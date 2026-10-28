"use client";
/**
 * 登录：用户名或邮箱 + 密码 + 记住我。字段级校验；服务端错误按 `field` 落到字段，否则显示在表单顶部；
 * 429 按 retry_after 倒计时并禁用提交。成功后回跳 ?next=（仅站内路径）。
 */
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { authApi, authErrorFor, safeNext } from "@/lib/auth";
import { useAuth, useCooldown } from "@/hooks/useAuth";
import { AuthCard } from "@/components/AuthCard";
import { FormField } from "@/components/FormField";
import { useToast } from "@/components/Toast";

type F = "login" | "password";

export function LoginView() {
  const router = useRouter();
  const toast = useToast();
  const params = useSearchParams();
  const next = safeNext(params?.get("next"), "/");
  const { status, user, lost, setUser } = useAuth();
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [errs, setErrs] = useState<Partial<Record<F, string | null>>>({});
  const [formErr, setFormErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const cool = useCooldown();

  // already signed in (e.g. /login opened in a second tab) → go on
  useEffect(() => {
    if (status === "authed" && user && !busy) router.replace(next);
  }, [status, user, busy, next, router]);

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (cool.left) return;
    setFormErr(null);
    const e = { login: login.trim() ? null : "请输入用户名或邮箱", password: password ? null : "请输入密码" };
    setErrs(e);
    if (e.login || e.password) {
      document.querySelector<HTMLInputElement>('[aria-invalid="true"]')?.focus();
      return;
    }
    setBusy(true);
    try {
      const u = await authApi.login({ login: login.trim(), password, remember });
      setUser(u);
      toast(`欢迎回来，${u.nickname}`);
      router.replace(next);
    } catch (err) {
      const { field, message, retryAfter } = authErrorFor(err, { username: "login", email: "login" });
      if (retryAfter) cool.start(retryAfter);
      if (field === "login" || field === "password") setErrs((x) => ({ ...x, [field]: message }));
      else setFormErr(message);
      setBusy(false);
    }
  };

  const clear = (k: F) => errs[k] && setErrs((x) => ({ ...x, [k]: null }));
  const regHref = `/register${next !== "/" ? `?next=${encodeURIComponent(next)}` : ""}`;
  return (
    <AuthCard
      title="登录织梦"
      sub="继续你的世界、存档与学习记录。"
      foot={
        <>
          还没有账号？
          <Link href={regHref} data-testid="login-to-register">
            立即注册
          </Link>
        </>
      }
    >
      <form className="stack" onSubmit={submit} noValidate data-testid="login-form">
        {lost && !formErr ? (
          <div className="notice" role="status" data-testid="login-expired">
            登录已过期，请重新登录。
          </div>
        ) : null}
        {formErr ? (
          <div className="notice warn" role="alert" data-testid="login-error">
            {formErr}
            {cool.left ? <span data-testid="login-cooldown">（{cool.left} 秒后可重试）</span> : null}
          </div>
        ) : null}
        <FormField
          label="用户名或邮箱"
          testId="login-username"
          name="login"
          autoComplete="username"
          autoFocus
          value={login}
          error={errs.login}
          onValue={(v) => {
            setLogin(v);
            clear("login");
          }}
        />
        <FormField
          label="密码"
          testId="login-password"
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          error={errs.password}
          onValue={(v) => {
            setPassword(v);
            clear("password");
          }}
        />
        <label className="check" data-testid="login-remember">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          <span>记住我（30 天内免登录）</span>
        </label>
        <button type="submit" className="btn lg" disabled={busy || cool.left > 0} data-testid="login-submit">
          {cool.left ? `请 ${cool.left} 秒后再试` : busy ? "正在登录…" : "登录"}
        </button>
      </form>
    </AuthCard>
  );
}
