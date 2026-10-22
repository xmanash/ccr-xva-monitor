"""Dependency-light helpers shared by later finance projects in this workspace."""

from shared.ids import new_id
from shared.settings import Settings, get_settings

__all__ = ["Settings", "get_settings", "new_id"]
