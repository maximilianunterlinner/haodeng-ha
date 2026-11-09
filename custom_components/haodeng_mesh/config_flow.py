"""Config flow: download mesh credentials once from the Hao Deng cloud.

Only the mesh credentials and the light list are stored. The cloud username
and password are NOT stored; runtime operation never contacts the cloud.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .cloud import (
    DEFAULT_REGION,
    REGION_SERVERS,
    CloudAuthError,
    CloudDevice,
    CloudError,
    CloudPlace,
    HaoDengCloud,
)
from .const import (
    CONF_DEVICES,
    CONF_MESH_LTK,
    CONF_MESH_NAME,
    CONF_MESH_PASSWORD,
    CONF_PLACE_ID,
    CONF_PLACE_NAME,
    CONF_REGION,
    DEFAULT_INVERT_CCT,
    DEFAULT_MAX_KELVIN,
    DEFAULT_MIN_KELVIN,
    DEV_FIRMWARE,
    DEV_MAC,
    DEV_MANUFACTURER,
    DEV_MESH_ID,
    DEV_MODEL,
    DEV_NAME,
    DOMAIN,
    OPT_INVERT_CCT,
    OPT_MAX_KELVIN,
    OPT_MIN_KELVIN,
)
from .protocol import normalize_mac

_LOGGER = logging.getLogger(__name__)

CONF_PLACE = "place"


def _login_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): TextSelector(
                TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
            ),
            vol.Required(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
            ),
            vol.Required(CONF_REGION, default=defaults.get(CONF_REGION, DEFAULT_REGION)): SelectSelector(
                SelectSelectorConfig(
                    options=list(REGION_SERVERS),
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="region",
                )
            ),
        }
    )


def _device_entry(device: CloudDevice) -> dict[str, Any]:
    return {
        DEV_MESH_ID: device.mesh_id,
        DEV_MAC: normalize_mac(device.mac),
        DEV_NAME: device.name,
        DEV_MODEL: device.model,
        DEV_MANUFACTURER: device.manufacturer,
        DEV_FIRMWARE: device.firmware,
    }


class HaoDengMeshConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._cloud: HaoDengCloud | None = None
        self._region: str = DEFAULT_REGION
        self._places: dict[str, CloudPlace] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> HaoDengOptionsFlow:
        return HaoDengOptionsFlow()

    async def _async_login(self, user_input: dict[str, Any], errors: dict[str, str]) -> bool:
        self._region = user_input[CONF_REGION]
        cloud = HaoDengCloud(async_get_clientsession(self.hass), self._region)
        try:
            await cloud.login(user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
            places = await cloud.places()
        except CloudAuthError:
            errors["base"] = "invalid_auth"
            return False
        except CloudError as err:
            _LOGGER.warning("Hao Deng cloud error: %s", err)
            errors["base"] = "cannot_connect"
            return False
        if not places:
            errors["base"] = "no_places"
            return False
        self._cloud = cloud
        self._places = {place.place_id: place for place in places}
        return True

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and await self._async_login(user_input, errors):
            if self.source == SOURCE_RECONFIGURE:
                place_id = self._get_reconfigure_entry().data[CONF_PLACE_ID]
                if place_id not in self._places:
                    return self.async_abort(reason="place_not_found")
                return await self._async_finish(self._places[place_id])
            if len(self._places) == 1:
                return await self._async_finish(next(iter(self._places.values())))
            return await self.async_step_place()

        defaults = dict(user_input or {})
        if self.source == SOURCE_RECONFIGURE:
            defaults.setdefault(CONF_REGION, self._get_reconfigure_entry().data.get(CONF_REGION))
        return self.async_show_form(step_id="user", data_schema=_login_schema(defaults), errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Download a fresh light list / credentials (e.g. after adding lights in the app)."""
        return await self.async_step_user(user_input)

    async def async_step_place(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return await self._async_finish(self._places[user_input[CONF_PLACE]])
        configured = {entry.unique_id for entry in self._async_current_entries()}
        options = {pid: place.name for pid, place in self._places.items() if pid not in configured}
        if not options:
            return self.async_abort(reason="already_configured")
        return self.async_show_form(
            step_id="place",
            data_schema=vol.Schema({vol.Required(CONF_PLACE): vol.In(options)}),
        )

    async def _async_finish(self, place: CloudPlace) -> ConfigFlowResult:
        assert self._cloud is not None
        await self.async_set_unique_id(place.place_id)
        try:
            devices = await self._cloud.devices(place.place_id)
        except CloudError as err:
            _LOGGER.warning("Could not load lights: %s", err)
            return self.async_abort(reason="cannot_connect")
        if not devices:
            return self.async_abort(reason="no_devices_found")

        data = {
            CONF_PLACE_ID: place.place_id,
            CONF_PLACE_NAME: place.name,
            CONF_REGION: self._region,
            CONF_MESH_NAME: place.mesh_name,
            CONF_MESH_PASSWORD: place.mesh_password,
            CONF_MESH_LTK: place.mesh_ltk,
            CONF_DEVICES: [_device_entry(device) for device in devices],
        }

        if self.source == SOURCE_RECONFIGURE:
            self._abort_if_unique_id_mismatch(reason="place_not_found")
            return self.async_update_reload_and_abort(self._get_reconfigure_entry(), data=data)

        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=place.name, data=data)


class HaoDengOptionsFlow(OptionsFlowWithReload):
    """Colour temperature settings."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[OPT_MIN_KELVIN] = int(user_input[OPT_MIN_KELVIN])
            user_input[OPT_MAX_KELVIN] = int(user_input[OPT_MAX_KELVIN])
            if user_input[OPT_MIN_KELVIN] >= user_input[OPT_MAX_KELVIN]:
                errors["base"] = "kelvin_range"
            else:
                return self.async_create_entry(data=user_input)

        current = {**self.config_entry.options, **(user_input or {})}
        kelvin = NumberSelectorConfig(
            min=1500, max=10000, step=100, unit_of_measurement="K", mode=NumberSelectorMode.BOX
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        OPT_MIN_KELVIN, default=current.get(OPT_MIN_KELVIN, DEFAULT_MIN_KELVIN)
                    ): NumberSelector(kelvin),
                    vol.Required(
                        OPT_MAX_KELVIN, default=current.get(OPT_MAX_KELVIN, DEFAULT_MAX_KELVIN)
                    ): NumberSelector(kelvin),
                    vol.Required(
                        OPT_INVERT_CCT, default=current.get(OPT_INVERT_CCT, DEFAULT_INVERT_CCT)
                    ): bool,
                }
            ),
            errors=errors,
        )
