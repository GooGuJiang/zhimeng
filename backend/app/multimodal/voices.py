"""Voice casting: the narrator and each NPC get different, *stable* Qwen-TTS system voices.

Voice ids verified 2026-10-19 against 百炼「Qwen-TTS音色列表」https://help.aliyun.com/zh/model-studio/qwen-tts-voice-list
- shared by qwen-tts and qwen3-tts-flash: Cherry(芊悦,女) Serena(苏瑶,女) Ethan(晨煦,男) Chelsie(千雪,女)
- qwen3-tts-flash only (used when the effective TTS model starts with "qwen3-tts"; "qwen-tts" is mapped to
  qwen3-tts-flash, see dashscope_api.TTS_MODEL_ALIASES / BUG-002):
  男 Moon Kai Nofish Ryan "Eldric Sage" Vincent Arthur Neil Andre / 女 Momo Vivian Maia Katerina Mia Bellona
Mapping: hash(character name) → pool chosen by guessed gender → same NPC always sounds the same and never
uses the narrator voice. Extend pools with ZM_TTS_EXTRA_MALE_VOICES / ZM_TTS_EXTRA_FEMALE_VOICES.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any

NARRATOR_VOICE = os.getenv("ZM_TTS_NARRATOR_VOICE", "Serena")
BASE_FEMALE = ["Serena", "Cherry", "Chelsie"]
BASE_MALE = ["Ethan"]
QWEN3_FEMALE = ["Momo", "Vivian", "Maia", "Katerina", "Mia", "Bellona"]
QWEN3_MALE = ["Moon", "Kai", "Nofish", "Ryan", "Eldric Sage", "Vincent", "Arthur", "Neil", "Andre"]
_EXTRA_MALE = [v.strip() for v in os.getenv("ZM_TTS_EXTRA_MALE_VOICES", "").split(",") if v.strip()]
_EXTRA_FEMALE = [v.strip() for v in os.getenv("ZM_TTS_EXTRA_FEMALE_VOICES", "").split(",") if v.strip()]

# Every voice name we may ever accept as an explicit ``voice=`` argument.
ALL_VOICES = sorted({NARRATOR_VOICE, *BASE_FEMALE, *BASE_MALE, *QWEN3_FEMALE, *QWEN3_MALE,
                     *_EXTRA_MALE, *_EXTRA_FEMALE})

_FEMALE_HINTS = ("女", "她", "姑娘", "小姐", "夫人", "太太", "姐", "妹", "母", "娘", "婆", "后", "妃", "公主", "千金", "少女",
                 "阿姨", "嫂", "姑")
_MALE_HINTS = ("男", "他", "先生", "少爷", "公子", "兄", "弟", "父", "爷", "叔", "伯", "王", "将军", "老板", "掌柜", "哥")


def _model() -> str:
    try:
        from app.multimodal.dashscope_api import effective_tts_model
        return effective_tts_model()
    except Exception:  # noqa: BLE001
        return ""


def pools(model: str | None = None) -> tuple[list[str], list[str]]:
    """(female, male) voice pools supported by the configured TTS model."""
    m = model if model is not None else _model()
    try:
        from app.multimodal.dashscope_api import TTS_MODEL_ALIASES
        m = TTS_MODEL_ALIASES.get(m, m)
    except Exception:  # noqa: BLE001
        pass
    m = m.lower()
    rich = m.startswith("qwen3-tts")
    female = BASE_FEMALE + (QWEN3_FEMALE if rich else []) + _EXTRA_FEMALE
    male = BASE_MALE + (QWEN3_MALE if rich else []) + _EXTRA_MALE
    return female, male


def guess_gender(character: dict[str, Any] | None) -> str:
    if not character:
        return "unknown"
    text = f"{character.get('role', '')}{character.get('persona', '')}{character.get('name', '')}"
    f = sum(text.count(h) for h in _FEMALE_HINTS)
    m = sum(text.count(h) for h in _MALE_HINTS)
    return "female" if f > m else "male" if m > f else "unknown"


def voice_for(speaker: str | dict[str, Any] | None = None, model: str | None = None) -> str:
    """'narrator'/None → narrator voice; a voice id → itself; a character name / dict → stable NPC voice."""
    if speaker is None or speaker == "narrator" or speaker == "":
        return NARRATOR_VOICE
    if isinstance(speaker, str):
        if speaker in ALL_VOICES:
            return speaker
        speaker = {"name": speaker}  # a character name/id → cast like an NPC
    female, male = pools(model)
    g = guess_gender(speaker)
    pool = female if g == "female" else male if g == "male" else female + male
    pool = [v for v in pool if v != NARRATOR_VOICE] or pool  # NPCs never sound like the narrator
    ident = str(speaker.get("name") or speaker.get("id") or "npc")
    h = int(hashlib.md5(ident.encode()).hexdigest(), 16)
    return pool[h % len(pool)]
