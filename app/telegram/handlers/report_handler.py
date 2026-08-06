import uuid
from datetime import datetime, timedelta
from fastapi import HTTPException
from app.utils.constants import TZ_IST
from app.telegram.telegram_utils import send_telegram_reply
from app.dao.report_token_dao import ReportTokenDAO


class ReportHandler:
    @staticmethod
    async def generate_report_link(request_url, chat_id, user_id, supabase_admin):
        token = str(uuid.uuid4())
        expires_at = datetime.now(TZ_IST) + timedelta(hours=1)

        token_dao = ReportTokenDAO(supabase_admin)
        token_dao.create_token(token, user_id, expires_at)

        base_url = str(request_url).split('/webhook')[0]
        report_url = f"{base_url}/report/view/{token}"
        response_msg = (
            f"📊 *Next-Level AI Financial Report Generated*\n\n"
            f"Your interactive HTML report is ready with phase-by-phase analytics.\n\n"
            f"🔗 [View Downloadable Report]({report_url})\n\n"
            f"⏰ *Note:* This secure link will automatically expire in **1 hour**."
        )
        await send_telegram_reply(chat_id, response_msg)

    @staticmethod
    async def get_html_report(token: str, supabase_admin):
        token_dao = ReportTokenDAO(supabase_admin)
        token_data = token_dao.get_token(token)
        if not token_data:
            raise HTTPException(status_code=404, detail="Report link expired or invalid.")

        expires_at_str = token_data["expires_at"]
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        if datetime.now(TZ_IST) > expires_at:
            token_dao.delete_token(token)
            raise HTTPException(status_code=410, detail="Report link has expired.")

        user_id = token_data["user_id"]
        user_res = supabase_admin.table('users').select('*').eq('id', user_id).execute()
        user_name = user_res.data[0]['full_name'] if user_res.data else "Valued User"
        acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).execute()
        accounts = acc_res.data or []
        total_balance = sum(float(a['balance']) for a in accounts)
        txn_res = supabase_admin.table('transactions').select('*').eq('user_id', user_id).eq('soft_deleted',
                                                                                             False).order('date',
                                                                                                          desc=True).execute()
        txns = txn_res.data or []
        total_income = sum(float(t['amount']) for t in txns if t['txn_type'] == 'income')
        total_expense = sum(float(t['amount']) for t in txns if t['txn_type'] == 'expense')
        net_savings = total_income - total_expense
        accounts_html = "".join([
                                    f'<div class="bg-slate-950 border border-slate-800 p-4 rounded-xl flex justify-between items-center"><span class="font-semibold text-slate-200">{acc["account_name"]}</span><span class="font-mono text-emerald-400">₹{float(acc["balance"]):,.2f}</span></div>'
                                    for acc in accounts])
        txns_html = "".join([
                                f'<tr class="hover:bg-slate-800/50"><td class="py-3 px-4 text-slate-400">{datetime.fromisoformat(t["date"].replace("Z", "+00:00")).astimezone(TZ_IST).strftime("%d %b %Y")}</td><td class="py-3 px-4 font-medium text-white">{t["description"]}</td><td class="py-3 px-4 text-slate-400">{t["category"] or "Unassigned"}</td><td class="py-3 px-4"><span class="px-2 py-1 rounded-full text-xs font-semibold {"bg-emerald-500/20 text-emerald-300" if t["txn_type"] == "income" else "bg-rose-500/20 text-rose-300"}">{t["txn_type"].upper()}</span></td><td class="py-3 px-4 text-right font-mono {"text-emerald-400" if t["txn_type"] == "income" else "text-rose-400"}">{"+" if t["txn_type"] == "income" else "-"} ₹{float(t["amount"]):,.2f}</td></tr>'
                                for t in txns[:50]])
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PocketMunim AI Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>body {{ font-family: sans-serif; }}</style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen py-10 px-4">
    <div class="max-w-5xl mx-auto space-y-8">
        <div class="bg-slate-900 border border-slate-800 rounded-3xl p-8 flex justify-between">
            <div>
                <h1 class="text-3xl font-bold text-white">Dashboard: {user_name}</h1>
            </div>
            <div class="text-right">
                <p class="text-xs text-slate-400">Net Worth / Balance</p>
                <p class="text-2xl font-extrabold text-emerald-400">₹{total_balance:,.2f}</p>
            </div>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-6">
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 border-l-4 border-l-emerald-500">
                <p class="text-sm text-slate-400">Total Income</p>
                <p class="text-2xl font-bold text-emerald-400">₹{total_income:,.2f}</p>
            </div>
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 border-l-4 border-l-rose-500">
                <p class="text-sm text-slate-400">Total Expenses</p>
                <p class="text-2xl font-bold text-rose-400">₹{total_expense:,.2f}</p>
            </div>
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 border-l-4 border-l-cyan-500">
                <p class="text-sm text-slate-400">Net Savings</p>
                <p class="text-2xl font-bold text-cyan-400">₹{net_savings:,.2f}</p>
            </div>
        </div>
        <div class="bg-slate-900 border border-slate-800 rounded-3xl p-6">
            <h2 class="text-xl font-bold text-white mb-4">Linked Bank Accounts</h2>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">{accounts_html}</div>
        </div>
        <div class="bg-slate-900 border border-slate-800 rounded-3xl p-6">
            <h2 class="text-xl font-bold text-white mb-4">Transaction History</h2>
            <table class="w-full text-left text-sm text-slate-300">
                <tbody class="divide-y divide-slate-800">{txns_html}</tbody>
            </table>
        </div>
    </div>
</body>
</html>"""

    @staticmethod
    async def monthly_summary(supabase_admin, chat_id, user_id, text):
        parts = text.replace("/monthly", "").strip().split()
        if len(parts) < 2:
            await send_telegram_reply(chat_id, "⚠️ Use format: `/monthly [Month] [Year]`")
            return
        try:
            target_dt = datetime.strptime(f"1 {parts[0][:3]} {parts[1]}", "%d %b %Y")
            start_date = target_dt.strftime("%Y-%m-%d")
            end_dt = target_dt.replace(year=target_dt.year + 1,
                                       month=1) if target_dt.month == 12 else target_dt.replace(
                month=target_dt.month + 1)
            end_date = end_dt.strftime("%Y-%m-%d")
            txns = supabase_admin.table('transactions').select('amount, txn_type').eq('user_id', user_id).gte('date',
                                                                                                              start_date).lt(
                'date', end_date).eq('soft_deleted', False).execute()
            total_income = sum(t['amount'] for t in txns.data if t['txn_type'] == 'income')
            total_expense = sum(t['amount'] for t in txns.data if t['txn_type'] == 'expense')
            reply = f"📊 *Monthly Report: {target_dt.strftime('%B %Y')}*\n\n🟢 *Total Income:* ₹{total_income:,.2f}\n🔴 *Total Expense:* ₹{total_expense:,.2f}\n------------------------\n💡 *Net Saved:* ₹{(total_income - total_expense):,.2f}"
            await send_telegram_reply(chat_id, reply)
        except ValueError:
            await send_telegram_reply(chat_id, "⚠️ Invalid date format.")