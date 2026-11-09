"""Parsing of decrypted status notifications."""

from __future__ import annotations

import colorsys
from dataclasses import dataclass

from .commands import BRIDGE_MESH_ADDRESS, OPCODE_NOTIFICATION

# Mode byte values that mean "RGB colour" (from upstream observations)
RGB_MODES = frozenset({42, 63})


@dataclass(frozen=True, slots=True)
class LightStatus:
    """State of one mesh node as reported by the mesh."""

    mesh_id: int
    online: bool
    brightness: int  # 0-100
    mode: int
    value: int  # hue (0-255) in RGB mode, colour temperature (0-100) in white mode

    @property
    def is_bridge(self) -> bool:
        return self.mesh_id == BRIDGE_MESH_ADDRESS

    @property
    def is_on(self) -> bool:
        return self.online and self.brightness > 0

    @property
    def is_rgb(self) -> bool:
        return self.mode in RGB_MODES

    @property
    def hue_rgb(self) -> tuple[int, int, int]:
        """Fully saturated RGB for the reported hue byte."""
        red, green, blue = colorsys.hsv_to_rgb((self.value % 256) / 255.0, 1.0, 1.0)
        return round(red * 255), round(green * 255), round(blue * 255)


def parse_notification(data: bytes) -> list[LightStatus]:
    """Parse a decrypted notification packet. Each one carries up to two nodes."""
    if len(data) < 20 or data[7] != OPCODE_NOTIFICATION:
        return []
    result: list[LightStatus] = []
    for start in (10, 15):
        mesh_id, online, bright, mode, value = data[start : start + 5]
        if mesh_id == 0:
            continue
        result.append(
            LightStatus(
                mesh_id=mesh_id,
                online=online != 0,
                brightness=min(bright, 100),
                mode=mode,
                value=value,
            )
        )
    return result


def rgb_to_hue_byte(red: int, green: int, blue: int) -> int:
    hue, _, _ = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)
    return round(hue * 255) % 256
