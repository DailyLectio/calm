"""Roman lectionary cycle labels, calculated for every year (not a readings selector).

USCCB: https://www.usccb.org/faq/questions-about-lectionary
2026 boundary fixtures: https://www.usccb.org/resources/2026cal.pdf (printed p. 5).
Seasonal/feast readings still come from the date-specific approved calendar.
"""
from datetime import date, timedelta


def first_sunday_of_advent(year: int) -> date:
    earliest = date(year, 11, 27)
    return earliest + timedelta(days=(6 - earliest.weekday()) % 7)


def liturgical_year(day: date) -> int:
    return day.year + (day >= first_sunday_of_advent(day.year))


def sunday_cycle(day: date) -> str:
    # The liturgical year ending in 2020 is Year A; repeat A, B, C.
    return ("Year A", "Year B", "Year C")[(liturgical_year(day) - 2020) % 3]


def weekday_cycle(day: date) -> str:
    # Annual context label. I/II selects Ordinary Time readings, not seasonal propers.
    return "Cycle I" if liturgical_year(day) % 2 else "Cycle II"
