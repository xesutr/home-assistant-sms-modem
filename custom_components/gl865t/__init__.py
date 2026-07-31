import logging
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.helpers import device_registry

from .const import DOMAIN, EVENT_NEW_SMS
from .coordinator import GL865TCoordinator
from .modem import GL865TModem

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SELECT,
    Platform.BUTTON,
]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialize GSM Module via Config Entry."""
    port = entry.data.get("port", "/dev/ttyUSB0")
    baud = entry.data.get("baudrate", 115200)
    scan_interval = entry.data.get("scan_interval", 20)

    # 1. Create modem instance
    modem = GL865TModem(port, baud)

    # 2. Create coordinator instance
    coordinator = GL865TCoordinator(hass, modem, scan_interval, _LOGGER, entry.entry_id)

    # Load stored SMS history from disk to RAM (prevents loss after restart)
    await coordinator._async_setup()

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    # 3. Setup listeners (SMS Event) and storage
    _async_add_listeners(hass, coordinator)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # 4. Load platforms (Sensor, Select, Button)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    # 5. Register services (send_sms, make_call, delete_sms)
    register_services(hass, coordinator)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload integration entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Reload integration entry."""
    await hass.config_entries.async_reload(config_entry.entry_id)


def register_services(hass: HomeAssistant, coord: GL865TCoordinator) -> None:
    """Register integration services."""

    async def send_sms_service(service: ServiceCall) -> None:
        target_raw = service.data.get("target") or service.data.get("number")
        message = service.data.get("message") or service.data.get("text")

        targets: list[str] = []

        # 1. Process incoming phone numbers
        if target_raw:
            if isinstance(target_raw, str):
                targets = [n.strip() for n in target_raw.split(",") if n.strip()]
            elif isinstance(target_raw, list):
                for item in target_raw:
                    if isinstance(item, str):
                        targets.extend([n.strip() for n in item.split(",") if n.strip()])

        # 2. If target is empty, read Helper
        if not targets:
            helper_state = hass.states.get("input_text.sms_bildirim_listesi")
            if helper_state:
                raw_val = helper_state.state
                if raw_val in ("unknown", "unavailable", None, ""):
                    raw_val = helper_state.attributes.get("pattern", "")

                if raw_val and raw_val not in ("unknown", "unavailable"):
                    targets = [n.strip() for n in raw_val.split(",") if n.strip()]

        if not targets or not message:
            _LOGGER.error("GL865T: Missing SMS parameters! Targets: %s, Message: %s", targets, message)
            return

        def callback():
            coord.modem.send_sms(targets, message)

        # Serial port operation executed in executor thread to prevent blocking async loop
        await hass.async_add_executor_job(callback)

    hass.services.async_register(DOMAIN, "send_sms", send_sms_service)

    async def make_call_service(service: ServiceCall) -> None:
        target = service.data.get("target") or service.data.get("number")
        duration = service.data.get("duration", 10)

        if not target:
            _LOGGER.error("GL865T: No target phone number specified for call!")
            return

        def callback():
            coord.modem.make_call(target, duration)

        await hass.async_add_executor_job(callback)

    hass.services.async_register(DOMAIN, "make_call", make_call_service)

    async def delete_sms_service(service: ServiceCall) -> None:
        sms_id = service.data.get("id")
        sender = service.data.get("sender")
        timestamp = service.data.get("timestamp")

        # 1. Priority: Delete from SQLite database using ID
        if sms_id is not None:
            coord.delete_sms_by_id(int(sms_id))
            return

        # 2. Fallback: Delete using Sender and Timestamp
        if sender and timestamp:
            coord.delete_sms(sender, timestamp)
            return

        _LOGGER.error("GL865T: Missing parameters for SMS deletion!")

    hass.services.async_register(DOMAIN, "delete_sms", delete_sms_service)


def _async_add_listeners(hass: HomeAssistant, coord: GL865TCoordinator) -> None:
    """Listener triggering event upon new SMS arrival."""
    coord.async_add_listener(
        lambda: _fire_sms_event(hass, coord)
    )


def _fire_sms_event(hass: HomeAssistant, coord: GL865TCoordinator) -> None:
    """Fires event to HA Event Bus for each new incoming SMS."""
    for sms in coord.new_sms:
        hass.bus.fire(
            EVENT_NEW_SMS,
            {
                "id": sms.get("id"),
                "sender": sms.get("sender"),
                "content": sms.get("body"),
                "received_at": sms.get("received_at"),
            },
        )
    coord.new_sms = []
