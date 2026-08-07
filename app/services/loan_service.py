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
            item_desc = loan_data.lender_name or "Unknown Loan"
            return f"⚠️ **Skipped Loan Creation**: Could not determine principal or lender for '{item_desc}'. Please provide complete details.", False

        principal = Decimal(str(loan_data.principal))
        rate = Decimal(str(loan_data.annual_interest_rate or 0.0))
        tenure_years = loan_data.tenure_years or 1
        tenure_months = tenure_years * 12

        # DUPLICATE LOAN CHECK
        existing_loan = self.db.table("loans").select("*").eq("user_id", self.user_id).ilike("lender",
                                                                                             loan_data.lender_name.strip()).eq(
            "principal_amount", float(principal)).eq("is_active", True).execute()
        if existing_loan.data:
            return f"⚠️ **Duplicate Loan Detected**\nAn active loan from **{loan_data.lender_name.title()}** with principal ₹{float(principal):,.2f} already exists. To add it as a separate account, please confirm or use a distinguishing note.", False

        emi = loan_data.emi_amount
        if not emi or emi <= 0:
            emi = self.calculate_emi(principal, rate, tenure_months)

        disbursement_str = loan_data.disbursement_date or datetime.now(TZ_IST).date().isoformat()

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
            return f"⚠️ **Failed** to save loan for {loan_data.lender_name}.", False

        loan_id = res.data[0]['loan_id']

        start_date_str = loan_data.first_emi_date or disbursement_str
        start_date = datetime.strptime(str(start_date_str), "%Y-%m-%d").date()
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

        success_msg = (
            f"✅ **Loan Registered Successfully**\n"
            f"Lender: {loan_data.lender_name.title()}\n"
            f"Principal: ₹{float(principal):,.2f}\n"
            f"Calculated EMI: ₹{float(emi):,.2f}\n"
            f"Tenure: {tenure_years} Years ({tenure_months} months)"
        )
        return success_msg, True

    async def process_emi_payment(self, lender_name: str, payment_amount: Decimal = None, target_period: str = None) -> \
    tuple[str, bool]:
        if not lender_name or lender_name.lower() in ["friend", "unknown", "someone"]:
            return f"⚠️ **Skipped EMI Payment**: Lender name is missing or ambiguous ('{lender_name}'). Please specify a valid registered lender name.", False

        loans_res = self.db.table("loans").select("*").eq("user_id", self.user_id).ilike("lender",
                                                                                         lender_name.strip()).eq(
            "is_active", True).execute()
        matching_loans = loans_res.data or []

        if not matching_loans:
            return f"❌ **Lender Not Found**: '{lender_name.title()}' has no active loans. Use `/getloans` to check active records.", False

        # MULTIPLE ACCOUNTS DISAMBIGUATION
        if len(matching_loans) > 1:
            loan_list_str = "\n".join([
                                          f"- Account ID: `{l['loan_id'][:8]}...` | Principal: ₹{float(l['principal_amount']):,.2f} | Rate: {float(l['annual_interest_rate'])}%"
                                          for l in matching_loans])
            return f"⚠️ **Multiple Loans Found for {lender_name.title()}**\nYou have {len(matching_loans)} active loan accounts with this lender:\n{loan_list_str}\nPlease use the interactive `/getloans` dashboard buttons to pay the specific account directly.", False

        loan = matching_loans[0]
        return await self.process_emi_payment_by_id(loan['loan_id'], payment_amount, target_period)

    async def process_emi_payment_by_id(self, loan_id: str, payment_amount: Decimal = None,
                                        target_period: str = None) -> tuple[str, bool]:
        loan_res = self.db.table("loans").select("*").eq("loan_id", loan_id).eq("is_active", True).execute()
        if not loan_res.data:
            return "❌ **Loan Not Found**: This loan account is invalid or already closed.", False

        loan = loan_res.data[0]

        sched_res = self.db.table("emi_schedules").select("*").eq("loan_id", loan_id).eq("status", "PENDING").order(
            "installment_number").execute()
        pending_schedules = sched_res.data or []
        if not pending_schedules:
            return f"ℹ️ No pending EMIs found for loan from {loan['lender']}.", False

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
            return "⚠️ **Transaction Failed**: No default bank account found for payment deduction.", False

        default_acc = acc_res.data[0]
        current_balance = Decimal(str(default_acc['balance']))

        if current_balance < amt_to_pay:
            return f"🚫 **Transaction Failed**\nYou do not have sufficient balance in **{default_acc['account_name']}** to complete EMI payment of ₹{amt_to_pay:,.2f} to {loan['lender']}.", False

        new_balance = current_balance - amt_to_pay

        # Update account balance
        self.db.table("accounts").update({"balance": float(new_balance)}).eq("id", default_acc['id']).execute()

        # Insert account log
        self.db.table("account_logs").insert({
            "account_id": default_acc['id'],
            "user_id": self.user_id,
            "log_type": "DEBIT",
            "amount": float(amt_to_pay),
            "balance_after": float(new_balance),
            "description": f"Loan EMI Payment to {loan['lender']} (Installment #{target_sched['installment_number']})"
        }).execute()

        # Insert transaction record
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

        # Mark EMI schedule as PAID
        self.db.table("emi_schedules").update({"status": "PAID"}).eq("schedule_id",
                                                                     target_sched['schedule_id']).execute()

        # Check if loan is fully paid off
        remaining_check = self.db.table("emi_schedules").select("schedule_id", count="exact").eq("loan_id", loan_id).eq(
            "status", "PENDING").execute()

        success_header = "✅ **EMI Payment Successful**"
        payment_line = f"Paid ₹{amt_to_pay:,.2f} to **{loan['lender']}** (Installment #{target_sched['installment_number']})."
        balance_line = f"New Balance in {default_acc['account_name']}: ₹{new_balance:,.2f}"

        if not remaining_check.count or remaining_check.count == 0:
            self.db.table("loans").update({"is_active": False}).eq("loan_id", loan_id).execute()
            return f"{success_header}\n{payment_line}\n{balance_line}\n🎉 **Congratulations!** Loan from **{loan['lender']}** is now fully paid off and closed!", True

        return f"{success_header}\n{payment_line}\n{balance_line}", True