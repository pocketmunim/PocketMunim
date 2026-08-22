import httpx
from datetime import date, timedelta
from typing import Set, Dict

class HolidayService:
    _holiday_cache: Dict[int, Set[date]] = {}

    @classmethod
    async def get_bank_holidays(cls, year: int) -> Set[date]:
        """Fetches and caches gazetted bank holidays for India for the given year."""
        if year in cls._holiday_cache:
            return cls._holiday_cache[year]

        url = f"https://date.nager.at/api/v3/PublicHolidays/{year}/IN"
        holidays_set: Set[date] = set()

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    for item in data:
                        holidays_set.add(date.fromisoformat(item["date"]))
        except Exception as e:
            print(f"[HolidayService] Warning: Failed to fetch online bank holidays: {e}")

        cls._holiday_cache[year] = holidays_set
        return holidays_set

    @classmethod
    async def get_effective_payout_date(cls, target_date: date) -> date:
        """
        Shifts target_date backwards until a valid working business day is found
        (skips Saturdays, Sundays, and Gazetted Bank Holidays).
        """
        holidays = await cls.get_bank_holidays(target_date.year)
        effective_date = target_date

        while True:
            # Check if target_date's year changed during backwards shift across Jan 1st
            if effective_date.year not in cls._holiday_cache:
                holidays = await cls.get_bank_holidays(effective_date.year)

            # Python weekday(): Monday=0, Tuesday=1, ..., Saturday=5, Sunday=6
            is_weekend = effective_date.weekday() in (5, 6)
            is_bank_holiday = effective_date in holidays

            if not is_weekend and not is_bank_holiday:
                return effective_date

            # Shift backward by 1 day
            effective_date -= timedelta(days=1)