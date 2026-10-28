"""启动迁移（幂等）：创建 demo 账号（u_demo），旧数据 owner_id 为空的归 demo。demo 密码绝不打印。"""
from __future__ import annotations

import logging
import secrets

from sqlalchemy import text
from sqlmodel import Session

from app.auth.context import DEMO_ID, DEMO_USERNAME
from app.config import get_settings

log = logging.getLogger("zhimeng.auth")
DEMO_NICKNAME = "演示账号"


def demo_password_file():  # noqa: ANN201
    return get_settings().data_dir / "demo_password.txt"


def _demo_password() -> tuple[str, bool]:
    """(密码, 是否来自 ZM_DEMO_PASSWORD)。缺省：读数据目录文件，没有则随机生成写入（0600）。"""
    from app.auth.security import write_secret_file

    s = get_settings()
    if s.zm_demo_password:
        return s.zm_demo_password, True
    p = demo_password_file()
    if p.exists():
        val = p.read_text(encoding="utf-8").strip()
        if val:
            return val, False
    val = secrets.token_urlsafe(15)[:20]
    write_secret_file(p, val)
    log.info("demo 账号密码已写入 %s（不在日志中显示）", p)
    return val, False


def bootstrap(engine) -> None:  # noqa: ANN001
    from app.auth.prefs import default_prefs
    from app.auth.security import hash_password, verify_password
    from app.db import UserRow

    with Session(engine) as s:
        demo = s.get(UserRow, DEMO_ID)
        if demo is None:
            pw, _ = _demo_password()
            s.add(UserRow(id=DEMO_ID, username=DEMO_USERNAME, username_lower=DEMO_USERNAME, password_hash=hash_password(pw),
                          nickname=DEMO_NICKNAME, preferences=default_prefs(), is_demo=True))
        elif get_settings().zm_demo_password and not verify_password(demo.password_hash, get_settings().zm_demo_password):
            demo.password_hash = hash_password(get_settings().zm_demo_password)  # ZM_DEMO_PASSWORD 变更 → 下次启动生效
            s.add(demo)
        s.commit()
        s.execute(text("UPDATE worlds SET owner_id = :d WHERE owner_id IS NULL OR owner_id = ''").bindparams(d=DEMO_ID))
        s.execute(text("UPDATE worlds SET origin = 'generated' WHERE origin IS NULL OR origin = ''"))
        s.commit()
