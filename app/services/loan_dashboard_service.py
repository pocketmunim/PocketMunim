import json
from app.telegram.handlers.report_handler import ReportHandler

class LoanDashboardService:
    @staticmethod
    async def render_dashboard(token: str, supabase_admin) -> str:
        """Renders the highly advanced HTML Dashboard for Loans using Glassmorphism."""
        user_id = ReportHandler._verify_magic_token(token)
        if not user_id:
            return """
            <html><body style="background-color:#0f172a; color:#f87171; font-family:sans-serif; text-align:center; padding-top:20%;">
                <h1 style="font-size:24px; margin-bottom:10px;">🔒 Security Exception</h1>
                <p style="color:#9ca3af;">This magic link has expired or is invalid.</p>
            </body></html>
            """
            
        try:
            # Fetch user name
            user_res = supabase_admin.table('users').select('full_name').eq('telegram_id', user_id).execute()
            user_name = user_res.data[0]['full_name'] if user_res.data else "Valued Member"

            # Fetch all loans and schedules
            loan_res = supabase_admin.table('loans').select('*, emi_schedules(*)').eq('user_id', user_id).execute()
            loans = loan_res.data or []

            # Calculate Global Metrics
            total_original_principal = sum(float(l['principal_amount']) for l in loans)
            total_outstanding = 0.0
            total_emis_paid = 0
            total_interest_paid = 0.0
            
            clean_loans_data = []

            for loan in loans:
                schedules = sorted(loan.get('emi_schedules', []), key=lambda x: x['installment_number'])
                paid_emis = [e for e in schedules if e['status'] == 'PAID']
                
                total_emis_paid += len(paid_emis)
                total_interest_paid += sum(float(e['interest_component']) for e in paid_emis)
                
                if paid_emis:
                    outstanding = float(paid_emis[-1]['remaining_balance'])
                else:
                    outstanding = float(loan['principal_amount'])
                
                if not loan.get('is_active'):
                    outstanding = 0.0
                    
                total_outstanding += outstanding
                
                clean_loans_data.append({
                    "lender": loan['lender'],
                    "principal": float(loan['principal_amount']),
                    "outstanding": outstanding,
                    "rate": float(loan['annual_interest_rate']),
                    "is_active": loan['is_active'],
                    "schedules": [
                        {
                            "due_date": s['due_date'],
                            "emi_amount": float(s['emi_amount']),
                            "principal_comp": float(s['principal_component']),
                            "interest_comp": float(s['interest_component']),
                            "remaining": float(s['remaining_balance']),
                            "status": s['status']
                        } for s in schedules
                    ]
                })

            debt_ratio = (total_outstanding / total_original_principal * 100) if total_original_principal > 0 else 0

            # Advanced Glassmorphism Template
            html_template = """
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>PocketMunim | Loan Analytics</title>
                <script src="https://cdn.tailwindcss.com"></script>
                <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
                <style>
                    body { 
                        background: radial-gradient(circle at top right, #1e1b4b, #0f172a, #000000); 
                        color: #f3f4f6; 
                        background-attachment: fixed;
                    }
                    .glass-panel { 
                        background: rgba(30, 41, 59, 0.4); 
                        backdrop-filter: blur(16px); 
                        -webkit-backdrop-filter: blur(16px);
                        border: 1px solid rgba(255, 255, 255, 0.08); 
                        box-shadow: 0 4px 30px rgba(0, 0, 0, 0.3);
                    }
                    .neon-text { text-shadow: 0 0 10px rgba(56, 189, 248, 0.5); }
                    
                    /* Custom Scrollbar */
                    ::-webkit-scrollbar { width: 8px; height: 8px; }
                    ::-webkit-scrollbar-track { background: rgba(0,0,0,0.2); border-radius: 10px; }
                    ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 10px; }
                    ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.4); }
                </style>
            </head>
            <body class="min-h-screen p-4 md:p-8 font-sans flex flex-col justify-between">
                <div class="max-w-7xl mx-auto w-full">
                    
                    <!-- HEADER -->
                    <div class="flex flex-col md:flex-row items-start md:items-center justify-between mb-8 pb-4 border-b border-gray-800/50 gap-4">
                        <div>
                            <h1 class="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-emerald-400">Amortization Engine</h1>
                            <p class="text-gray-400 text-sm mt-1">Debt Portfolio for __USER_NAME__</p>
                        </div>
                    </div>

                    <!-- KPI CARDS -->
                    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-10">
                        <div class="glass-panel p-6 rounded-3xl border-t-4 border-t-emerald-500">
                            <p class="text-xs text-gray-400 uppercase tracking-widest font-semibold mb-2">Total Outstanding</p>
                            <p class="text-3xl font-extrabold text-white neon-text">₹__TOTAL_OUTSTANDING__</p>
                            <div class="w-full bg-gray-800 rounded-full h-1.5 mt-4">
                                <div class="bg-gradient-to-r from-emerald-500 to-cyan-400 h-1.5 rounded-full" style="width: __DEBT_RATIO__%"></div>
                            </div>
                            <p class="text-[10px] text-gray-500 mt-2 text-right">__DEBT_RATIO__% of Original Debt</p>
                        </div>
                        <div class="glass-panel p-6 rounded-3xl border-t-4 border-t-blue-500">
                            <p class="text-xs text-gray-400 uppercase tracking-widest font-semibold mb-2">Total Original Debt</p>
                            <p class="text-3xl font-extrabold text-blue-400">₹__TOTAL_ORIGINAL__</p>
                            <p class="text-xs text-gray-500 mt-3">Across all registered loans</p>
                        </div>
                        <div class="glass-panel p-6 rounded-3xl border-t-4 border-t-orange-500">
                            <p class="text-xs text-gray-400 uppercase tracking-widest font-semibold mb-2">Interest Paid</p>
                            <p class="text-3xl font-extrabold text-orange-400">₹__TOTAL_INTEREST__</p>
                            <p class="text-xs text-gray-500 mt-3">Cost of borrowing to date</p>
                        </div>
                        <div class="glass-panel p-6 rounded-3xl border-t-4 border-t-purple-500">
                            <p class="text-xs text-gray-400 uppercase tracking-widest font-semibold mb-2">EMIs Settled</p>
                            <p class="text-3xl font-extrabold text-purple-400">__TOTAL_EMIS_PAID__</p>
                            <p class="text-xs text-gray-500 mt-3">Successful installments</p>
                        </div>
                    </div>

                    <!-- CHARTS SECTION -->
                    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-10">
                        
                        <!-- Portfolio Doughnut -->
                        <div class="glass-panel p-6 rounded-3xl flex flex-col items-center justify-center">
                            <h2 class="text-sm font-semibold text-gray-300 w-full mb-4 tracking-wider uppercase">Debt Distribution</h2>
                            <div class="relative w-full aspect-square max-h-[250px]">
                                <canvas id="portfolioChart"></canvas>
                            </div>
                        </div>

                        <!-- Debt Burndown Line Chart -->
                        <div class="glass-panel p-6 rounded-3xl lg:col-span-2">
                            <h2 class="text-sm font-semibold text-gray-300 mb-4 tracking-wider uppercase">Debt Burndown Projection</h2>
                            <div class="relative w-full h-[250px]">
                                <canvas id="burndownChart"></canvas>
                            </div>
                        </div>
                    </div>

                    <!-- COMBINED UPCOMING EMI SCHEDULE -->
                    <div class="glass-panel p-6 rounded-3xl mb-8">
                        <h2 class="text-lg font-bold text-white mb-6">Upcoming Scheduled EMIs (All Loans)</h2>
                        <div class="overflow-x-auto">
                            <table class="w-full text-left border-collapse" id="emiTable">
                                <thead>
                                    <tr class="text-gray-400 text-xs uppercase tracking-widest border-b border-gray-700/50">
                                        <th class="px-4 py-3 font-semibold">Due Date</th>
                                        <th class="px-4 py-3 font-semibold">Lender</th>
                                        <th class="px-4 py-3 font-semibold text-right">EMI Amount</th>
                                        <th class="px-4 py-3 font-semibold text-right hidden sm:table-cell">Principal Cut</th>
                                        <th class="px-4 py-3 font-semibold text-right hidden sm:table-cell">Interest Cut</th>
                                    </tr>
                                </thead>
                                <tbody id="tableBody" class="divide-y divide-gray-700/30">
                                    <!-- Populated via JS -->
                                </tbody>
                            </table>
                        </div>
                    </div>

                </div>

                <footer class="max-w-7xl mx-auto w-full text-center text-xs text-gray-500 pt-6 mt-12 border-t border-gray-800/50">
                    &copy; 2026 Ishita Financial Intelligence (I) Pvt. Ltd. | Amortization Engine
                </footer>

                <script>
                    const loansData = __LOANS_JSON__;
                    
                    window.addEventListener('DOMContentLoaded', () => {
                        const activeLoans = loansData.filter(l => l.is_active && l.outstanding > 0);
                        const labels = activeLoans.map(l => l.lender);
                        const data = activeLoans.map(l => l.outstanding);
                        
                        const ctxPie = document.getElementById('portfolioChart').getContext('2d');
                        new Chart(ctxPie, {
                            type: 'doughnut',
                            data: {
                                labels: labels.length > 0 ? labels : ['No Debt'],
                                datasets: [{
                                    data: data.length > 0 ? data : [1],
                                    backgroundColor: ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444'],
                                    borderWidth: 0,
                                    hoverOffset: 4
                                }]
                            },
                            options: {
                                responsive: true, maintainAspectRatio: false,
                                cutout: '75%',
                                plugins: { legend: { position: 'bottom', labels: { color: '#9ca3af', usePointStyle: true, boxWidth: 8 } } }
                            }
                        });

                        let allPending = [];
                        loansData.forEach(loan => {
                            if (loan.is_active) {
                                const pending = loan.schedules.filter(s => s.status === 'PENDING');
                                pending.slice(0, 12).forEach(p => {
                                    allPending.push({ lender: loan.lender, ...p });
                                });
                            }
                        });
                        
                        allPending.sort((a, b) => new Date(a.due_date) - new Date(b.due_date));
                        
                        const tbody = document.getElementById('tableBody');
                        if (allPending.length === 0) {
                            tbody.innerHTML = `<tr><td colspan="5" class="px-4 py-8 text-center text-gray-500">No upcoming EMIs. You are debt-free!</td></tr>`;
                        } else {
                            allPending.slice(0, 20).forEach(emi => {
                                tbody.innerHTML += `
                                    <tr class="hover:bg-white/5 transition duration-200">
                                        <td class="px-4 py-3 text-sm text-gray-300 whitespace-nowrap">${emi.due_date}</td>
                                        <td class="px-4 py-3 text-sm text-white font-medium">${emi.lender.toUpperCase()}</td>
                                        <td class="px-4 py-3 text-sm text-cyan-400 font-bold text-right">₹${emi.emi_amount.toLocaleString('en-IN', {minimumFractionDigits: 2})}</td>
                                        <td class="px-4 py-3 text-sm text-gray-400 text-right hidden sm:table-cell">₹${emi.principal_comp.toLocaleString('en-IN', {minimumFractionDigits: 2})}</td>
                                        <td class="px-4 py-3 text-sm text-orange-400/80 text-right hidden sm:table-cell">₹${emi.interest_comp.toLocaleString('en-IN', {minimumFractionDigits: 2})}</td>
                                    </tr>
                                `;
                            });
                        }

                        let timelineMap = {};
                        loansData.forEach(loan => {
                            loan.schedules.forEach(sched => {
                                const monthKey = sched.due_date.substring(0, 7);
                                if (!timelineMap[monthKey]) timelineMap[monthKey] = 0;
                                timelineMap[monthKey] += sched.remaining;
                            });
                        });

                        const sortedMonths = Object.keys(timelineMap).sort();
                        const burndownData = sortedMonths.map(m => timelineMap[m]);

                        const ctxLine = document.getElementById('burndownChart').getContext('2d');
                        new Chart(ctxLine, {
                            type: 'line',
                            data: {
                                labels: sortedMonths,
                                datasets: [{
                                    label: 'Total Debt Remaining',
                                    data: burndownData,
                                    borderColor: '#10b981',
                                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                                    borderWidth: 2,
                                    fill: true,
                                    tension: 0.4,
                                    pointRadius: 0,
                                    pointHoverRadius: 6
                                }]
                            },
                            options: { 
                                responsive: true, maintainAspectRatio: false, 
                                plugins: { legend: { display: false } }, 
                                scales: { 
                                    x: { grid: { display: false, color: '#334155' }, ticks: { color: '#64748b', maxTicksLimit: 12 } }, 
                                    y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#64748b' } } 
                                },
                                interaction: { intersect: false, mode: 'index' }
                            }
                        });
                    });
                </script>
            </body>
            </html>
            """

            # Text replacements
            html_output = html_template.replace("__USER_NAME__", user_name)
            html_output = html_output.replace("__TOTAL_OUTSTANDING__", f"{total_outstanding:,.2f}")
            html_output = html_output.replace("__TOTAL_ORIGINAL__", f"{total_original_principal:,.2f}")
            html_output = html_output.replace("__TOTAL_INTEREST__", f"{total_interest_paid:,.2f}")
            html_output = html_output.replace("__TOTAL_EMIS_PAID__", str(total_emis_paid))
            html_output = html_output.replace("__DEBT_RATIO__", f"{debt_ratio:.1f}")
            html_output = html_output.replace("__LOANS_JSON__", json.dumps(clean_loans_data))

            return html_output

        except Exception as e:
            return f"<html><body style='background:#0f172a; color:#f87171; text-align:center; padding-top:20%; font-family:sans-serif;'><h1>Engine Error</h1><p>{str(e)}</p></body></html>"