"""F5 multimodal — public interface (owned by the safety/multimodal engineer; see /TEAM.md).

Routes and the turn graph ONLY import from here. Stable: illustrate / speak / regenerate / list_assets.
Extras: key_scene_assets (image + narrator audio in parallel), is_key_scene, build_scene_prompt, voice_for,
deadline helpers: get_asset / is_pending / pending_ids / wait_for_asset / drain_background;
status() → runtime switches (ZM_DISABLE_IMAGE, models, TTS background retry) + counters.
"""
from app.multimodal.assets import (STATS, build_scene_prompt, drain_background, get_asset,  # noqa: F401
                                   is_key_scene, is_pending, key_scene_assets, pending_ids, status,
                                   wait_for_asset)
from app.multimodal.service import illustrate, list_assets, regenerate, speak  # noqa: F401
from app.multimodal.voices import ALL_VOICES, NARRATOR_VOICE, voice_for  # noqa: F401
