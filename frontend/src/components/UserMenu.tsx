"use client";
/** Top-bar account area: 登录 / 注册 for guests, avatar + nickname dropdown (个人中心 / 退出登录) when signed in. */
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ChevronDown, LogIn, LogOut, UserRound } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { isPublicPath, safeNext } from "@/lib/auth";
import { Avatar } from "./Avatar";
import { useToast } from "./Toast";

export function UserMenu() {
  const { status, user, authRequired, logout } = useAuth();
  const path = usePathname() ?? "/";
  const router = useRouter();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (status === "loading") return <span className="user-skel skel" aria-hidden data-testid="user-menu-loading" />;

  if (!user) {
    const onAuthPage = /^\/(login|register)/.test(path);
    const next = onAuthPage ? "" : `?next=${encodeURIComponent(safeNext(path))}`;
    return (
      <div className="auth-links">
        <Link href={`/login${next}`} className="btn ghost sm" data-testid="auth-login-link">
          <LogIn size={14} aria-hidden className="hide-xs" /> 登录
        </Link>
        <Link href={`/register${next}`} className="btn sm" data-testid="auth-register-link">
          注册
        </Link>
      </div>
    );
  }

  const doLogout = async () => {
    setOpen(false);
    await logout();
    toast("已退出登录");
    // account pages make no sense signed out; when the server requires a login, only public pages do
    if (path.startsWith("/me") || (authRequired && !isPublicPath(path))) router.replace("/");
  };

  return (
    <div className="user-menu" ref={box}>
      <button
        type="button"
        className="user-btn"
        data-testid="user-menu-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`账号菜单：${user.nickname}`}
        onClick={() => setOpen((o) => !o)}
      >
        <Avatar src={user.avatar_url} name={user.nickname} size={30} testId="user-avatar" />
        <span className="user-name" data-testid="user-nickname">
          {user.nickname}
        </span>
        <ChevronDown size={14} aria-hidden className="hide-xs" />
      </button>
      {open ? (
        <div className="user-pop" role="menu" data-testid="user-menu">
          <div className="user-pop-h">
            <Avatar src={user.avatar_url} name={user.nickname} size={40} />
            <div style={{ minWidth: 0 }}>
              <strong className="ellipsis">{user.nickname}</strong>
              <div className="faint ellipsis" style={{ fontSize: 12 }}>
                @{user.username}
              </div>
            </div>
          </div>
          <Link
            href="/me"
            role="menuitem"
            className="user-pop-item"
            data-testid="user-menu-profile"
            onClick={() => setOpen(false)}
          >
            <UserRound size={15} aria-hidden /> 个人中心
          </Link>
          <button
            type="button"
            role="menuitem"
            className="user-pop-item"
            data-testid="user-menu-logout"
            onClick={() => void doLogout()}
          >
            <LogOut size={15} aria-hidden /> 退出登录
          </button>
        </div>
      ) : null}
    </div>
  );
}
