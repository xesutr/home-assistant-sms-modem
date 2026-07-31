from __future__ import annotations
import logging
from homeassistant.components.button import ButtonEntity
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
    """Register GL865T Delete Button entity."""
    coordinator: GL865TCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([GL865TDeleteSmsButton(coordinator)])


class GL865TDeleteSmsButton(CoordinatorEntity[GL865TCoordinator], ButtonEntity):
    """Button entity executing SMS deletion strictly for selected ID."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GL865TCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.unique_id}_button_delete_sms"
        self._attr_name = "Delete Selected SMS"
        self._attr_icon = "mdi:delete-forever"

    async def async_press(self) -> None:
        """Fetch option directly from the Select entity attached to coordinator."""
        select_entity = getattr(self.coordinator, "select_entity", None)

        if not select_entity:
            _LOGGER.warning("GL865T: Select entity reference not found on coordinator.")
            return

        current_opt = select_entity.current_option

        if not current_opt or current_opt == "No Recorded SMS":
            _LOGGER.warning("GL865T: No valid SMS selected for deletion.")
            return

        try:
            target_id = int(current_opt.split("]")[0].replace("[", "").strip())
        except Exception as e:
            _LOGGER.error("GL865T: Could not parse selected SMS ID: %s", e)
            return

        self.coordinator.delete_sms_by_id(target_id)

        select_entity._attr_current_option = None
        select_entity.async_write_ha_state()

        _LOGGER.info("GL865T: Successfully deleted SMS with ID %s.", target_id)
