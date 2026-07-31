import logging
import voluptuous as vol
from typing import Any
import serial
from homeassistant import config_entries
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv
from homeassistant.data_entry_flow import FlowResult
from homeassistant.const import CONF_SCAN_INTERVAL

from .const import DOMAIN, CONF_PORT, CONF_BAUDRATE, DEFAULT_PORT, DEFAULT_BAUDRATE, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


def _test_serial_port(port: str, baudrate: int) -> bool:
    """Seri portun açılıp açılamadığını test eden yardımcı fonksiyon."""
    ser = None
    try:
        ser = serial.Serial(port, baudrate, timeout=1)
        ser.write(b'AT\r')
        return ser.is_open
    except Exception as e:
        _LOGGER.error("GL865T Seri Port Test Hatası (%s): %s", port, e)
        return False
    finally:
        if ser and ser.is_open:
            ser.close()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Arayüzden entegrasyon ekleme akışı."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """İlk ekleme adımı."""
        errors = {}

        # Tekil cihaz kontrolü
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            port = user_input[CONF_PORT]
            baudrate = user_input[CONF_BAUDRATE]

            # Seri portu test et
            success = await self.hass.async_add_executor_job(_test_serial_port, port, baudrate)

            if success:
                return self.async_create_entry(
                    title=f"Telit GL865 ({port})", 
                    data=user_input
                )
            else:
                errors["base"] = "cannot_connect"

        schema = vol.Schema(
            {
                vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.string,
                vol.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): vol.In([9600, 19200, 38400, 57600, 115200]),
                vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return OptionsFlow(config_entry)


class OptionsFlow(config_entries.OptionsFlowWithConfigEntry):
    """Cihaz Ayarlarını (Yapılandır) menüsünden güncelleme akışı."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors = {}
        data = user_input or self.config_entry.data

        if user_input is not None:
            port = user_input[CONF_PORT]
            baudrate = user_input[CONF_BAUDRATE]

            success = await self.hass.async_add_executor_job(_test_serial_port, port, baudrate)

            if success:
                self.hass.config_entries.async_update_entry(self.config_entry, data=user_input)
                return self.async_create_entry(title="", data=user_input)
            else:
                errors["base"] = "cannot_connect"

        data_schema = vol.Schema(
            {
                vol.Required(CONF_PORT, default=data.get(CONF_PORT, DEFAULT_PORT)): cv.string,
                vol.Required(CONF_BAUDRATE, default=data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)): vol.In([9600, 19200, 38400, 57600, 115200]),
                vol.Required(CONF_SCAN_INTERVAL, default=data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): int,
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema, errors=errors)
