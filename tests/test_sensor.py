"""Sanitized history parser tests."""

from datetime import date, timedelta

from custom_components.kcwater.sensor import _number, _valid_history


def test_history_keeps_zero_and_deduplicates_dates():
    rows = [
        {"chargeDateRaw": "01-OCT-2026", "gallonsConsumption": "0"},
        {"readDate": "2026-10-01", "gallonsConsumption": "3"},
        {"chargeDateRaw": "02-OCT-2026", "gallonsConsumption": "12.5"},
    ]
    assert _valid_history(rows) == [(date(2026, 10, 1), 3.0), (date(2026, 10, 2), 12.5)]


def test_future_placeholders_and_malformed_rows_are_ignored():
    future = (date.today() + timedelta(days=1)).strftime("%d-%b-%Y").upper()
    rows = [
        {"readDate": future, "gallonsConsumption": 0},
        {"readDate": "not-a-date", "gallonsConsumption": 4},
        {"readDate": "2026-10-03", "gallonsConsumption": "unknown"},
        None,
    ]
    assert _valid_history(rows) == []


def test_number_handles_zero_and_rejects_invalid_values():
    assert _number("0") == 0
    assert _number("1,234.5 gal") == 1234.5
    assert _number("n/a") is None
    assert _number(-1) is None
