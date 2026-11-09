"""Button to force a reconnect to the mesh."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HaoDengConfigEntry
from .entity import HaoDengHubEntity
from .mesh import MeshError


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaoDengConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ReconnectButton(entry.runtime_data, entry.entry_id, "reconnect")])


class ReconnectButton(HaoDengHubEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        try:
            await self._mesh.async_reconnect()
        except MeshError as err:
            raise HomeAssistantError(str(err)) from err
