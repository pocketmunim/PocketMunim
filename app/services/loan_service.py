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

    async def create_loan(self, loan_data) -> tuple[str, bool]:
        if not loan_data.principal or not loan_data.lender_name:
            return f"⚠️ *Skipped Loan Creation*: Could not determine details.", False

        principal = Decimal(str(loan_data.principal))
        rate = Decimal(str(loan_data.annual_interest_rate or 0.0))
        tenure_months = (loan_data.tenure_years or 1) * 12
        emi = loan_data.emi_amount or self.calculate_emi(principal, rate, tenure_months)

        # Duplicate Check
        exist = self.db.table("loans").select("*").eq("user_id", self.user_id).ilike("lender",
                                                                                     loan_data.lender_name.strip()).execute()
        if exist.data:
            return f"⚠️ *Duplicate Loan*: Loan from *{loan_data.lender_name}* already exists.", False

        # Register Loan
        res = self.db.table("loans").insert({
            "user_id": self.user_id, "lender": loan_data.lender_name.title(),
            "principal_amount": float(principal), "annual_interest_rate": float(rate),
            "tenure_months": tenure_months, "start_date": str(datetime.now(TZ_IST).date()), "is_active": True
        }).execute()

        loan_id = res.data[0]['loan_id']
        # Create Schedules
        schedules = []
        curr_date = datetime.now(TZ_IST).date()
        for i in range(1, tenure_months + 1):
            schedules.append({
                "loan_id": loan_id, "installment_number": i, "due_date": curr_date.isoformat(),
                "emi_amount": float(emi), "status": "PENDING"
            })
            curr_date += relativedelta(months=1)
        self.db.table("emi_schedules").insert(schedules).execute()

        # Credit Account
        acc = self.db.table("accounts").select("*").eq("user_id", self.user_id).eq("is_default", True).execute()
        if acc.data:
            new_bal = Decimal(str(acc.data[0]['balance'])) + principal
            self.db.table("accounts").update({"balance": float(new_bal)}).eq("id", acc.data[0]['id']).execute()
            self.db.table("transactions").insert({
                "user_id": self.user_id, "amount": float(principal), "txn_type": "borrow",
                "description": f"Loan Disbursement - {loan_data.lender_name}", "date": datetime.now(TZ_IST).isoformat()
            }).execute()

        return f"✅ *Loan Registered*: {loan_data.lender_name.title()} (+₹{float(principal):,.2f})", True

    async def process_emi_payment_by_id(self, loan_id: str, force_schedule_id: str = None) -> tuple[str, any]:
        loan = self.db.table("loans").select("*").eq("loan_id", loan_id).execute().data[0]
        scheds = self.db.table("emi_schedules").select("*").eq("loan_id", loan_id).order(
            "installment_number").execute().data

        target = None
        if force_schedule_id:
            target = next((s for s in scheds if s['schedule_id'] == force_schedule_id), None)
        else:
            target = next((s for s in scheds if s['status'] == 'PENDING'), None)

        if not target:
            return f"ℹ️ All EMIs paid for *{loan['lender']}*.", False

        if target['status'] == 'PAID' and not force_schedule_id:
            next_sched = next((s for s in scheds if s['status'] == 'PENDING'), None)
            if next_sched:
                return (
                    f"⚠️ *EMI Already Paid*\nEMI for {target['due_date']} is paid. Pay next (#{next_sched['installment_number']})?",
                    {"status": "NEXT_EMI_CONFIRM", "next_schedule_id": next_sched['schedule_id'], "loan_id": loan_id})
            return "ℹ️ No pending EMIs.", False

        # Pay Logic
        amt = Decimal(str(target['emi_amount']))
        acc = self.db.table("accounts").select("*").eq("user_id", self.user_id).eq("is_default", True).execute().data[0]

        self.db.table("accounts").update({"balance": float(Decimal(str(acc['balance'])) - amt)}).eq("id",
                                                                                                    acc['id']).execute()
        self.db.table("transactions").insert({"user_id": self.user_id, "amount": float(amt), "txn_type": "loan_payment",
                                              "description": f"EMI to {loan['lender']}",
                                              "date": datetime.now(TZ_IST).isoformat()}).execute()
        self.db.table("emi_schedules").update({"status": "PAID"}).eq("schedule_id", target['schedule_id']).execute()

        return f"✅ *Payment Successful*: ₹{float(amt):,.2f} to *{loan['lender']}*", True