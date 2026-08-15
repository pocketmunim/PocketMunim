from decimal import Decimal
from datetime import datetime
from app.utils.constants import TZ_IST
from app.services.amortization_engine import AmortizationEngine

class LoanService:
    def __init__(self, db_client, user_id: str):
        self.db = db_client
        self.user_id = user_id

    async def create_loan(self, loan_data) -> tuple[str, bool]:
        if not loan_data.principal or not loan_data.lender_name:
            item_desc = loan_data.lender_name or "Unknown Loan"
            return f"  *Skipped Loan Creation*: Missing principal or lender for '{item_desc}'.", False

        principal = Decimal(str(loan_data.principal))
        rate = Decimal(str(loan_data.annual_interest_rate or 0.0))
        tenure_years = loan_data.tenure_years or 1
        tenure_months = tenure_years * 12

        existing_loan = self.db.table("loans").select("*").eq("user_id", self.user_id).ilike("lender", loan_data.lender_name.strip()).eq("principal_amount", float(principal)).eq("is_active", True).execute()
        if existing_loan.data:
            return f"  *Duplicate Loan Detected*\nAn active loan from *{loan_data.lender_name.title()}* for  {float(principal):,.2f} already exists.", False

        emi = loan_data.emi_amount
        if not emi or emi <= 0:
            emi = AmortizationEngine.calculate_emi(principal, rate, tenure_months)

        # Base dates
        disbursement_str = loan_data.disbursement_date or datetime.now(TZ_IST).date().isoformat()
        disbursement_dt = datetime.strptime(str(disbursement_str), "%Y-%m-%d").date()
        # Calculate accurate ledger timestamp
        txn_date_iso = datetime.combine(disbursement_dt, datetime.now(TZ_IST).time()).replace(tzinfo=TZ_IST).isoformat()

        loan_payload = {
            "user_id": self.user_id,
            "lender": loan_data.lender_name.title(),
            "principal_amount": float(principal),
            "annual_interest_rate": float(rate),
            "tenure_months": tenure_months,
            "start_date": str(disbursement_str),
            "is_active": True
        }
        res = self.db.table("loans").insert(loan_payload).execute()
        if not res.data:
            return f"  *Failed* to save loan for {loan_data.lender_name}.", False

        loan_id = res.data[0]['loan_id']
        start_date_str = loan_data.first_emi_date or disbursement_str
        start_date = datetime.strptime(str(start_date_str), "%Y-%m-%d").date()
        schedules_raw = AmortizationEngine.generate_schedule(float(principal), float(rate), tenure_months, start_date)
        schedules_payload = [{**s, "loan_id": loan_id} for s in schedules_raw]
        self.db.table("emi_schedules").insert(schedules_payload).execute()

        acc_res = self.db.table("accounts").select("*").eq("user_id", self.user_id).eq("is_default", True).execute()
        default_acc_name = "Account"
        if acc_res.data:
            default_acc = acc_res.data[0]
            default_acc_name = default_acc['account_name']
            current_balance = Decimal(str(default_acc['balance']))
            new_balance = current_balance + principal
            self.db.table("accounts").update({"balance": float(new_balance)}).eq("id", default_acc['id']).execute()
            self.db.table("account_logs").insert({
                "account_id": default_acc['id'],
                "user_id": self.user_id,
                "log_type": "CREDIT",
                "amount": float(principal),
                "balance_after": float(new_balance),
                "description": f"Loan Disbursement - {loan_data.lender_name.title()}"
            }).execute()

            self.db.table("transactions").insert({
                "user_id": self.user_id,
                "amount": float(principal),
                "txn_type": "borrow",
                "intent": "borrow",
                "category": "Loans",
                "subcategory": "Loan Disbursement",
                "description": f"Loan from {loan_data.lender_name.title()}",
                "date": txn_date_iso,  # <--- Historical Date Applied Here
                "destination_account": default_acc_name,
                "soft_deleted": False
            }).execute()

        return (
            f"  *Loan Registered Successfully*\n"
            f"Lender: *{loan_data.lender_name.title()}*\n"
            f"Principal:  {float(principal):,.2f} (Credited to {default_acc_name})\n"
            f"Calculated EMI:  {float(emi):,.2f}\n"
            f"Tenure: {tenure_years} Years ({tenure_months} months)"
        ), True

    async def process_emi_payment_by_id(self, loan_id: str, payment_amount: Decimal = None, target_period: str = None,
                                        force_schedule_id: str = None, payment_date_str: str = None, skip_month_check: bool = False) -> tuple[str, any]:
        loan_res = self.db.table("loans").select("*").eq("loan_id", loan_id).eq("is_active", True).execute()
        if not loan_res.data:
            return "  *Loan Not Found*: This loan account is invalid or closed.", False

        loan = loan_res.data[0]
        sched_res = self.db.table("emi_schedules").select("*").eq("loan_id", loan_id).order(
            "installment_number").execute()
        all_schedules = sched_res.data or []

        # --- DUPLICATE MONTH INTERCEPTOR ---
        curr_year_month = datetime.now(TZ_IST).strftime("%Y-%m")
        current_month_paid = any(sched['due_date'].startswith(curr_year_month) and sched['status'] == 'PAID' for sched in all_schedules)

        if current_month_paid and not skip_month_check and not force_schedule_id:
            return (
                f"  *Duplicate EMI Warning*\n"
                f"An EMI for *{loan['lender']}* has already been recorded for this month.\n\n"
                f"Do you want to advance and pay the next subsequent month's installment?"
            ), {"requires_confirmation": True, "loan_id": loan_id}

        pending_schedules = [s for s in all_schedules if s['status'] == 'PENDING']
        target_sched = None
        if force_schedule_id:
            for sched in all_schedules:
                if sched['schedule_id'] == force_schedule_id:
                    target_sched = sched
                    break
        else:
            if pending_schedules:
                target_sched = pending_schedules[0]

        if not target_sched:
            return f"  All EMIs for *{loan['lender']}* are already fully paid!", False

        amt_to_pay = payment_amount if (payment_amount and payment_amount > 0) else Decimal(
            str(target_sched['emi_amount']))

        acc_res = self.db.table("accounts").select("*").eq("user_id", self.user_id).eq("is_default", True).execute()
        if not acc_res.data:
            return "  *Transaction Failed*: No default bank account configured.", False

        default_acc = acc_res.data[0]
        current_balance = Decimal(str(default_acc['balance']))

        if current_balance < amt_to_pay:
            return f"  *Transaction Failed*\nInsufficient balance in *{default_acc['account_name']}* to complete payment of  {amt_to_pay:,.2f}.", False

        new_balance = current_balance - amt_to_pay
        self.db.table("accounts").update({"balance": float(new_balance)}).eq("id", default_acc['id']).execute()

        # Calculate accurate ledger timestamp for EMI
        payment_dt = datetime.strptime(payment_date_str, "%Y-%m-%d").date() if payment_date_str else datetime.now(
            TZ_IST).date()
        txn_date_iso = datetime.combine(payment_dt, datetime.now(TZ_IST).time()).replace(tzinfo=TZ_IST).isoformat()

        self.db.table("account_logs").insert({
            "account_id": default_acc['id'],
            "user_id": self.user_id,
            "log_type": "DEBIT",
            "amount": float(amt_to_pay),
            "balance_after": float(new_balance),
            "description": f"Loan EMI Payment to {loan['lender']} (Installment #{target_sched['installment_number']})"
        }).execute()

        self.db.table("transactions").insert({
            "user_id": self.user_id,
            "amount": float(amt_to_pay),
            "txn_type": "loan_payment",
            "intent": "loan_payment",
            "category": "Loans",
            "subcategory": "EMI Payment",
            "description": f"EMI Payment - {loan['lender']}",
            "date": txn_date_iso,  # <--- Historical Date Applied Here
            "source_account": default_acc['account_name'],
            "soft_deleted": False
        }).execute()

        self.db.table("emi_schedules").update({"status": "PAID"}).eq("schedule_id",
                                                                     target_sched['schedule_id']).execute()

        remaining_check = self.db.table("emi_schedules").select("schedule_id", count="exact").eq("loan_id", loan_id).eq(
            "status", "PENDING").execute()

        if not remaining_check.count or remaining_check.count == 0:
            self.db.table("loans").update({"is_active": False}).eq("loan_id", loan_id).execute()
            return f"  *Loan Fully Paid Off!*\nPaid  {amt_to_pay:,.2f} to *{loan['lender']}*. Loan closed!", True

        return f"  *EMI Payment Successful*\nPaid  {amt_to_pay:,.2f} to *{loan['lender']}* (Installment #{target_sched['installment_number']}).\nNew Balance in {default_acc['account_name']}:  {new_balance:,.2f}", True