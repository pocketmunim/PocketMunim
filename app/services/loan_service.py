from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from dateutil.relativedelta import relativedelta
from app.utils.constants import TZ_IST


class LoanService:
    def __init__(self, db_client, user_id: str):
        self.db = db_client
        self.user_id = user_id

    @staticmethod
    def calculate_emi(principal: Decimal, annual_rate: Decimal, tenure_months: int) -> Decimal:
        if annual_rate <= 0:
            return principal / Decimal(tenure_months)
        monthly_rate = annual_rate / Decimal('12') / Decimal('100')
        emi = principal * monthly_rate * ((1 + monthly_rate) ** tenure_months) / (
                    ((1 + monthly_rate) ** tenure_months) - 1)
        return emi.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    async def create_loan(self, loan_data) -> dict:
        principal = Decimal(str(loan_data.principal))
        rate = Decimal(str(loan_data.annual_interest_rate))
        tenure_years = loan_data.tenure_years
        tenure_months = tenure_years * 12

        emi = loan_data.emi_amount
        if not emi or emi <= 0:
            emi = self.calculate_emi(principal, rate, tenure_months)

        loan_payload = {
            "user_id": self.user_id,
            "lender": loan_data.lender_name.title(),
            "principal_amount": float(principal),
            "annual_interest_rate": float(rate),
            "tenure_months": tenure_months,
            "start_date": str(loan_data.disbursement_date),
            "is_active": True
        }
        res = self.db.table("loans").insert(loan_payload).execute()
        if not res.data:
            raise Exception("Failed to create loan record.")

        loan_id = res.data[0]['loan_id']

        start_date = datetime.strptime(str(loan_data.first_emi_date), "%Y-%m-%d").date()
        balance = principal
        monthly_rate = rate / Decimal('12') / Decimal('100')

        schedules = []
        curr_date = start_date
        for i in range(1, tenure_months + 1):
            interest = (balance * monthly_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            principal_comp = (emi - interest).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if principal_comp > balance:
                principal_comp = balance
                emi = principal_comp + interest
            balance -= principal_comp

            schedules.append({
                "loan_id": loan_id,
                "installment_number": i,
                "due_date": curr_date.isoformat(),
                "emi_amount": float(emi),
                "principal_component": float(principal_comp),
                "interest_component": float(interest),
                "remaining_balance": float(max(balance, Decimal('0'))),
                "status": "PENDING"
            })
            curr_date += relativedelta(months=1)

        self.db.table("emi_schedules").insert(schedules).execute()
        return {"loan_id": loan_id, "emi": float(emi), "tenure_months": tenure_months}

    async def process_emi_payment(self, lender_name: str, payment_amount: Decimal = None,
                                  target_period: str = None) -> str:
        loans_res = self.db.table("loans").select("*").eq("user_id", self.user_id).ilike("lender",
                                                                                         lender_name.strip()).eq(
            "is_active", True).execute()
        if not loans_res.data:
            return f"❌ Lender '{lender_name}' not available or has no active loans."

        loan = loans_res.data[0]
        loan_id = loan['loan_id']

        sched_res = self.db.table("emi_schedules").select("*").eq("loan_id", loan_id).eq("status", "PENDING").order(
            "installment_number").execute()
        pending_schedules = sched_res.data or []
        if not pending_schedules:
            return f"ℹ️ No pending EMIs found for loan from {loan['lender']}."

        target_sched = pending_schedules[0]
        current_dt = datetime.now(TZ_IST)

        if target_period and "last month" in target_period.lower():
            last_month_dt = current_dt - relativedelta(months=1)
            for sched in pending_schedules:
                due_dt = datetime.strptime(sched['due_date'], "%Y-%m-%d")
                if due_dt.year == last_month_dt.year and due_dt.month == last_month_dt.month:
                    target_sched = sched
                    break

        amt_to_pay = payment_amount if (payment_amount and payment_amount > 0) else Decimal(
            str(target_sched['emi_amount']))

        acc_res = self.db.table("accounts").select("*").eq("user_id", self.user_id).eq("is_default", True).execute()
        if not acc_res.data:
            return "⚠️ No default account found for payment deduction."

        default_acc = acc_res.data[0]
        current_balance = Decimal(str(default_acc['balance']))

        if current_balance < amt_to_pay:
            return f"🚫 Insufficient balance in **{default_acc['account_name']}** to pay EMI of ₹{amt_to_pay:,.2f}."

        new_balance = current_balance - amt_to_pay

        self.db.table("accounts").update({"balance": float(new_balance)}).eq("id", default_acc['id']).execute()

        self.db.table("account_logs").insert({
            "account_id": default_acc['id'],
            "user_id": self.user_id,
            "log_type": "DEBIT",
            "amount": float(amt_to_pay),
            "balance_after": float(new_balance),
            "description": f"Loan EMI Payment to {loan['lender']} (Inst #{target_sched['installment_number']})"
        }).execute()

        self.db.table("transactions").insert({
            "user_id": self.user_id,
            "amount": float(amt_to_pay),
            "txn_type": "loan_payment",
            "intent": "loan_payment",
            "category": "Loans",
            "subcategory": "EMI Payment",
            "description": f"EMI Payment - {loan['lender']}",
            "date": datetime.now(TZ_IST).isoformat(),
            "source_account": default_acc['account_name'],
            "soft_deleted": False
        }).execute()

        self.db.table("emi_schedules").update({"status": "PAID"}).eq("schedule_id",
                                                                     target_sched['schedule_id']).execute()

        remaining_check = self.db.table("emi_schedules").select("schedule_id", count="exact").eq("loan_id", loan_id).eq(
            "status", "PENDING").execute()
        if not remaining_check.count or remaining_check.count == 0:
            self.db.table("loans").update({"is_active": False}).eq("loan_id", loan_id).execute()
            loan_status_msg = f"\n🎉 Congratulations! Loan from **{loan['lender']}** is now fully paid off and closed!"
        else:
            loan_status_msg = ""

        return f"✅ *EMI Payment Successful*\nPaid ₹{amt_to_pay:,.2f} to *{loan['lender']}* (Installment #{target_sched['installment_number']}).\nNew Balance in {default_acc['account_name']}: ₹{new_balance:,.2f}{loan_status_msg}"