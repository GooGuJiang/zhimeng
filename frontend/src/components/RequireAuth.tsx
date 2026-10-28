"use client";
/**
 * Route guard. Decides from the server's `auth_required` (never guesses):
 * - auth_required=true and no session → /login?next=<here> (same-site only, see safeNext)
 * - auth_required=false (demo mode) → render; pages show the demo account and ask to log in only for edits
 * - the session was lost mid-use (refresh failed) → /login?next=<here> in either mode
 * `demoOk={false}` additionally requires a real account even in demo mode (not used by default).
 */
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useAuth } from "@/hooks/useAuth";
import { loginHref } from "@/lib/auth";

export function RequireAuth({ children, demoOk = true }: { children: ReactNode; demoOk?: boolean }) {
  const { status, user, authRequired, lost, refresh } = useAuth();
  const router = useRouter();
  const path = usePathname() ?? "/";
  const qs = useSearchParams()?.toString();
  const here = qs ? `${path}?${qs}` : path;
  const mustLogin = status === "anon" && (authRequired || lost || !demoOk);
  useEffect(() => {
    if (mustLogin) router.replace(loginHref(here));
  }, [mustLogin, router, here]);

  if (user || (status === "anon" && !mustLogin)) return <>{children}</>;
  if (status === "offline")
    return (
      <div className="empty" data-testid="auth-offline">
        <h1 className="h1">暂时无法确认登录状态</h1>
        <p>服务连接异常，请检查网络后重试。</p>
        <button type="button" className="btn" onClick={() => void refresh()}>
          重试
        </button>
      </div>
    );
  return (
    <div className="stack" aria-busy data-testid="auth-checking">
      <div className="skel" style={{ height: 40, width: "30%" }} />
      <div className="skel" style={{ height: 220 }} />
    </div>
  );
}
