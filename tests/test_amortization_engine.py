import datetime
from decimal import Decimal
from app.services.amortization_engine import AmortizationEngine


def test_calculate_emi_standard():
    """Test standard EMI calculation for 5 Lakhs at 9.5% for 3 years (36 months)."""
    principal = Decimal('500000')
    rate = Decimal('9.5')
    tenure_months = 36

    # Mathematical expected EMI is strictly 16016.47
    emi = AmortizationEngine.calculate_emi(principal, rate, tenure_months)
    assert emi == Decimal('16016.47')


def test_calculate_emi_zero_interest():
    """Test edge case where interest rate is 0%."""
    principal = Decimal('120000')
    rate = Decimal('0.0')
    tenure_months = 12

    # Expected EMI is strictly Principal / Months
    emi = AmortizationEngine.calculate_emi(principal, rate, tenure_months)
    assert emi == Decimal('10000.00')


def test_generate_schedule():
    """Test that the schedule generates the correct number of installments and zero remaining balance."""
    start_date = datetime.date(2026, 1, 1)
    schedule = AmortizationEngine.generate_schedule(
        principal=100000.0,
        annual_rate=10.0,
        tenure_months=12,
        start_date=start_date
    )

    assert len(schedule) == 12
    assert schedule[0]["installment_number"] == 1
    assert schedule[0]["status"] == "PENDING"

    # Final remaining balance must be exactly 0.00
    assert schedule[-1]["remaining_balance"] == 0.0