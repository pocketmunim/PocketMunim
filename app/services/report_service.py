from typing import Dict, Any, List
from supabase import Client

class ReportService:
    @staticmethod
    def generate_intelligence_report(
        db: Client,
        user_id: str,
        start_date: str,
        end_date: str
    ) -> Dict[str, Any]:
        uid = str(user_id)

        # 1. Fetch Transactions in Selected Date Window
        tx_res = db.table('transactions')\
            .select('*')\
            .eq('user_id', uid)\
            .gte('transaction_date', start_date)\
            .lte('transaction_date', end_date)\
            .order('transaction_date', desc=True)\
            .execute()
        transactions = tx_res.data or []

        # 2. Fetch Active Accounts Liquidity
        acc_res = db.table('accounts')\
            .select('*')\
            .eq('user_id', uid)\
            .eq('is_active', True)\
            .execute()
        accounts = acc_res.data or []
        total_liquidity = sum(float(a.get('balance') or 0.0) for a in accounts)

        # 3. Fetch Active Debt Summary
        loans_res = db.table('loans')\
            .select('*')\
            .eq('user_id', uid)\
            .eq('status', 'ACTIVE')\
            .execute()
        loans = loans_res.data or []
        total_debt = sum(float(l.get('pending_principal') or 0.0) for l in loans if l.get('loan_type') == 'BORROWED')
        total_receivable = sum(float(l.get('pending_principal') or 0.0) for l in loans if l.get('loan_type') == 'LENT')

        # 4. Aggregations & Category Distribution
        total_inflow = 0.0
        total_outflow = 0.0
        category_map: Dict[str, float] = {}

        for tx in transactions:
            amt = float(tx.get('amount') or 0.0)
            ttype = tx.get('type')
            cat = tx.get('category') or 'Uncategorized'

            if ttype == 'CREDIT':
                total_inflow += amt
            elif ttype == 'DEBIT':
                total_outflow += amt
                category_map[cat] = round(category_map.get(cat, 0.0) + amt, 2)

        net_savings = round(total_inflow - total_outflow, 2)
        savings_rate = round((net_savings / total_inflow * 100), 1) if total_inflow > 0 else 0.0

        # Format Categories for UI Pie/Donut Chart
        category_distribution = []
        for cat, val in sorted(category_map.items(), key=lambda x: x[1], reverse=True):
            pct = round((val / total_outflow * 100), 1) if total_outflow > 0 else 0.0
            category_distribution.append({
                "category": cat,
                "amount": val,
                "percentage": pct
            })

        # 5. Financial Health Score (0 - 100)
        health_score = 50
        if savings_rate >= 30:
            health_score += 25
        elif savings_rate >= 10:
            health_score += 15

        if total_debt == 0:
            health_score += 25
        elif total_debt < total_liquidity:
            health_score += 15

        health_verdict = (
            "EXCELLENT" if health_score >= 80
            else ("HEALTHY" if health_score >= 60 else "NEEDS ATTENTION")
        )

        return {
            "period": {"start_date": start_date, "end_date": end_date},
            "summary": {
                "total_inflow": round(total_inflow, 2),
                "total_outflow": round(total_outflow, 2),
                "net_savings": net_savings,
                "savings_rate_pct": savings_rate,
                "total_liquidity": round(total_liquidity, 2),
                "total_debt": round(total_debt, 2),
                "total_receivable": round(total_receivable, 2),
                "net_worth_delta": round(total_liquidity + total_receivable - total_debt, 2),
                "health_score": min(100, health_score),
                "health_verdict": health_verdict
            },
            "category_distribution": category_distribution,
            "transaction_count": len(transactions),
            "transactions": transactions
        }