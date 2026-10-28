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
    # GET /api/reports 不带 world_id 的全量列表需要请求头 X-Admin-Token 与之一致；未设置 → 全量列表禁用
    zm_admin_token: str = ""
    # ---- 用户系统（feat/auth，API v1.4）：均可用同名大写环境变量覆盖 ----
    zm_auth_required: bool = False      # ZM_AUTH_REQUIRED=1 → 匿名访问受保护接口 401；0 → 匿名 = 演示账号 u_demo
    zm_jwt_secret: str = ""             # 缺省自动生成并持久化到 $ZM_DATA_DIR/jwt_secret（0600）
    zm_access_ttl_min: int = 30
    zm_refresh_ttl_days: int = 30
    zm_cookie_secure: bool = False
    zm_demo_password: str = ""          # 缺省随机生成并写入 $ZM_DATA_DIR/demo_password.txt（0600），绝不打印
    zm_trust_proxy: bool = True         # 兼容旧开关：0 = 完全不采信 X-Forwarded-For / X-Real-IP
    # 可信代理（逗号分隔，支持 CIDR）：只有对端在其中才采信转发头——只取 X-Forwarded-For 从右数第 ZM_PROXY_HOPS 项
    # （默认 1 = 我方代理写入的那一跳），不往左回溯；没有 XFF 时取 X-Real-IP；都没有 → 客户端 IP 未知（按 IP 的限流不生效）。
    # 不在其中的对端一律按 TCP 对端地址，客户端自带的转发头忽略。Docker：compose 默认只信任回环 + 前端容器固定 IP（ZM_FRONTEND_IP）。
    zm_trusted_proxies: str = "127.0.0.1/32,::1"
    zm_avatar_max_bytes: int = 2 * 1024 * 1024
    zm_register_per_hour: int = 10      # 同 IP 每小时注册上限（客户端 IP 未知时不生效）
    zm_register_global_per_hour: int = 200   # 全站每小时注册上限（兜底，AUTH-QA-3）
    # 只按账号计数、与 IP 无关的登录失败上限（兜底，AUTH-QA-3）：窗口内失败 N 次 → 锁定；登录成功不清零
    zm_login_account_max_fails: int = 10
    zm_login_account_window_min: int = 15
    zm_login_account_lock_min: int = 15
    # 其余限流阈值（默认值即原写死的值；窗口均为 ZM_LOGIN_WINDOW_MIN）
    zm_login_window_min: int = 15            # 下面两条按 IP 规则与改密码规则的计数窗口
    zm_login_ip_account_max_fails: int = 5   # 同 IP + 同账号：失败 N 次 → 锁
    zm_login_ip_account_lock_min: int = 5
    zm_login_ip_max_fails: int = 20          # 同 IP：失败 N 次 → 锁
    zm_login_ip_lock_min: int = 15
    zm_pwd_change_max_fails: int = 5         # 改密码时旧密码输错 N 次 → 锁
    zm_pwd_change_lock_min: int = 5
    zm_refresh_per_min: int = 60             # 每 IP 每分钟 refresh 上限
    # 可信代理时取 XFF 从右数第 N 项（N = 我方可信代理的层数；默认 1 = 只取最右边那一跳）
    zm_proxy_hops: int = 1
    # 实时回合延迟预算（首字 ≤2s 目标）：叙事前的世界/角色 Agent 与记忆向量检索超时即用本地规则，不拖慢旁白
    agent_budget_s: float = 2.0
    retrieval_budget_s: float = 1.2
    # 非流式 LLM 调用（小结/问答/抽取/测验）的总时限：超时走本地兜底，避免代理 socket hang up（BUG-007）
    sync_llm_timeout_s: float = 8.0
    # 安全审核单次调用时限：超时退回关键词/规则层
    guard_timeout_s: float = 6.0
    # 回合内关键场景插画/配音最多等待秒数，超时先发占位（status=pending），后台同 id 原地升级（体验流畅优先）
    key_scene_media_deadline_s: float = 3.0
    model_cooldown_s: float = 30.0       # 限流/断连后该模型冷却时间（期间优先跳过）
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024
    image_model: str = "wanx2.1-t2i-turbo"
    tts_model: str = "qwen3-tts-flash"  # qwen-tts 已 404（BUG-002）
    tts_voice: str = "Cherry"

    force_fallback: bool = False  # ZM_FORCE_FALLBACK=1 → never call remote APIs
    # ZM_DISABLE_IMAGE=1 → 不真实调用生图（省费；插画一律走本地占位），配音/大模型不受影响
    disable_image: bool = False
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
    def image_enabled(self) -> bool:
        return self.llm_enabled and not self.disable_image

    @property
    def assets_dir(self) -> Path:
        return self.data_dir / "assets"

    @property
    def avatars_dir(self) -> Path:
        return self.data_dir / "avatars"

    @property
    def cors_list(self) -> list[str]:
        """CORS 来源白名单（allow_credentials=True 时不允许 "*"，因此过滤掉）。"""
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip() and o.strip() != "*"]

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
    if os.getenv("ZM_DISABLE_IMAGE", "").lower() in {"1", "true", "yes"}:
        s.disable_image = True
    if os.getenv("ZM_CORS_ORIGINS"):
        s.cors_origins = os.environ["ZM_CORS_ORIGINS"]
    if os.getenv("ZM_DATA_DIR"):
        s.data_dir = Path(os.environ["ZM_DATA_DIR"])
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.assets_dir.mkdir(parents=True, exist_ok=True)
    s.avatars_dir.mkdir(parents=True, exist_ok=True)
    return s
