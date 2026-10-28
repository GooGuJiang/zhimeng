"use client";
/**
 * 注册：用户名 / 昵称 / 邮箱（可选）/ 密码 / 确认密码。失焦即校验、提交时全量校验；服务端错误按 `field`
 * （或 username_taken 等错误码）落到对应字段；429 倒计时禁用提交。成功即已登录，回跳 next 或个人中心。
 */
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import {
  authApi,
  authErrorFor,
  passwordStrength,
  safeNext,
  validateEmail,
  validateNickname,
  validatePassword,
  validateUsername,
} from "@/lib/auth";
import { useAuth, useCooldown } from "@/hooks/useAuth";
import { HINTS } from "@/lib/authRules";
import { AuthCard } from "@/components/AuthCard";
import { FormField, PasswordMeter } from "@/components/FormField";
import { useToast } from "@/components/Toast";

type F = "username" | "nickname" | "email" | "password" | "confirm";

export function RegisterView() {
  const router = useRouter();
  const toast = useToast();
  const next = safeNext(useSearchParams()?.get("next"), "/");
  const { status, user, setUser } = useAuth();
  const [v, setV] = useState<Record<F, string>>({ username: "", nickname: "", email: "", password: "", confirm: "" });
  const [errs, setErrs] = useState<Partial<Record<F, string | null>>>({});
  const [touched, setTouched] = useState<Partial<Record<F, boolean>>>({});
  const [formErr, setFormErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const cool = useCooldown();

  useEffect(() => {
    if (status === "authed" && user && !busy) router.replace(next);
  }, [status, user, busy, next, router]);

  const validate = (k: F, all = v): string | null => {
    if (k === "username") return validateUsername(all.username);
    if (k === "nickname") return validateNickname(all.nickname);
    if (k === "email") return validateEmail(all.email);
    if (k === "password") return validatePassword(all.password, all.username, all.email);
    if (!all.confirm) return "请再次输入密码";
    return all.confirm === all.password ? null : "两次输入的密码不一致";
  };
  const set = (k: F) => (val: string) => {
    const nv = { ...v, [k]: val };
    setV(nv);
    // re-validate live once the user has left the field (and keep 确认密码 in step with 密码)
    setErrs((e) => ({
      ...e,
      ...(touched[k] ? { [k]: validate(k, nv) } : {}),
      ...(k === "password" && touched.confirm ? { confirm: validate("confirm", nv) } : {}),
    }));
  };
  const blur = (k: F) => () => {
    setTouched((t) => ({ ...t, [k]: true }));
    setErrs((e) => ({ ...e, [k]: validate(k) }));
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (cool.left) return;
    setFormErr(null);
    const keys: F[] = ["username", "nickname", "email", "password", "confirm"];
    const all = Object.fromEntries(keys.map((k) => [k, validate(k)])) as Record<F, string | null>;
    setErrs(all);
    setTouched({ username: true, nickname: true, email: true, password: true, confirm: true });
    if (keys.some((k) => all[k])) {
      document.querySelector<HTMLInputElement>('[aria-invalid="true"]')?.focus();
      return;
    }
    setBusy(true);
    try {
      const u = await authApi.register({
        username: v.username.trim(),
        nickname: v.nickname.trim(),
        password: v.password,
        ...(v.email.trim() ? { email: v.email.trim() } : {}),
      });
      setUser(u);
      toast(`注册成功，欢迎你，${u.nickname}`);
      router.replace(next === "/" ? "/me" : next);
    } catch (e) {
      const { field, message, retryAfter } = authErrorFor(e);
      if (retryAfter) cool.start(retryAfter);
      const known = (f?: string): f is F => !!f && ["username", "nickname", "email", "password"].includes(f);
      if (known(field)) {
        setErrs((x) => ({ ...x, [field]: message }));
        document.querySelector<HTMLInputElement>(`[data-testid="register-${field}"]`)?.focus();
      } else setFormErr(message);
      setBusy(false);
    }
  };

  const loginHref = `/login${next !== "/" ? `?next=${encodeURIComponent(next)}` : ""}`;
  return (
    <AuthCard
      title="注册织梦账号"
      sub="一个账号，保存你织就的每一个世界。"
      foot={
        <>
          已有账号？
          <Link href={loginHref} data-testid="register-to-login">
            去登录
          </Link>
        </>
      }
    >
      <form className="stack" onSubmit={submit} noValidate data-testid="register-form">
        {formErr ? (
          <div className="notice warn" role="alert" data-testid="register-error">
            {formErr}
            {cool.left ? <span data-testid="register-cooldown">（{cool.left} 秒后可重试）</span> : null}
          </div>
        ) : null}
        <FormField
          label="用户名"
          testId="register-username"
          name="username"
          autoComplete="username"
          autoFocus
          value={v.username}
          error={errs.username}
          hint={HINTS.username}
          onValue={set("username")}
          onBlur={blur("username")}
        />
        <FormField
          label="昵称"
          testId="register-nickname"
          name="nickname"
          autoComplete="nickname"
          value={v.nickname}
          error={errs.nickname}
          hint="展示在顶栏和个人中心，最多 20 字，之后可修改"
          onValue={set("nickname")}
          onBlur={blur("nickname")}
        />
        <FormField
          label="邮箱（可选）"
          testId="register-email"
          name="email"
          type="email"
          autoComplete="email"
          value={v.email}
          error={errs.email}
          hint={HINTS.email}
          onValue={set("email")}
          onBlur={blur("email")}
        />
        <FormField
          label="密码"
          testId="register-password"
          name="new-password"
          type="password"
          autoComplete="new-password"
          value={v.password}
          error={errs.password}
          hint={
            <>
              <span>{HINTS.password}</span>
              <PasswordMeter score={passwordStrength(v.password)} />
            </>
          }
          onValue={set("password")}
          onBlur={blur("password")}
        />
        <FormField
          label="确认密码"
          testId="register-confirm"
          name="confirm-password"
          type="password"
          autoComplete="new-password"
          value={v.confirm}
          error={errs.confirm}
          onValue={set("confirm")}
          onBlur={blur("confirm")}
        />
        <button type="submit" className="btn lg" disabled={busy || cool.left > 0} data-testid="register-submit">
          {cool.left ? `请 ${cool.left} 秒后再试` : busy ? "正在创建账号…" : "注册并登录"}
        </button>
      </form>
    </AuthCard>
  );
}
