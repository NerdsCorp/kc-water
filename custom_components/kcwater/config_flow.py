"""Config flow for KC Water."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_ACCOUNT, CONF_ACCOUNT_NUMBER, CONF_CUSTOMER_ID, CONF_SERVICE_ID, DOMAIN
from .coordinator import KCWaterApiError, KCWaterClient


def _choices(user: dict[str, Any]) -> tuple[str, dict[str, dict[str, str]]]:
    """Build stable UI choices only from account/service fields supplied by API."""
    customer_id = user.get("customerId")
    accounts = user.get("accounts")
    choices: dict[str, dict[str, str]] = {}
    if not isinstance(customer_id, (str, int)) or not isinstance(accounts, list):
        return "", choices
    for account in accounts:
        if not isinstance(account, dict):
            continue
        account_number = account.get("accountNumber") or account.get("accountNo")
        services = account.get("services") or account.get("serviceList") or [account]
        if not account_number or not isinstance(services, list):
            continue
        for service in services:
            if not isinstance(service, dict):
                continue
            service_id = service.get("serviceId") or service.get("serviceID")
            if service_id is None:
                continue
            identifier = f"{account_number}|{service_id}"
            label = str(account.get("accountName") or "Account")
            label += f" account ending {str(account_number)[-4:]} / {service.get('serviceName') or service_id}"
            choices[identifier] = {
                "account_number": str(account_number),
                "service_id": str(service_id),
                "label": label,
            }
    return str(customer_id), choices


class KCWaterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure KC Water credentials and account/service selection."""

    VERSION = 1

    def __init__(self) -> None:
        self._credentials: dict[str, str] = {}
        self._customer_id = ""
        self._choices: dict[str, dict[str, str]] = {}

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input:
            client = KCWaterClient(
                async_get_clientsession(self.hass),
                user_input[CONF_USERNAME].strip(),
                user_input[CONF_PASSWORD],
            )
            try:
                user = await client.async_authenticate()
                self._customer_id, self._choices = _choices(user)
                if not self._choices:
                    errors["base"] = "accounts_unavailable"
                else:
                    self._credentials = {
                        CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    }
                    return await self.async_step_account()
            except KCWaterApiError as err:
                errors["base"] = "invalid_auth" if "rejected" in str(err).lower() else "cannot_connect"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
            ),
            errors=errors,
        )

    async def async_step_account(self, user_input=None):
        if user_input:
            selected = self._choices[user_input[CONF_ACCOUNT]]
            await self.async_set_unique_id(self._credentials[CONF_USERNAME].casefold())
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="KC Water",
                data={
                    **self._credentials,
                    CONF_CUSTOMER_ID: self._customer_id,
                    CONF_ACCOUNT_NUMBER: selected["account_number"],
                    CONF_SERVICE_ID: selected["service_id"],
                },
            )
        return self.async_show_form(
            step_id="account",
            data_schema=vol.Schema(
                {vol.Required(CONF_ACCOUNT): vol.In({key: value["label"] for key, value in self._choices.items()})}
            ),
        )

    async def async_step_reauth(self, entry_data):
        """Prompt for updated portal credentials when HA reports auth failure."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        entry = self._get_reauth_entry()
        if user_input:
            client = KCWaterClient(
                async_get_clientsession(self.hass),
                entry.data[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            try:
                user = await client.async_authenticate()
                customer_id, choices = _choices(user)
                key = f"{entry.data[CONF_ACCOUNT_NUMBER]}|{entry.data[CONF_SERVICE_ID]}"
                if key not in choices:
                    return self.async_show_form(
                        step_id="reauth_confirm",
                        data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
                        errors={"base": "account_missing"},
                    )
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD], CONF_CUSTOMER_ID: customer_id},
                )
            except KCWaterApiError as err:
                return self.async_show_form(
                    step_id="reauth_confirm",
                    data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
                    errors={"base": "invalid_auth" if "rejected" in str(err).lower() else "cannot_connect"},
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
        )

