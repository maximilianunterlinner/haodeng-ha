"""Base entities."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .mesh import HaoDengMesh


class HaoDengEntity(Entity):
    """Entity that updates whenever the mesh reports a change (push, no polling)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, mesh: HaoDengMesh) -> None:
        self._mesh = mesh

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._mesh.async_add_listener(self._handle_mesh_update))
        self._handle_mesh_update()

    @callback
    def _handle_mesh_update(self) -> None:
        self.async_write_ha_state()


class HaoDengHubEntity(HaoDengEntity):
    """Diagnostic entity attached to the mesh hub device."""

    def __init__(self, mesh: HaoDengMesh, entry_id: str, key: str) -> None:
        super().__init__(mesh)
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry_id)})
