from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from typing import List, Dict, Any, Tuple


class LoanService:
    @staticmethod
    def calculate_reducing_emi(principal: float, annual_rate: float, tenure_months: int) -> float:
        p = Decimal(str(principal))
        r = Decimal(str(annual_rate))
        t = Decimal(str(tenure_months))

        if r <= Decimal('0'):
            fallback = p / max(Decimal('1'), t)
            return float(fallback.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

        monthly_rate = (r / Decimal('100.0')) / Decimal('12.0')
        factor = (Decimal('1.0') + monthly_rate) ** t
        emi = p * monthly_rate * factor / (factor - Decimal('1.0'))
        return float(emi.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

    @staticmethod
    def calculate_default_first_emi_date(disbursement_date: date) -> date:
        target_date = disbursement_date + timedelta(days=30)
        candidate_same_month = date(target_date.year, target_date.month, 5)
        next_m = target_date + relativedelta(months=1)
        candidate_next_month = date(next_m.year, next_m.month, 5)

        diff_same = abs((candidate_same_month - target_date).days)
        diff_next = abs((candidate_next_month - target_date).days)

        if candidate_same_month <= disbursement_date:
            return candidate_next_month
        return candidate_same_month if diff_same <= diff_next else candidate_next_month

    @staticmethod
    def generate_amortization_schedule(
            principal: float,
            annual_rate: float,
            tenure_months: int,
            first_emi_date: date,
            monthly_emi: float
    ) -> List[Dict[str, Any]]:
        p = Decimal(str(principal))
        r = Decimal(str(annual_rate))
        emi = Decimal(str(monthly_emi))

        monthly_rate = (r / Decimal('100.0')) / Decimal('12.0') if r > Decimal('0') else Decimal('0')
        remaining = p
        schedule = []

        for i in range(1, tenure_months + 1):
            due_date = first_emi_date + relativedelta(months=i - 1)

            if r > Decimal('0'):
                interest_comp = (remaining * monthly_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                principal_comp = (emi - interest_comp).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            else:
                interest_comp = Decimal('0.00')
                principal_comp = emi.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            if i == tenure_months or principal_comp > remaining:
                principal_comp = remaining.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                remaining_after = Decimal('0.00')
            else:
                remaining_after = (remaining - principal_comp).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            remaining = max(Decimal('0.00'), remaining_after)

            schedule.append({
                "installment_number": i,
                "due_date": str(due_date),
                "emi_amount": float(principal_comp + interest_comp),
                "principal_component": float(principal_comp),
                "interest_component": float(interest_comp),
                "remaining_principal_after": float(remaining_after),
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
        today = date.today()
        pending_principal = Decimal(str(original_principal))
        principal_paid = Decimal('0.00')
        interest_paid = Decimal('0.00')
        settled_count = 0
        next_emi_date = first_emi_date

        for inst in schedule:
            due_d = date.fromisoformat(inst['due_date'])
            if settle_past_emis and due_d <= today:
                inst['status'] = 'PAID'
                inst['paid_at'] = str(today)

                principal_paid += Decimal(str(inst['principal_component']))
                interest_paid += Decimal(str(inst['interest_component']))
                pending_principal = Decimal(str(inst['remaining_principal_after']))
                settled_count += 1
            elif due_d > today and next_emi_date <= today:
                next_emi_date = due_d

        pending_tenure = max(0, total_tenure - settled_count)
        loan_status = "CLOSED" if pending_principal <= Decimal('0.00') or pending_tenure == 0 else "ACTIVE"

        return (
            schedule,
            float(pending_principal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            float(principal_paid.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            float(interest_paid.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            pending_tenure,
            next_emi_date,
            loan_status
        )