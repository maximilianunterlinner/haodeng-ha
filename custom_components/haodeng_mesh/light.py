"""Light platform."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HaoDengConfigEntry
from .const import (
    CONF_DEVICES,
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
from .entity import HaoDengEntity
from .mesh import HaoDengMesh, MeshError
from .protocol import LightStatus, commands, normalize_mac, rgb_to_hue_byte

_HUE_TOLERANCE = 4  # hue byte steps; keeps the user's exact colour if the lamp reports ~the same hue


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaoDengConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    mesh = entry.runtime_data
    min_k = entry.options.get(OPT_MIN_KELVIN, DEFAULT_MIN_KELVIN)
    max_k = entry.options.get(OPT_MAX_KELVIN, DEFAULT_MAX_KELVIN)
    invert = entry.options.get(OPT_INVERT_CCT, DEFAULT_INVERT_CCT)
    async_add_entities(
        HaoDengLight(mesh, entry.entry_id, device, min_k, max_k, invert)
        for device in entry.data[CONF_DEVICES]
    )


def _to_percent(ha_brightness: int) -> int:
    return max(1, min(100, round(ha_brightness * 100 / 255)))


def _to_ha(percent: int) -> int:
    return max(0, min(255, round(percent * 255 / 100)))


def _hue_close(a: int, b: int) -> bool:
    diff = abs(a - b) % 256
    return min(diff, 256 - diff) <= _HUE_TOLERANCE


class HaoDengLight(HaoDengEntity, LightEntity):
    """A single light in the mesh."""

    _attr_name = None  # use the device name
    _attr_supported_color_modes = {ColorMode.COLOR_TEMP, ColorMode.RGB}

    def __init__(
        self,
        mesh: HaoDengMesh,
        entry_id: str,
        device: dict[str, Any],
        min_kelvin: int,
        max_kelvin: int,
        invert_cct: bool,
    ) -> None:
        super().__init__(mesh)
        self._mesh_id: int = device[DEV_MESH_ID]
        mac = normalize_mac(device[DEV_MAC])
        self._attr_unique_id = mac.replace(":", "").lower()
        self._attr_min_color_temp_kelvin = min_kelvin
        self._attr_max_color_temp_kelvin = max_kelvin
        self._invert_cct = invert_cct
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            connections={(CONNECTION_BLUETOOTH, mac)},
            name=device[DEV_NAME],
            manufacturer=device.get(DEV_MANUFACTURER) or "Zengge",
            model=(device.get(DEV_MODEL) or "").replace("_", " ") or None,
            sw_version=device.get(DEV_FIRMWARE),
            via_device=(DOMAIN, entry_id),
        )
        self._last_status: LightStatus | None = None
        self._commanded_rgb: tuple[int, int, int] | None = None

        # Start values until the first status arrives
        self._attr_is_on = None
        self._attr_brightness = None
        self._attr_color_mode = ColorMode.COLOR_TEMP
        self._attr_color_temp_kelvin = None
        self._attr_rgb_color = None

    # ------------------------------------------------------------ conversions

    def _kelvin_to_device(self, kelvin: int) -> int:
        low, high = self.min_color_temp_kelvin, self.max_color_temp_kelvin
        ratio = (min(max(kelvin, low), high) - low) / (high - low)
        if self._invert_cct:
            ratio = 1 - ratio
        return round(ratio * 100)

    def _device_to_kelvin(self, value: int) -> int:
        low, high = self.min_color_temp_kelvin, self.max_color_temp_kelvin
        ratio = min(max(value, 0), 100) / 100
        if self._invert_cct:
            ratio = 1 - ratio
        return round(low + ratio * (high - low))

    # ------------------------------------------------------------------ state

    @property
    def available(self) -> bool:
        return self._mesh.is_available(self._mesh_id)

    @callback
    def _handle_mesh_update(self) -> None:
        status = self._mesh.status.get(self._mesh_id)
        if status is not None and status != self._last_status:
            self._last_status = status
            self._apply_status(status)
        self.async_write_ha_state()

    def _apply_status(self, status: LightStatus) -> None:
        self._attr_is_on = status.is_on
        if status.brightness > 0:
            self._attr_brightness = _to_ha(status.brightness)
        if status.is_rgb:
            self._attr_color_mode = ColorMode.RGB
            if self._commanded_rgb is None or not _hue_close(
                rgb_to_hue_byte(*self._commanded_rgb), status.value
            ):
                self._commanded_rgb = None
                self._attr_rgb_color = status.hue_rgb
        else:
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._attr_color_temp_kelvin = self._device_to_kelvin(status.value)

    # --------------------------------------------------------------- commands

    async def _send(self, command: commands.Command) -> None:
        try:
            await self._mesh.async_send(self._mesh_id, command)
        except MeshError as err:
            raise HomeAssistantError(f"{self.name or 'Light'}: {err}") from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        percent = _to_percent(brightness) if brightness is not None else None

        if ATTR_RGB_COLOR in kwargs:
            red, green, blue = kwargs[ATTR_RGB_COLOR]
            await self._send(commands.rgb(red, green, blue))
            if percent is not None:
                await self._send(commands.brightness(percent))
            self._commanded_rgb = (red, green, blue)
            self._attr_rgb_color = (red, green, blue)
            self._attr_color_mode = ColorMode.RGB
        elif ATTR_COLOR_TEMP_KELVIN in kwargs:
            kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]
            if percent is None:
                percent = _to_percent(self._attr_brightness or 255)
            await self._send(commands.color_temperature(self._kelvin_to_device(kelvin), percent))
            self._attr_color_temp_kelvin = kelvin
            self._attr_color_mode = ColorMode.COLOR_TEMP
        elif percent is not None:
            await self._send(commands.brightness(percent))
        else:
            await self._send(commands.power(True))

        self._attr_is_on = True
        if percent is not None:
            self._attr_brightness = _to_ha(percent)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send(commands.power(False))
        self._attr_is_on = False
        self.async_write_ha_state()
