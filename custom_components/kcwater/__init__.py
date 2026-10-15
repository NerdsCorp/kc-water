"""KC Water Home Assistant integration."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .const import DOMAIN
from .coordinator import KCWaterCoordinator

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up integration."""
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a configured account."""
    coordinator = KCWaterCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an account."""
    ok = await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    if ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
        if coordinator:
            await coordinator.client.async_close()
    return ok
