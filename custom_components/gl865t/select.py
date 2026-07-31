from __future__ import annotations
import logging
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GL865TCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Register GL865T Select entity."""
    coordinator: GL865TCoordinator = hass.data[DOMAIN][entry.entry_id]

    select_entity = GL865TSmsSelect(coordinator)
    coordinator.select_entity = select_entity

    async_add_entities([select_entity])


class GL865TSmsSelect(CoordinatorEntity[GL865TCoordinator], SelectEntity):
    """Select entity listing recorded SMS items from SQLite DB by ID."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GL865TCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.unique_id}_select_sms_to_delete"
        self._attr_name = "Select SMS to Delete"
        self._attr_icon = "mdi:message-bulleted"
        self._attr_current_option: str | None = None

    @property
    def options(self) -> list[str]:
        if not self.coordinator.sms_history:
            return ["No Recorded SMS"]

        return [
            f"[{msg['id']}] {msg['sender']} - {msg['timestamp']}"
            for msg in self.coordinator.sms_history
            if msg.get("id") is not None
        ]

    @property
    def current_option(self) -> str | None:
        opts = self.options
        if self._attr_current_option in opts:
            return self._attr_current_option
        return None

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self.async_write_ha_state()
