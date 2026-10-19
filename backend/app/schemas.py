"""Pydantic API models (see /API.md for the contract)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AI_LABEL = "内容由AI生成"
Mode = Literal["story", "education"]
Rating = Literal["all", "teen", "mature"]


class Location(BaseModel):
    id: str
    name: str
    description: str = ""
    x: float = 50
    y: float = 50
    connections: list[str] = Field(default_factory=list)
    interactables: list[str] = Field(default_factory=list)


class Relation(BaseModel):
    target_id: str
    type: str = "相识"
    affinity: int = 0
    note: str | None = None


class Character(BaseModel):
    id: str
    name: str
    role: str = ""
    persona: str = ""
    goals: list[str] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    location_id: str | None = None
    mood: str = "平静"
    status: str = "活跃"
    is_player: bool = False
    avatar_emoji: str | None = None


class Item(BaseModel):
    id: str
    name: str
    description: str = ""
    owner_id: str | None = None
    quantity: int = 1


class KnowledgeCard(BaseModel):
    id: str
    title: str
    content: str
    source: str | None = None
    turn: int | None = None


class WorldState(BaseModel):
    turn: int = 0
    chapter: int = 1
    time: str = "第1天·清晨"
    day: int = 1
    player_location_id: str | None = None
    flags: dict[str, Any] = Field(default_factory=dict)
    hp: int = 100
    stats: dict[str, int] = Field(default_factory=dict)


class PlayerInfo(BaseModel):
    name: str = "你"
    role: str = "旅人"
    character_id: str = "player"


class Option(BaseModel):
    id: str
    text: str
    hint: str | None = None


class World(BaseModel):
    id: str
    title: str
    genre: str = ""
    tone: str = ""
    era: str = ""
    setting: str = ""
    mode: Mode = "story"
    language: str = "zh"
    premise: str = ""
    initial_conflict: str = ""
    opening_scene: str = ""
    player: PlayerInfo = Field(default_factory=PlayerInfo)
    locations: list[Location] = Field(default_factory=list)
    characters: list[Character] = Field(default_factory=list)
    items: list[Item] = Field(default_factory=list)
    knowledge_cards: list[KnowledgeCard] = Field(default_factory=list)
    opening_options: list[Option] = Field(default_factory=list)
    state: WorldState = Field(default_factory=WorldState)
    rating: Rating = "teen"
    minor_mode: bool = False
    status: Literal["draft", "active", "ended"] = "draft"
    created_at: str = ""
    updated_at: str = ""
    source: Literal["llm", "fallback"] = "fallback"
    ai_generated: bool = True
    ai_label: str = AI_LABEL

    def loc(self, loc_id: str | None) -> Location | None:
        return next((l for l in self.locations if l.id == loc_id), None)

    def char(self, char_id: str | None) -> Character | None:
        return next((c for c in self.characters if c.id == char_id), None)

    def npcs(self) -> list[Character]:
        return [c for c in self.characters if not c.is_player]


class WorldSummary(BaseModel):
    id: str
    title: str
    genre: str
    tone: str
    mode: Mode
    turn: int
    status: str
    created_at: str
    updated_at: str


class GenerateWorldRequest(BaseModel):
    prompt: str = Field("", max_length=4000)
    genre: str | None = None
    tone: str | None = None
    length: Literal["short", "medium", "long"] = "medium"
    language: str = "zh"
    mode: Mode = "story"
    source_text: str | None = Field(None, max_length=20000)
    minor_mode: bool = False
    rating: Rating = "teen"


class EducationGenerateRequest(BaseModel):
    source_text: str = Field(..., min_length=1, max_length=20000)
    title: str | None = None
    subject: str | None = None
    grade: str | None = None
    minor_mode: bool = True


class SettingsPatch(BaseModel):
    minor_mode: bool | None = None
    rating: Rating | None = None


class TurnRequest(BaseModel):
    action: str = Field(..., min_length=1, max_length=2000)
    option_id: str | None = None
    client_turn_id: str | None = None


class WorldEvent(BaseModel):
    id: str
    world_id: str
    type: str
    summary: str
    actor_ids: list[str] = Field(default_factory=list)
    location_id: str | None = None
    turn: int = 0
    chapter: int = 1
    impact: str = "low"
    timestamp: str = ""
    in_world_time: str = ""
    seen: bool = False


class Turn(BaseModel):
    id: str
    world_id: str
    index: int
    chapter: int
    action: str
    narration: str
    options: list[Option] = Field(default_factory=list)
    events: list[WorldEvent] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    key_scene: bool = False
    created_at: str = ""
    ai_generated: bool = True
    ai_label: str = AI_LABEL


class Citation(BaseModel):
    fact_id: str
    content: str
    turn: int
    chapter: int
    kind: str
    score: float
    source: str


class MemoryItem(BaseModel):
    id: str
    content: str
    kind: str
    turn: int
    chapter: int
    source: str
    created_at: str


class MemoryQuery(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(5, ge=1, le=20)


class MemoryAnswer(BaseModel):
    answer: str
    citations: list[Citation]
    ai_generated: bool = True
    ai_label: str = AI_LABEL


class Asset(BaseModel):
    id: str
    world_id: str
    type: Literal["image", "audio"]
    url: str
    turn_id: str | None = None
    prompt: str = ""
    source: str = "fallback"
    created_at: str = ""


class IllustrationRequest(BaseModel):
    turn_id: str | None = None
    prompt: str | None = None


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=600)
    voice: str | None = None
    turn_id: str | None = None


class InjectRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=1000)
    target_character_ids: list[str] = Field(default_factory=list)
    location_id: str | None = None
    impact: Literal["low", "medium", "high"] = "medium"


class SeenRequest(BaseModel):
    ids: list[str]


class SafetyCheck(BaseModel):
    text: str = Field(..., max_length=20000)
    minor_mode: bool = False


class SafetyResult(BaseModel):
    allowed: bool = True
    blocked: bool = False
    crisis: bool = False
    categories: list[str] = Field(default_factory=list)
    rating: Rating = "all"
    message: str | None = None
    filtered_text: str | None = None


class ReportRequest(BaseModel):
    world_id: str | None = None
    turn_id: str | None = None
    content: str = Field(..., min_length=1, max_length=5000)
    reason: str = Field(..., min_length=1, max_length=500)


class UIStreamRequest(BaseModel):
    focus: str | None = None
