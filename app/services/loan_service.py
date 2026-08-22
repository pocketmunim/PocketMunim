import math
from datetime import date
from dateutil.relativedelta import relativedelta
from typing import List, Dict, Any, Tuple


class LoanService:
    @staticmethod
    def calculate_reducing_emi(principal: float, annual_rate: float, tenure_months: int) -> float:
        """
        Calculates reducing-balance EMI.
        Formula: EMI = P * r * (1+r)^n / ((1+r)^n - 1)
        """
        if annual_rate <= 0:
            return round(principal / max(1, tenure_months), 2)

        monthly_rate = (annual_rate / 100.0) / 12.0
        factor = math.pow(1.0 + monthly_rate, tenure_months)
        emi = principal * monthly_rate * factor / (factor - 1.0)
        return round(emi, 2)

    @staticmethod
    def generate_amortization_schedule(
            principal: float,
            annual_rate: float,
            tenure_months: int,
            first_emi_date: date,
            monthly_emi: float
    ) -> List[Dict[str, Any]]:
        """
        Generates month-by-month amortization schedule with principal/interest breakdown.
        """
        monthly_rate = (annual_rate / 100.0) / 12.0 if annual_rate > 0 else 0.0
        remaining = principal
        schedule = []

        for i in range(1, tenure_months + 1):
            due_date = first_emi_date + relativedelta(months=i - 1)

            if annual_rate > 0:
                interest_comp = round(remaining * monthly_rate, 2)
                principal_comp = round(monthly_emi - interest_comp, 2)
            else:
                interest_comp = 0.0
                principal_comp = round(monthly_emi, 2)

            # Cap last installment rounding delta
            if i == tenure_months or principal_comp > remaining:
                principal_comp = round(remaining, 2)
                remaining_after = 0.0
            else:
                remaining_after = round(remaining - principal_comp, 2)

            remaining = max(0.0, remaining_after)

            schedule.append({
                "installment_number": i,
                "due_date": str(due_date),
                "emi_amount": round(principal_comp + interest_comp, 2),
                "principal_component": principal_comp,
                "interest_component": interest_comp,
                "remaining_principal_after": remaining_after,
                "status": "SCHEDULED",
                "paid_at": None
            })
        return schedule

    @classmethod
    def process_inception_settlement(
            cls,
            schedule: List[Dict[str, Any]],
            settle_past_emis: bool,
            first_emi_date: date,
            original_principal: float,
            total_tenure: int
    ) -> Tuple[List[Dict[str, Any]], float, float, float, int, date, str]:
        """
        Settles historical EMIs up to the current date and returns recalculated loan metrics.
        """
        today = date.today()
        pending_principal = original_principal
        principal_paid = 0.0
        interest_paid = 0.0
        settled_count = 0
        next_emi_date = first_emi_date

        for inst in schedule:
            due_d = date.fromisoformat(inst['due_date'])
            if settle_past_emis and due_d <= today:
                inst['status'] = 'PAID'
                inst['paid_at'] = str(today)
                principal_paid += inst['principal_component']
                interest_paid += inst['interest_component']
                pending_principal = inst['remaining_principal_after']
                settled_count += 1
            elif due_d > today and next_emi_date <= today:
                next_emi_date = due_d

        pending_tenure = max(0, total_tenure - settled_count)
        loan_status = "CLOSED" if pending_principal <= 0 else "ACTIVE"

        return (
            schedule,
            round(pending_principal, 2),
            round(principal_paid, 2),
            round(interest_paid, 2),
            pending_tenure,
            next_emi_date,
            loan_status
        )