"""KC Water API client and polling coordinator."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import VolumeConverter

try:
    from homeassistant.components.recorder.models import StatisticMeanType
except ImportError:  # Home Assistant versions before mean_type was introduced.
    StatisticMeanType = None

from .const import (
    API_BASE,
    CONF_ACCOUNT_NUMBER,
    CONF_CUSTOMER_ID,
    CONF_SERVICE_ID,
    CUSTOMER_PATH,
    DOMAIN,
    OAUTH_CLIENT_ID,
    OAUTH_CLIENT_SECRET,
    TOKEN_PATH,
    UPDATE_INTERVAL,
    USAGE_PATH,
)

_LOGGER = logging.getLogger(__name__)
TIMEOUT = aiohttp.ClientTimeout(total=30)


class KCWaterApiError(Exception):
    """A sanitized API failure."""


class KCWaterAuthError(KCWaterApiError):
    """Authentication was rejected."""


class KCWaterClient:
    """Async client for the read-only KC Water portal API."""

    def __init__(self, session: aiohttp.ClientSession, username: str, password: str) -> None:
        self.session = session
        self.username = username
        self.password = password
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.expires_at: datetime | None = None

    async def async_authenticate(self) -> dict[str, Any]:
        """Authenticate and return the user object for account selection."""
        payload = await self._token_request(
            {"grant_type": "password", "username": self.username, "password": self.password}
        )
        self._store_tokens(payload)
        user = payload.get("user")
        if not isinstance(user, dict) or not payload.get("access_token"):
            raise KCWaterApiError("Authentication response was missing required data")
        return user

    async def async_get_customer(self, customer_id: str) -> dict[str, Any]:
        """Fetch the signed-in customer's accounts and services."""
        if not self.access_token:
            raise KCWaterApiError("KC Water customer lookup requires authentication")
        try:
            async with self.session.post(
                f"{API_BASE}{CUSTOMER_PATH}",
                json={"customerId": customer_id, "accountContext": None},
                headers={"Authorization": f"Bearer {self.access_token}", "Accept": "application/json"},
                timeout=TIMEOUT,
            ) as response:
                if response.status in (401, 403):
                    raise KCWaterAuthError("KC Water customer lookup was unauthorized")
                if response.status == 429:
                    raise KCWaterApiError("KC Water rate limit reached")
                if response.status != 200:
                    raise KCWaterApiError(f"KC Water customer lookup failed (HTTP {response.status})")
                payload = await response.json(content_type=None)
        except KCWaterApiError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise KCWaterApiError("Could not retrieve KC Water customer accounts") from err
        if not isinstance(payload, dict):
            raise KCWaterApiError("KC Water returned invalid customer data")
        return payload

    async def _token_request(self, data: dict[str, str]) -> dict[str, Any]:
        try:
            async with self.session.post(
                f"{API_BASE}{TOKEN_PATH}",
                data=data,
                auth=aiohttp.BasicAuth(OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET),
                headers={"Accept": "application/json"},
                timeout=TIMEOUT,
            ) as response:
                if response.status in (400, 401, 403):
                    raise KCWaterAuthError("KC Water rejected authentication")
                if response.status == 429:
                    raise KCWaterApiError("KC Water rate limit reached")
                if response.status != 200:
                    raise KCWaterApiError(f"KC Water authentication failed (HTTP {response.status})")
                payload = await response.json(content_type=None)
        except KCWaterApiError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise KCWaterApiError("Could not connect to KC Water") from err
        if not isinstance(payload, dict):
            raise KCWaterApiError("KC Water returned an invalid authentication response")
        return payload

    def _store_tokens(self, payload: dict[str, Any]) -> None:
        self.access_token = payload.get("access_token")
        self.refresh_token = payload.get("refresh_token") or self.refresh_token
        try:
            lifetime = max(1, int(payload.get("expires_in", 3600)))
        except (TypeError, ValueError):
            lifetime = 3600
        self.expires_at = datetime.now(UTC) + timedelta(seconds=lifetime)

    async def _refresh(self) -> bool:
        """Try the OAuth refresh grant; the grant shape is unverified by live capture."""
        if not self.refresh_token:
            return False
        try:
            payload = await self._token_request(
                {"grant_type": "refresh_token", "refresh_token": self.refresh_token}
            )
        except KCWaterApiError:
            return False
        if not payload.get("access_token"):
            return False
        self._store_tokens(payload)
        return True

    async def async_get_usage(self, entry_data: dict[str, Any]) -> dict[str, Any]:
        """Fetch usage for the selected account and current day selector."""
        if not self.access_token:
            await self.async_authenticate()
        if self.expires_at and datetime.now(UTC) >= self.expires_at - timedelta(seconds=60):
            if not await self._refresh():
                await self._reauthenticate()

        body = {
            "customerId": entry_data[CONF_CUSTOMER_ID],
            "accountContext": {
                "accountNumber": entry_data[CONF_ACCOUNT_NUMBER],
                "serviceId": entry_data[CONF_SERVICE_ID],
            },
            "direction": "current",
            "page": "1",
            "maxPerPage": "13",
        }
        try:
            async with self.session.post(
                f"{API_BASE}{USAGE_PATH}",
                json=body,
                headers={"Authorization": f"Bearer {self.access_token}", "Accept": "application/json"},
                timeout=TIMEOUT,
            ) as response:
                if response.status == 401:
                    if not await self._refresh():
                        await self._reauthenticate()
                    async with self.session.post(
                        f"{API_BASE}{USAGE_PATH}",
                        json=body,
                        headers={"Authorization": f"Bearer {self.access_token}", "Accept": "application/json"},
                        timeout=TIMEOUT,
                    ) as retry:
                        return await self._usage_response(retry)
                return await self._usage_response(response)
        except KCWaterApiError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise KCWaterApiError("Could not retrieve KC Water usage") from err

    async def _usage_response(self, response: aiohttp.ClientResponse) -> dict[str, Any]:
        if response.status in (401, 403):
            raise KCWaterAuthError("KC Water authorization expired")
        if response.status == 429:
            raise KCWaterApiError("KC Water rate limit reached")
        if response.status != 200:
            raise KCWaterApiError(f"Usage request failed (HTTP {response.status})")
        try:
            payload = await response.json(content_type=None)
        except (ValueError, aiohttp.ClientError) as err:
            raise KCWaterApiError("KC Water returned invalid usage data") from err
        if not isinstance(payload, dict):
            raise KCWaterApiError("KC Water returned invalid usage data")
        return payload

    async def _reauthenticate(self) -> None:
        try:
            await self.async_authenticate()
        except KCWaterAuthError:
            raise
        except KCWaterApiError as err:
            raise KCWaterAuthError("KC Water credentials need to be updated") from err


class KCWaterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll selected account usage and normalize response data."""

    def __init__(self, hass, entry, session: aiohttp.ClientSession) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=UPDATE_INTERVAL)
        self.entry = entry
        self.client = KCWaterClient(session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            if not self.client.access_token:
                await self.client.async_authenticate()
            payload = await self.client.async_get_usage(self.entry.data)
        except KCWaterAuthError as err:
            raise ConfigEntryAuthFailed("KC Water credentials need to be re-entered") from err
        except KCWaterApiError as err:
            raise UpdateFailed(str(err)) from err
        # Some portal failures arrive with HTTP 200 and an error string in the
        # response body. Do not publish those as a successful empty usage result.
        status = payload.get("status")
        if isinstance(status, str) and status.strip().casefold() in {
            "internal server error",
            "error",
            "failed",
        }:
            raise UpdateFailed("KC Water reported a usage service error")
        summary = payload.get("jsonData", {})
        if isinstance(summary, str):
            try:
                summary = json.loads(summary)
            except json.JSONDecodeError:
                summary = {}
        if not isinstance(summary, dict):
            summary = {}
        table = summary.get("serviceTableData", {})
        if isinstance(table, str):
            try:
                table = json.loads(table)
            except json.JSONDecodeError:
                table = {}
        if not isinstance(table, dict):
            table = {}
        history = payload.get("history")
        if not isinstance(history, list):
            history = []
        try:
            await self._async_import_history_statistics(history)
        except Exception:  # Recorder import failure should not take down live sensors.
            _LOGGER.exception("Could not import KC Water billing history statistics")
        return {"history": history, "summary": table, "status": status}

    async def _async_import_history_statistics(self, rows: list[Any]) -> None:
        """Import portal billing periods as Energy-compatible external statistics."""
        usage_by_date: dict[date, float] = {}
        today = dt_util.now().date()
        for row in rows:
            if not isinstance(row, dict):
                continue
            reading_date = _history_date(row)
            gallons = _nonnegative_number(row.get("gallonsConsumption"))
            if reading_date is None or reading_date > today or gallons is None:
                continue
            usage_by_date[reading_date] = gallons
        if not usage_by_date:
            return

        statistic_id = f"{DOMAIN}:{self.entry.entry_id.replace('-', '_').lower()}_billing_history"
        recorder = get_instance(self.hass)
        last_stats = await recorder.async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, set()
        )
        existing = last_stats.get(statistic_id, [])
        latest_start = existing[0]["start"] if existing else None
        running_sum = float(existing[0].get("sum", 0)) if existing else 0.0

        metadata: dict[str, Any] = {
            "has_sum": True,
            "name": "KC Water billing history",
            "source": DOMAIN,
            "statistic_id": statistic_id,
            "unit_class": VolumeConverter.UNIT_CLASS,
            "unit_of_measurement": "gal",
        }
        if StatisticMeanType is None:
            metadata["has_mean"] = False
        else:
            metadata["mean_type"] = StatisticMeanType.NONE

        timezone = dt_util.get_time_zone(self.hass.config.time_zone) or UTC
        statistics: list[StatisticData] = []
        for reading_date, gallons in sorted(usage_by_date.items()):
            start = datetime.combine(reading_date, datetime.min.time(), tzinfo=timezone)
            if latest_start is not None and start.timestamp() <= latest_start:
                continue
            running_sum += gallons
            statistics.append(StatisticData(start=start, state=gallons, sum=running_sum))

        if statistics:
            async_add_external_statistics(self.hass, StatisticMetaData(**metadata), statistics)


def _history_date(row: dict[str, Any]) -> date | None:
    """Parse the portal's billing read date."""
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


def _nonnegative_number(value: Any) -> float | None:
    """Parse a finite, non-negative numeric usage value."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 and number < float("inf") else None
