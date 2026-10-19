"""F5 multimodal — public interface (owned by the safety/multimodal engineer; see /TEAM.md).

Routes and the turn graph ONLY import from here. Stable: illustrate / speak / regenerate / list_assets.
Extras: key_scene_assets (image + narrator audio in parallel), is_key_scene, build_scene_prompt, voice_for.
"""
from app.multimodal.assets import (STATS, build_scene_prompt, get_asset, is_key_scene,  # noqa: F401
                                   key_scene_assets)
from app.multimodal.service import illustrate, list_assets, regenerate, speak  # noqa: F401
from app.multimodal.voices import ALL_VOICES, NARRATOR_VOICE, voice_for  # noqa: F401
