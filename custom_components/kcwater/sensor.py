"""Sensors for KC Water usage."""

from __future__ import annotations

import re
import math
from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfVolume
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN

GALLONS_PER_CUBIC_FOOT = 7.48051948


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up KC Water sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [KCWaterSensor(coordinator, entry, metric) for metric in (
            "daily_gallons", "daily_cubic_feet", "billing_gallons", "billing_cubic_feet",
            "average_gallons", "high_gallons", "last_reading",
        )]
    )


class KCWaterSensor(CoordinatorEntity, SensorEntity):
    """One normalized usage value derived from portal history or summary."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry, metric: str) -> None:
        super().__init__(coordinator)
        self.metric = metric
        self._attr_unique_id = f"{entry.entry_id}_{metric}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "KC Water",
            "manufacturer": "Kansas City Water Services",
            "configuration_url": "https://my.kcwater.us",
        }
        names = {
            "daily_gallons": ("Latest daily usage", UnitOfVolume.GALLONS),
            "daily_cubic_feet": ("Latest daily usage", UnitOfVolume.CUBIC_FEET),
            "billing_gallons": ("Portal period usage", UnitOfVolume.GALLONS),
            "billing_cubic_feet": ("Portal period usage", UnitOfVolume.CUBIC_FEET),
            "average_gallons": ("Average daily usage", UnitOfVolume.GALLONS),
            "high_gallons": ("Highest daily usage", UnitOfVolume.GALLONS),
            "last_reading": ("Last reading date", None),
        }
        self._attr_name, self._attr_native_unit_of_measurement = names[metric]
        if metric == "last_reading":
            self._attr_device_class = SensorDeviceClass.DATE
            self._attr_state_class = None

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        history = _valid_history(data.get("history", []))
        if self.metric == "last_reading":
            return max((item[0] for item in history), default=None)
        if self.metric.startswith("daily_"):
            if not history:
                return None
            gallons = max(history, key=lambda item: item[0])[1]
            return _gallons_to_metric(gallons, self.metric)
        summary = data.get("summary", {})
        keys = {
            "billing_gallons": "Total Gal Usage",
            "billing_cubic_feet": "Total Usage",
            "average_gallons": "Average Gal Usage",
            "high_gallons": "High Gal Usage",
        }
        return _number(summary.get(keys.get(self.metric, "")))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {"portal_status": data.get("status"), "history_readings": len(_valid_history(data.get("history", [])))}


def _number(value: Any) -> float | None:
    """Parse a finite non-negative numeric reading without inventing a value."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value) if isinstance(value, (int, float)) else float(
            re.sub(r"[^0-9.+-]", "", str(value).replace(",", ""))
        )
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _parse_date(row: dict[str, Any]) -> date | None:
    for value in (row.get("chargeDateRaw"), row.get("readDate")):
        if not value:
            continue
        if isinstance(value, date):
            return value
        text = str(value).strip()
        for pattern in ("%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(text[:19], pattern).date()
            except ValueError:
                continue
    return None


def _valid_history(rows: Any) -> list[tuple[date, float]]:
    """Deduplicate readings, retain zeros, and omit future placeholders."""
    if not isinstance(rows, list):
        return []
    today = dt_util.now().date()
    result: dict[date, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        reading_date = _parse_date(row)
        gallons = _number(row.get("gallonsConsumption"))
        if reading_date is None or reading_date > today or gallons is None:
            continue
        result[reading_date] = gallons
    return sorted(result.items())


def _gallons_to_metric(gallons: float, metric: str) -> float:
    return gallons if metric.endswith("gallons") else gallons / GALLONS_PER_CUBIC_FOOT
