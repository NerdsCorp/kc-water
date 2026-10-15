"""Redacted diagnostics for KC Water."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from .const import CONF_ACCOUNT_NUMBER, CONF_CUSTOMER_ID, DOMAIN

TO_REDACT = {"username", "password", CONF_ACCOUNT_NUMBER, CONF_CUSTOMER_ID, "access_token", "refresh_token"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry):
    """Return sanitized entry and normalized coordinator data."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    return {"entry": async_redact_data(dict(entry.data), TO_REDACT), "usage": coordinator.data}
