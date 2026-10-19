"""Central configuration. DASHSCOPE_API_KEY is read ONLY here (env var or backend/.env)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    dashscope_api_key: str | None = None  # env: DASHSCOPE_API_KEY
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_api_url: str = "https://dashscope.aliyuncs.com/api/v1"  # native API (image / tts)

    chat_model: str = "qwen-plus"
    fast_model: str = "qwen-turbo"
    skeleton_model: str = "qwen-flash"   # 世界生成第一步（≤5s 骨架预览）
    # 备用模型链（逗号分隔，按顺序切换；429/限流/连接断开/5xx/模型不可用时切到下一个）。
    # 2026-10-19 实测该 key 可用：qwen-plus / qwen-plus-latest / qwen-max / qwen-flash / qwen-turbo（qwen-max-latest、qwen3-max 404）
    chat_model_chain: str = "qwen-plus,qwen-plus-latest,qwen-max,qwen-turbo,qwen-flash"
    fast_model_chain: str = "qwen-turbo,qwen-flash,qwen-plus,qwen-plus-latest"
    skeleton_model_chain: str = "qwen-flash,qwen-turbo,qwen-plus"
    model_cooldown_s: float = 30.0       # 限流/断连后该模型冷却时间（期间优先跳过）
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024
    image_model: str = "wanx2.1-t2i-turbo"
    tts_model: str = "qwen3-tts-flash"  # qwen-tts 已 404（BUG-002）
    tts_voice: str = "Cherry"

    force_fallback: bool = False  # ZM_FORCE_FALLBACK=1 → never call remote APIs
    llm_timeout: float = 60.0
    llm_retries: int = 1

    data_dir: Path = BACKEND_DIR / "data"
    database_url: str | None = None
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    chapter_size: int = 5          # turns per chapter (summary compression boundary)
    npc_batch_every: int = 3       # non-focus NPCs advance every N turns
    stream_delay: float = 0.01     # fallback token pacing (seconds)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.dashscope_api_key) and not self.force_fallback

    @property
    def assets_dir(self) -> Path:
        return self.data_dir / "assets"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'zhimeng.db'}"


@lru_cache
def get_settings() -> Settings:
    import os

    s = Settings()
    # ZM_ prefixed overrides for local toggles

    if os.getenv("ZM_FORCE_FALLBACK", "").lower() in {"1", "true", "yes"}:
        s.force_fallback = True
    if os.getenv("ZM_DATA_DIR"):
        s.data_dir = Path(os.environ["ZM_DATA_DIR"])
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.assets_dir.mkdir(parents=True, exist_ok=True)
    return s
