"""Light platform: single lights and Hao Deng mesh groups."""

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
    CONF_GROUPS,
    CONF_PLACE_ID,
    DEFAULT_INVERT_CCT,
    DEFAULT_MAX_KELVIN,
    DEFAULT_MIN_KELVIN,
    DEV_FIRMWARE,
    DEV_GROUPS,
    DEV_MAC,
    DEV_MANUFACTURER,
    DEV_MESH_ID,
    DEV_MODEL,
    DEV_NAME,
    DOMAIN,
    GROUP_ID,
    GROUP_NAME,
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
    kelvin = (
        entry.options.get(OPT_MIN_KELVIN, DEFAULT_MIN_KELVIN),
        entry.options.get(OPT_MAX_KELVIN, DEFAULT_MAX_KELVIN),
        entry.options.get(OPT_INVERT_CCT, DEFAULT_INVERT_CCT),
    )
    devices = entry.data[CONF_DEVICES]
    entities: list[LightEntity] = [HaoDengLight(mesh, device, *kelvin) for device in devices]

    for group in entry.data.get(CONF_GROUPS, []):
        members = [d[DEV_MESH_ID] for d in devices if group[GROUP_ID] in d.get(DEV_GROUPS, [])]
        if members:
            entities.append(
                HaoDengGroupLight(mesh, entry.entry_id, entry.data[CONF_PLACE_ID], group, members, *kelvin)
            )
    async_add_entities(entities)


def _to_percent(ha_brightness: int) -> int:
    return max(1, min(100, round(ha_brightness * 100 / 255)))


def _to_ha(percent: int) -> int:
    return max(0, min(255, round(percent * 255 / 100)))


def _hue_close(a: int, b: int) -> bool:
    diff = abs(a - b) % 256
    return min(diff, 256 - diff) <= _HUE_TOLERANCE


class _HaoDengLightBase(HaoDengEntity, LightEntity):
    """Shared command handling. Subclasses decide the destination and the state."""

    _attr_supported_color_modes = {ColorMode.COLOR_TEMP, ColorMode.RGB}

    def __init__(
        self, mesh: HaoDengMesh, dest: int, min_kelvin: int, max_kelvin: int, invert_cct: bool
    ) -> None:
        super().__init__(mesh)
        self._dest = dest
        self._attr_min_color_temp_kelvin = min_kelvin
        self._attr_max_color_temp_kelvin = max_kelvin
        self._invert_cct = invert_cct
        self._commanded_rgb: tuple[int, int, int] | None = None
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

    def _apply_status(self, status: LightStatus) -> None:
        """Take over on/brightness/colour from a (representative) light status."""
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
            await self._mesh.async_send(self._dest, command)
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


class HaoDengLight(_HaoDengLightBase):
    """A single light in the mesh."""

    _attr_name = None  # use the device name

    def __init__(
        self,
        mesh: HaoDengMesh,
        device: dict[str, Any],
        min_kelvin: int,
        max_kelvin: int,
        invert_cct: bool,
    ) -> None:
        super().__init__(mesh, device[DEV_MESH_ID], min_kelvin, max_kelvin, invert_cct)
        mac = normalize_mac(device[DEV_MAC])
        self._attr_unique_id = mac.replace(":", "").lower()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            connections={(CONNECTION_BLUETOOTH, mac)},
            name=device[DEV_NAME],
            manufacturer=device.get(DEV_MANUFACTURER) or "Zengge",
            model=(device.get(DEV_MODEL) or "").replace("_", " ") or None,
            sw_version=device.get(DEV_FIRMWARE),
        )
        self._last_status: LightStatus | None = None

    @property
    def available(self) -> bool:
        return self._mesh.is_available(self._dest)

    @callback
    def _handle_mesh_update(self) -> None:
        status = self._mesh.status.get(self._dest)
        if status is not None and status != self._last_status:
            self._last_status = status
            self._apply_status(status)
        self.async_write_ha_state()


class HaoDengGroupLight(_HaoDengLightBase):
    """A group as defined in the Hao Deng app. One command switches all members at once."""

    _attr_name = None  # use the group (device) name

    def __init__(
        self,
        mesh: HaoDengMesh,
        entry_id: str,
        place_id: str,
        group: dict[str, Any],
        members: list[int],
        min_kelvin: int,
        max_kelvin: int,
        invert_cct: bool,
    ) -> None:
        super().__init__(mesh, group[GROUP_ID], min_kelvin, max_kelvin, invert_cct)
        self._members = members
        self._attr_unique_id = f"{place_id}_group_{group[GROUP_ID]}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=group[GROUP_NAME],
            manufacturer="Zengge",
            model="Mesh group",
        )
        self._attr_extra_state_attributes = {"mesh_group_id": group[GROUP_ID]}
        self._last_statuses: tuple[LightStatus | None, ...] = ()

    @property
    def available(self) -> bool:
        return any(self._mesh.is_available(member) for member in self._members)

    @callback
    def _handle_mesh_update(self) -> None:
        statuses = tuple(self._mesh.status.get(member) for member in self._members)
        if statuses != self._last_statuses:
            self._last_statuses = statuses
            known = [s for s in statuses if s is not None and s.online]
            if known:
                lit = [s for s in known if s.is_on]
                # Representative member: the brightest one that is on, else the first known
                self._apply_status(max(lit, key=lambda s: s.brightness) if lit else known[0])
                self._attr_is_on = bool(lit)
        self.async_write_ha_state()
