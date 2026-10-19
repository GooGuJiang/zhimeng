"""F5 multimodal — public interface (owned by the safety/multimodal engineer; see /TEAM.md).

Routes and the turn graph ONLY import from here. Implementations live in
``app/multimodal/service.py`` (currently a placeholder stub written by backend core).
"""
from app.multimodal.service import (  # noqa: F401
    illustrate,
    list_assets,
    regenerate,
    speak,
)
