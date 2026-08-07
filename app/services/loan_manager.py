import math
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date
from dateutil.relativedelta import relativedelta


class LoanManager:
    """
    Isolated Loan Management Service.
    Does not depend on any NLP or Telegram handlers.
    """

    @staticmethod
    def calculate_emi(principal: Decimal, annual_rate: Decimal, tenure_months: int) -> Decimal:
        """Calculates standard fixed monthly EMI."""
        if annual_rate <= 0:
            return principal / Decimal(tenure_months)

        monthly_rate = annual_rate / Decimal('12') / Decimal('100')
        emi = principal * monthly_rate * ((1 + monthly_rate) ** tenure_months) / (
                    ((1 + monthly_rate) ** tenure_months) - 1)
        return emi.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @staticmethod
    def generate_schedule(principal: Decimal, emi: Decimal, annual_rate: Decimal, start_date: date) -> list:
        """Generates a detailed amortization schedule for a loan."""
        schedule = []
        balance = principal
        monthly_rate = annual_rate / Decimal('12') / Decimal('100')

        current_date = start_date
        installment = 1

        while balance > 0:
            interest = (balance * monthly_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            principal_comp = (emi - interest).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            # Handle final payment adjustment
            if principal_comp > balance:
                principal_comp = balance
                emi = principal_comp + interest

            balance -= principal_comp

            schedule.append({
                "installment": installment,
                "due_date": current_date.isoformat(),
                "emi": float(emi),
                "principal": float(principal_comp),
                "interest": float(interest),
                "balance": float(max(balance, Decimal('0'))),
                "status": "PENDING"
            })

            current_date += relativedelta(months=1)
            installment += 1
            if installment > 600: break  # Safety break

        return schedule

    @staticmethod
    def validate_payment(loan_details: dict, payment_amount: Decimal, payment_date: date) -> bool:
        """Logic to verify if a payment is expected and valid."""
        # Check if John is lender (as per requirement)
        if loan_details.get("lender_name", "").lower() != "john":
            return False

        # Logic to check if this EMI is pending for the requested month
        # This will query the database schedule generated above
        return True