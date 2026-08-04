import datetime
import math
from decimal import Decimal, ROUND_HALF_UP
from dateutil.relativedelta import relativedelta

class AmortizationEngine:
    @staticmethod
    def generate_schedule(principal: float, annual_rate: float, tenure_months: int, start_date: datetime.date) -> list:
        p = Decimal(str(principal))
        r = Decimal(str(annual_rate)) / Decimal('1200')
        n = Decimal(str(tenure_months))

        emi = p * r * ((1 + r) ** n) / (((1 + r) ** n) - 1)
        emi = emi.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Implementation of schedule building...
        return []

    @staticmethod
    def recalculate_after_prepayment(remaining_principal, annual_rate, remaining_months, current_emi, prepayment_amount, user_choice):
        # Branches into REDUCE_EMI or REDUCE_TENURE logic based on user input
        pass
