import datetime
import math
from decimal import Decimal, ROUND_HALF_UP
from dateutil.relativedelta import relativedelta

class AmortizationEngine:
    @staticmethod
    def calculate_emi(principal: Decimal, annual_rate: Decimal, tenure_months: int) -> Decimal:
        if tenure_months <= 0:
            return Decimal('0.00')
        if annual_rate <= Decimal('0.00'):
            return (principal / Decimal(tenure_months)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        monthly_rate = annual_rate / Decimal('1200')
        factor = (Decimal('1') + monthly_rate) ** tenure_months
        emi = principal * monthly_rate * factor / (factor - Decimal('1'))
        return emi.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @staticmethod
    def generate_schedule(principal: float, annual_rate: float, tenure_months: int, start_date: datetime.date) -> list:
        p = Decimal(str(principal))
        r_annual = Decimal(str(annual_rate))
        monthly_rate = r_annual / Decimal('1200') if r_annual > 0 else Decimal('0.00')

        emi = AmortizationEngine.calculate_emi(p, r_annual, tenure_months)
        schedule = []
        balance = p
        current_date = start_date

        for i in range(1, tenure_months + 1):
            interest_comp = (balance * monthly_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if monthly_rate > 0 else Decimal('0.00')
            principal_comp = (emi - interest_comp).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            if principal_comp > balance or i == tenure_months:
                principal_comp = balance
                emi = principal_comp + interest_comp

            balance -= principal_comp
            schedule.append({
                "installment_number": i,
                "due_date": current_date.isoformat(),
                "emi_amount": float(emi),
                "principal_component": float(principal_comp),
                "interest_component": float(interest_comp),
                "remaining_balance": float(max(balance, Decimal('0.00'))),
                "status": "PENDING"
            })
            current_date += relativedelta(months=1)

        return schedule
