import os
import time
import json
import base64
import hmac
import hashlib
from datetime import datetime, timezone
from decimal import Decimal

from app.interfaces.notification_gateway import TelegramNotificationAdapter
from app.utils.constants import TZ_IST


class ReportHandler:

    @staticmethod
    def _create_magic_token(user_id: str) -> str:
        """Generates a secure, stateless, 1-hour expiration JWT-style token."""
        secret = os.getenv("TELEGRAM_BOT_TOKEN", "default_secret").encode()
        payload = {"uid": user_id, "exp": int(time.time()) + 3600}
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        sig = hmac.new(secret, payload_b64.encode(), hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
        return f"{payload_b64}.{sig_b64}"

    @staticmethod
    def _verify_magic_token(token: str) -> str:
        """Verifies signature and expiration. Returns user_id if valid, else None."""
        try:
            secret = os.getenv("TELEGRAM_BOT_TOKEN", "default_secret").encode()
            parts = token.split(".")
            if len(parts) != 2:
                return None
            payload_b64, sig_b64 = parts[0], parts[1]
            expected_sig = hmac.new(secret, payload_b64.encode(), hashlib.sha256).digest()
            expected_sig_b64 = base64.urlsafe_b64encode(expected_sig).decode().rstrip("=")
            if not hmac.compare_digest(sig_b64, expected_sig_b64):
                return None
            payload_padded = payload_b64 + "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_padded).decode())
            if payload.get("exp", 0) < int(time.time()):
                return None
            return payload.get("uid")
        except Exception:
            return None

    @staticmethod
    async def generate_report_link(base_url: str, chat_id: int, user_id: str, supabase_admin):
        """Generates the magic link and sends it to the user via Telegram."""
        gateway = TelegramNotificationAdapter()
        token = ReportHandler._create_magic_token(user_id)
        clean_url = str(base_url).split('/webhook')[0].split('/process-task')[0].rstrip('/')
        dashboard_url = f"{clean_url}/report/view/{token}"

        message = (
            "📊 *Your Advanced Wealth Hub is Ready*\n"
            "_Equipped with density plots, proportional treemaps, and interactive ledgers._\n\n"
            "🔐 *Security Notice:* This magic link is cryptographically signed and expires in 60 minutes."
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "🌐 Open Financial Cockpit", "url": dashboard_url}]
            ]
        }
        await gateway.send_message(str(chat_id), message, reply_markup=keyboard)

    @staticmethod
    async def monthly_summary(supabase_admin, chat_id, user_id, text):
        """Generates a quick text-based monthly summary inside Telegram."""
        gateway = TelegramNotificationAdapter()
        current_dt = datetime.now(TZ_IST)
        start_of_month = current_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

        try:
            res = supabase_admin.table('transactions').select('*').eq('user_id', user_id).gte('date',
                                                                                              start_of_month).eq(
                'soft_deleted', False).execute()
            txns = res.data or []

            if not txns:
                await gateway.send_message(str(chat_id), "📭 No transactions recorded this month.")
                return

            income = sum(Decimal(str(t['amount'])) for t in txns if t['txn_type'] in ['income', 'borrow'])
            expenses = sum(
                Decimal(str(t['amount'])) for t in txns if t['txn_type'] in ['expense', 'loan_payment', 'lend'])

            msg = (
                f"📅 *{current_dt.strftime('%B %Y')} Summary*\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"🟩 *Total Income:* ₹{income:,.2f}\n"
                f"🟥 *Total Expenses:* ₹{expenses:,.2f}\n"
                f"📈 *Net Savings:* ₹{(income - expenses):,.2f}\n\n"
                f"Tap below for your advanced visual Wealth Hub."
            )
            keyboard = {
                "inline_keyboard": [
                    [{"text": "📊 Open Wealth Hub", "callback_data": "menu_report"}]
                ]
            }
            await gateway.send_message(str(chat_id), msg, reply_markup=keyboard)
        except Exception as e:
            await gateway.send_message(str(chat_id), f"❌ Failed to generate summary: `{str(e)}`")

    @staticmethod
    async def get_html_report(token: str, supabase_admin, request) -> str:
        """Renders the HTML Dashboard featuring Density Plots and Treemaps."""
        user_id = ReportHandler._verify_magic_token(token)

        if not user_id:
            return """
            <html><body style="background-color:#0f172a; color:#f87171; font-family:sans-serif; text-align:center; padding-top:20%;">
                <h1 style="font-size:24px; margin-bottom:10px;">⚠️ Security Exception</h1>
                <p style="color:#9ca3af;">This magic link has expired or is invalid.</p>
                <p style="color:#9ca3af;">Please request a new dashboard link via Telegram.</p>
            </body></html>
            """

        try:
            query_params = request.query_params
            current_dt = datetime.now(TZ_IST)

            default_start = current_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            default_end = current_dt

            start_str = query_params.get("start", default_start.strftime("%Y-%m-%d"))
            end_str = query_params.get("end", default_end.strftime("%Y-%m-%d"))

            try:
                start_dt = datetime.strptime(start_str, "%Y-%m-%d").replace(hour=0, minute=0, second=0, tzinfo=TZ_IST)
                end_dt = datetime.strptime(end_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=TZ_IST)
            except ValueError:
                start_dt = default_start
                end_dt = default_end

            acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).execute()
            accounts = acc_res.data or []
            liquid_cash = sum(Decimal(str(a['balance'])) for a in accounts)

            loan_res = supabase_admin.table('loans').select('*, emi_schedules(*)').eq('user_id', user_id).eq(
                'is_active', True).execute()
            loans = loan_res.data or []
            total_debt = Decimal('0.00')
            for loan in loans:
                paid_emis = [e for e in loan.get('emi_schedules', []) if e['status'] == 'PAID']
                if paid_emis:
                    paid_emis = sorted(paid_emis, key=lambda x: x['installment_number'])
                    total_debt += Decimal(str(paid_emis[-1]['remaining_balance']))
                else:
                    total_debt += Decimal(str(loan['principal_amount']))

            start_iso = start_dt.astimezone(timezone.utc).isoformat()
            end_iso = end_dt.astimezone(timezone.utc).isoformat()

            txn_res = supabase_admin.table('transactions').select('*').eq('user_id', user_id).gte('date',
                                                                                                  start_iso).lte('date',
                                                                                                                 end_iso).eq(
                'soft_deleted', False).order('date', desc=True).execute()
            txns = txn_res.data or []

            total_income = sum(Decimal(str(t['amount'])) for t in txns if t['txn_type'] in ['income', 'borrow'])
            total_expenses = sum(
                Decimal(str(t['amount'])) for t in txns if t['txn_type'] in ['expense', 'loan_payment', 'lend'])
            net_savings = total_income - total_expenses

            # Category Totals
            category_totals = {}
            for t in txns:
                if t['txn_type'] in ['expense', 'loan_payment']:
                    cat = t.get('category', 'Uncategorized').title()
                    category_totals[cat] = category_totals.get(cat, 0.0) + float(t['amount'])
            sorted_cats = dict(sorted(category_totals.items(), key=lambda item: item[1], reverse=True))

            # Density Plot Distribution Bins
            density_bins = {"< ₹500": 0, "₹500 - ₹2k": 0, "₹2k - ₹5k": 0, "₹5k - ₹10k": 0, "> ₹10k": 0}
            for t in txns:
                if t['txn_type'] in ['expense', 'loan_payment']:
                    amt = float(t['amount'])
                    if amt < 500:
                        density_bins["< ₹500"] += 1
                    elif amt < 2000:
                        density_bins["₹500 - ₹2k"] += 1
                    elif amt < 5000:
                        density_bins["₹2k - ₹5k"] += 1
                    elif amt < 10000:
                        density_bins["₹5k - ₹10k"] += 1
                    else:
                        density_bins["> ₹10k"] += 1

            chart_data = {
                "density": {"labels": list(density_bins.keys()), "data": list(density_bins.values())}
            }

            formatted_txns = []
            available_accounts = set()
            available_categories = set()
            for t in txns:
                dt_ist = datetime.fromisoformat(t['date']).astimezone(TZ_IST)
                acc = t.get('source_account') or t.get('destination_account') or 'Primary'
                cat = t.get('category', 'General').title()
                available_accounts.add(acc)
                available_categories.add(cat)

                formatted_txns.append({
                    "date_sort": t['date'],
                    "description": t['description'],
                    "category": cat,
                    "amount": float(t['amount']),
                    "type": t['txn_type'],
                    "account": acc,
                    "date_display": dt_ist.strftime('%b %d, %Y, %I:%M %p')
                })

            html_template = """
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>PocketMunim | Advanced Wealth Hub</title>
                <script src="https://cdn.tailwindcss.com"></script>
                <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
                <style>
                    body { background-color: #0f172a; color: #f3f4f6; }
                    .glass-card { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(10px); border: 1px solid rgba(51, 65, 85, 0.5); }
                    @media print {
                        body { background-color: #ffffff !important; color: #000000 !important; }
                        .glass-card { background: #ffffff !important; border: 1px solid #cbd5e1 !important; color: #000 !important; box-shadow: none !important; }
                        .no-print { display: none !important; }
                    }
                </style>
            </head>
            <body class="min-h-screen p-4 md:p-8 font-sans flex flex-col justify-between">

                <div class="max-w-7xl mx-auto w-full">
                    <!-- HEADER -->
                    <div class="flex flex-col md:flex-row items-start md:items-center justify-between mb-8 pb-4 border-b border-gray-800 gap-4">
                        <div>
                            <h1 class="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-purple-400 to-cyan-400">PocketMunim</h1>
                            <p class="text-gray-400 text-sm mt-1">Advanced Financial Cockpit</p>
                        </div>

                        <form method="GET" class="flex flex-wrap items-center gap-2 bg-gray-900/80 p-2 rounded-xl border border-gray-800 no-print">
                            <span class="text-xs text-gray-400 px-2 font-medium">From:</span>
                            <input type="date" name="start" value="__START_VAL__" class="bg-gray-800 text-sm text-white px-3 py-1.5 rounded-lg border border-gray-700 focus:outline-none focus:border-cyan-500">
                            <span class="text-xs text-gray-400 px-2 font-medium">To:</span>
                            <input type="date" name="end" value="__END_VAL__" class="bg-gray-800 text-sm text-white px-3 py-1.5 rounded-lg border border-gray-700 focus:outline-none focus:border-cyan-500">
                            <button type="submit" class="bg-cyan-600 hover:bg-cyan-500 text-white text-sm font-medium px-4 py-1.5 rounded-lg transition">Apply</button>
                            <button type="button" onclick="window.print()" class="bg-purple-600 hover:bg-purple-500 text-white text-sm font-medium px-3 py-1.5 rounded-lg transition ml-2">📥 Export PDF</button>
                        </form>
                    </div>

                    <!-- FINANCIAL SNAPSHOT CARDS -->
                    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
                        <div class="glass-card p-5 rounded-2xl">
                            <p class="text-xs text-gray-400 uppercase tracking-wider mb-1">Total Available Cash</p>
                            <p class="text-2xl font-bold text-white">__LIQUID_CASH__</p>
                            <span class="text-xs text-gray-500 mt-1 block">Liquid bank balances</span>
                        </div>
                        <div class="glass-card p-5 rounded-2xl border-l-4 border-l-cyan-500">
                            <p class="text-xs text-gray-400 uppercase tracking-wider mb-1">Net Savings (Money Kept)</p>
                            <p class="text-2xl font-bold text-cyan-400">__NET_SAVINGS__</p>
                            <span class="text-xs text-gray-500 mt-1 block">Income minus Expenses</span>
                        </div>
                        <div class="glass-card p-5 rounded-2xl border-l-4 border-l-green-500">
                            <p class="text-xs text-gray-400 uppercase tracking-wider mb-1">Total Income</p>
                            <p class="text-2xl font-bold text-green-400">__TOTAL_INCOME__</p>
                            <span class="text-xs text-gray-500 mt-1 block">Selected period inflow</span>
                        </div>
                        <div class="glass-card p-5 rounded-2xl border-l-4 border-l-red-500">
                            <p class="text-xs text-gray-400 uppercase tracking-wider mb-1">Total Expenses</p>
                            <p class="text-2xl font-bold text-red-400">__TOTAL_EXPENSES__</p>
                            <span class="text-xs text-gray-500 mt-1 block">Selected period outflow</span>
                        </div>
                    </div>

                    <!-- ADVANCED VISUAL SUITE -->
                    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
                        <div class="glass-card p-6 rounded-2xl flex flex-col justify-between">
                            <div class="flex items-center justify-between mb-4">
                                <h2 class="text-base font-semibold text-gray-200">Amount Density Plot</h2>
                                <button onclick="downloadChart('densityChart', 'density-plot.png')" class="text-xs text-cyan-400 hover:underline no-print">📥 PNG</button>
                            </div>
                            <div class="relative w-full aspect-square max-h-[220px] mx-auto">
                                <canvas id="densityChart"></canvas>
                            </div>
                        </div>

                        <div class="glass-card p-6 rounded-2xl flex flex-col justify-between">
                            <div class="flex items-center justify-between mb-4">
                                <h2 class="text-base font-semibold text-gray-200">Proportional Treemap</h2>
                                <span class="text-xs text-gray-400">Share %</span>
                            </div>
                            <div class="flex flex-col gap-2 overflow-y-auto max-h-[220px] pr-1">
                                __TREEMAP_BLOCKS__
                            </div>
                        </div>
                    </div>

                    <!-- ADVANCED INTERACTIVE LEDGER -->
                    <div class="glass-card p-6 rounded-2xl mb-8">
                        <div class="flex flex-col md:flex-row items-start md:items-center justify-between mb-6 gap-4">
                            <h2 class="text-lg font-semibold text-gray-200">Transaction History</h2>
                            <button onclick="exportTableToCSV('pocketmunim-transactions.csv')" class="bg-gray-800 hover:bg-gray-700 text-cyan-400 border border-gray-700 text-sm font-medium px-4 py-2 rounded-xl transition no-print">📥 Download Excel (CSV)</button>
                        </div>

                        <div class="flex flex-wrap items-center justify-between gap-4 mb-6 no-print">
                            <div class="flex items-center gap-2">
                                <span class="text-sm text-gray-400">Show</span>
                                <select id="pageSizeSelect" onchange="changePageSize()" class="bg-gray-800 text-sm text-white px-3 py-1.5 rounded-xl border border-gray-700 focus:outline-none">
                                    <option value="10">10</option>
                                    <option value="25">25</option>
                                    <option value="50" selected>50</option>
                                    <option value="100">100</option>
                                </select>
                                <span class="text-sm text-gray-400">entries</span>
                            </div>

                            <div class="flex flex-wrap items-center gap-3">
                                <input type="text" id="searchInput" oninput="filterTable()" placeholder="🔍 Search description..." class="bg-gray-800 text-sm text-white px-4 py-2 rounded-xl border border-gray-700 focus:outline-none focus:border-cyan-500 w-52">

                                <select id="accountFilter" onchange="filterTable()" class="bg-gray-800 text-sm text-white px-3 py-2 rounded-xl border border-gray-700 focus:outline-none">
                                    <option value="">All Accounts</option>
                                    __ACCOUNT_OPTIONS__
                                </select>

                                <select id="categoryFilter" onchange="filterTable()" class="bg-gray-800 text-sm text-white px-3 py-2 rounded-xl border border-gray-700 focus:outline-none">
                                    <option value="">All Categories</option>
                                    __CATEGORY_OPTIONS__
                                </select>
                            </div>
                        </div>

                        <div class="overflow-x-auto">
                            <table class="w-full text-left border-collapse" id="ledgerTable">
                                <thead>
                                    <tr class="text-gray-400 text-xs uppercase tracking-wider border-b border-gray-800 bg-gray-900/50">
                                        <th onclick="sortTable(0)" class="px-4 py-3 font-semibold cursor-pointer hover:text-white">Date (IST) ↕</th>
                                        <th onclick="sortTable(1)" class="px-4 py-3 font-semibold cursor-pointer hover:text-white">Description ↕</th>
                                        <th onclick="sortTable(2)" class="px-4 py-3 font-semibold cursor-pointer hover:text-white">Category ↕</th>
                                        <th onclick="sortTable(3)" class="px-4 py-3 font-semibold cursor-pointer hover:text-white text-right">Amount ↕</th>
                                        <th onclick="sortTable(4)" class="px-4 py-3 font-semibold cursor-pointer hover:text-white">Account ↕</th>
                                    </tr>
                                </thead>
                                <tbody id="tableBody" class="divide-y divide-gray-800/60">
                                </tbody>
                            </table>
                        </div>

                        <div class="flex flex-col md:flex-row items-center justify-between mt-6 gap-4 text-sm text-gray-400 no-print">
                            <div id="tableInfo">Showing 0 to 0 of 0 entries</div>
                            <div class="flex items-center gap-2">
                                <button onclick="prevPage()" id="prevBtn" class="bg-gray-800 hover:bg-gray-700 text-white px-4 py-2 rounded-xl border border-gray-700 transition disabled:opacity-40 disabled:cursor-not-allowed">« Previous</button>
                                <span id="pageIndicator" class="px-3 font-medium text-gray-300">Page 1 of 1</span>
                                <button onclick="nextPage()" id="nextBtn" class="bg-gray-800 hover:bg-gray-700 text-white px-4 py-2 rounded-xl border border-gray-700 transition disabled:opacity-40 disabled:cursor-not-allowed">Next »</button>
                            </div>
                        </div>
                    </div>

                </div>

                <footer class="max-w-7xl mx-auto w-full text-center text-xs text-gray-500 pt-6 border-t border-gray-800 mt-12">
                    © 2026 Ishita Financial Intelligence (I) Pvt. Ltd. All rights reserved.
                </footer>

                <script>
                    const rawTransactions = __TXN_JSON__;
                    const chartData = __CHART_JSON__;

                    let filteredData = [...rawTransactions];
                    let currentPage = 1;
                    let pageSize = 50;
                    let sortColumn = -1;
                    let sortAsc = true;

                    window.addEventListener('DOMContentLoaded', () => {
                        const ctxDensity = document.getElementById('densityChart').getContext('2d');
                        new Chart(ctxDensity, {
                            type: 'bar',
                            data: {
                                labels: chartData.density.labels,
                                datasets: [{
                                    label: 'Frequency',
                                    data: chartData.density.data,
                                    backgroundColor: '#c084fc',
                                    borderRadius: 6
                                }]
                            },
                            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#9ca3af' } }, y: { ticks: { color: '#9ca3af' } } } }
                        });

                        filterTable();
                    });

                    function filterTable() {
                        const search = document.getElementById('searchInput').value.toLowerCase();
                        const acc = document.getElementById('accountFilter').value;
                        const cat = document.getElementById('categoryFilter').value;

                        filteredData = rawTransactions.filter(t => {
                            const matchSearch = t.description.toLowerCase().includes(search) || t.category.toLowerCase().includes(search);
                            const matchAcc = !acc || t.account === acc;
                            const matchCat = !cat || t.category === cat;
                            return matchSearch && matchAcc && matchCat;
                        });

                        currentPage = 1;
                        renderTable();
                    }

                    function renderTable() {
                        const tbody = document.getElementById('tableBody');
                        tbody.innerHTML = '';

                        const start = (currentPage - 1) * pageSize;
                        const end = start + parseInt(pageSize);
                        const pageData = filteredData.slice(start, end);

                        if (pageData.length === 0) {
                            tbody.innerHTML = `<tr><td colspan="5" class="px-4 py-8 text-center text-gray-500">No transactions found.</td></tr>`;
                            document.getElementById('tableInfo').innerText = "Showing 0 to 0 of 0 entries";
                            document.getElementById('pageIndicator').innerText = "Page 1 of 1";
                            document.getElementById('prevBtn').disabled = true;
                            document.getElementById('nextBtn').disabled = true;
                            return;
                        }

                        pageData.forEach(t => {
                            const isExpense = ['expense', 'loan_payment'].includes(t.type);
                            const color = isExpense ? 'text-red-400' : (t.type === 'income' ? 'text-green-400' : 'text-blue-400');
                            const sign = isExpense ? '-' : '+';

                            tbody.innerHTML += `
                                <tr class="hover:bg-gray-800/40 transition">
                                    <td class="px-4 py-3 text-sm text-gray-300 whitespace-nowrap">${t.date_display}</td>
                                    <td class="px-4 py-3 text-sm text-white font-medium">${t.description}</td>
                                    <td class="px-4 py-3 text-sm text-gray-400">${t.category}</td>
                                    <td class="px-4 py-3 text-sm ${color} font-bold text-right whitespace-nowrap">${sign}₹${t.amount.toLocaleString('en-IN', {minimumFractionDigits: 2})}</td>
                                    <td class="px-4 py-3 text-sm text-gray-400">${t.account}</td>
                                </tr>
                            `;
                        });

                        const totalPages = Math.ceil(filteredData.length / pageSize) || 1;
                        document.getElementById('tableInfo').innerText = `Showing ${start + 1} to ${Math.min(end, filteredData.length)} of ${filteredData.length} entries`;
                        document.getElementById('pageIndicator').innerText = `Page ${currentPage} of ${totalPages}`;
                        document.getElementById('prevBtn').disabled = currentPage === 1;
                        document.getElementById('nextBtn').disabled = currentPage >= totalPages;
                    }

                    function changePageSize() {
                        pageSize = document.getElementById('pageSizeSelect').value;
                        currentPage = 1;
                        renderTable();
                    }

                    function prevPage() {
                        if (currentPage > 1) {
                            currentPage--;
                            renderTable();
                        }
                    }

                    function nextPage() {
                        const totalPages = Math.ceil(filteredData.length / pageSize);
                        if (currentPage < totalPages) {
                            currentPage++;
                            renderTable();
                        }
                    }

                    function sortTable(colIndex) {
                        if (sortColumn === colIndex) {
                            sortAsc = !sortAsc;
                        } else {
                            sortColumn = colIndex;
                            sortAsc = true;
                        }

                        const keys = ['date_sort', 'description', 'category', 'amount', 'account'];
                        const key = keys[colIndex];

                        filteredData.sort((a, b) => {
                            let valA = a[key];
                            let valB = b[key];

                            if (colIndex === 3) {
                                // Numeric sort for Amount
                                valA = parseFloat(valA);
                                valB = parseFloat(valB);
                            } else if (colIndex === 0) {
                                // Date sort using ISO string
                                valA = new Date(valA).getTime();
                                valB = new Date(valB).getTime();
                            } else {
                                // String sort for Description, Category, Account
                                valA = String(valA).toLowerCase();
                                valB = String(valB).toLowerCase();
                            }

                            if (valA < valB) return sortAsc ? -1 : 1;
                            if (valA > valB) return sortAsc ? 1 : -1;
                            return 0;
                        });

                        renderTable();
                    }

                    function downloadChart(canvasId, filename) {
                        const canvas = document.getElementById(canvasId);
                        const url = canvas.toDataURL('image/png');
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = filename;
                        a.click();
                    }

                    function exportTableToCSV(filename) {
                        let csv = 'Date,Description,Category,Amount,Type,Account\\n';
                        filteredData.forEach(t => {
                            csv += `"${t.date_display}","${t.description}","${t.category}",${t.amount},"${t.type}","${t.account}"\\n`;
                        });
                        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = filename;
                        a.click();
                    }
                </script>
            </body>
            </html>
            """

            treemap_html = ""
            max_cat_val = max(sorted_cats.values()) if sorted_cats else 1.0
            for cat, val in sorted_cats.items():
                pct = (val / float(total_expenses)) * 100 if total_expenses > 0 else 0
                width_pct = max(15, int((val / max_cat_val) * 100))
                treemap_html += f"""
                <div class="flex flex-col bg-gray-800/60 p-3 rounded-xl border border-gray-700/50">
                    <div class="flex justify-between text-xs font-medium text-gray-300 mb-1">
                        <span>{cat}</span>
                        <span class="text-cyan-400">₹{val:,.0f} ({pct:.1f}%)</span>
                    </div>
                    <div class="w-full bg-gray-900 h-2.5 rounded-full overflow-hidden">
                        <div class="bg-gradient-to-r from-purple-500 to-cyan-400 h-2.5 rounded-full" style="width: {width_pct}%;"></div>
                    </div>
                </div>
                """
            if not treemap_html:
                treemap_html = '<p class="text-xs text-gray-500 text-center py-4">No expense data available</p>'

            acc_options = "".join([f'<option value="{acc}">{acc}</option>' for acc in sorted(available_accounts)])
            cat_options = "".join([f'<option value="{cat}">{cat}</option>' for cat in sorted(available_categories)])

            html_output = html_template.replace("__START_VAL__", start_str)
            html_output = html_output.replace("__END_VAL__", end_str)
            html_output = html_output.replace("__LIQUID_CASH__", f"₹{liquid_cash:,.2f}")
            html_output = html_output.replace("__NET_SAVINGS__", f"₹{net_savings:,.2f}")
            html_output = html_output.replace("__TOTAL_INCOME__", f"₹{total_income:,.2f}")
            html_output = html_output.replace("__TOTAL_EXPENSES__", f"₹{total_expenses:,.2f}")
            html_output = html_output.replace("__TREEMAP_BLOCKS__", treemap_html)
            html_output = html_output.replace("__ACCOUNT_OPTIONS__", acc_options)
            html_output = html_output.replace("__CATEGORY_OPTIONS__", cat_options)
            html_output = html_output.replace("__CHART_JSON__", json.dumps(chart_data))
            html_output = html_output.replace("__TXN_JSON__", json.dumps(formatted_txns))

            return html_output

        except Exception as e:
            return f"<html><body style='background:#0f172a; color:#f87171; text-align:center; padding-top:20%; font-family:sans-serif;'><h1>Dashboard Error</h1><p>{str(e)}</p></body></html>"