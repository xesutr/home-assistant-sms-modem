from dataclasses import dataclass
from collections.abc import Callable
from typing import Any
from homeassistant.components.sensor import (
    SensorStateClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GL865TCoordinator


@dataclass
class GL865TSensorConfigBase[T]:
    description: SensorEntityDescription
    value: Callable[[T], Any]
    attributes: Callable[[T], dict[str, Any]] | None = None


SENSOR_TYPES = (
    GL865TSensorConfigBase(
        value=lambda data: (
            data["last_sms"].get("body", "No Messages")[:255]
            if data and data.get("last_sms")
            else "No Messages"
        ),
        attributes=lambda data: {
            "sender": data["last_sms"].get("sender", "Unknown") if data and data.get("last_sms") else "Unknown",
            "timestamp": data["last_sms"].get("timestamp", "Unknown") if data and data.get("last_sms") else "Unknown",
            "full_message": data["last_sms"].get("body", "") if data and data.get("last_sms") else "",
            "messages": data.get("sms_history", []) if data else [],
        },
        description=SensorEntityDescription(
            key="last_sms",
            name="Last Received SMS",
            icon="mdi:email-outline",
        ),
    ),
    GL865TSensorConfigBase(
        value=lambda data: data.get("new_sms_count", 0) if data else 0,
        description=SensorEntityDescription(
            key="unread_sms_count",
            name="Unread SMS Count",
            icon="mdi:message-badge-outline",
            state_class=SensorStateClass.TOTAL,
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up GL865T sensors based on a config entry."""
    coordinator: GL865TCoordinator = hass.data[DOMAIN][entry.entry_id]

    sensors = [
        GL865TSensor(coordinator, sensor_config)
        for sensor_config in SENSOR_TYPES
    ]

    async_add_entities(sensors, False)


class GL865TSensor(CoordinatorEntity[GL865TCoordinator], SensorEntity):
    """GL865T Sensor Entity architecture fully compatible with Home Assistant standard."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GL865TCoordinator,
        sensor_config: GL865TSensorConfigBase,
    ) -> None:
        super().__init__(coordinator)

        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.unique_id}_{DOMAIN}_{sensor_config.description.key}"
        self.entity_description = sensor_config.description
        self.sensor_config = sensor_config

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor directly from coordinator data."""
        if self.coordinator.data is not None:
            return self.sensor_config.value(self.coordinator.data)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return dynamic attributes from coordinator data."""
        if self.coordinator.data is not None and self.sensor_config.attributes:
            return self.sensor_config.attributes(self.coordinator.data)
        return None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None
