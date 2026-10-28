"use client";
/**
 * 个人中心各分区（契约 v1.4-draft2 §3.6–3.11）。每个数据区都有加载 / 空 / 错误三态。
 * 演示模式（ZM_AUTH_REQUIRED=0 且未登录）：统计、作品、学习记录、偏好按 demo 账号显示；资料与安全需要登录。
 */
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type ChangeEvent, type FormEvent, type ReactNode } from "react";
import { BookOpen, Download, ImageUp, Layers, Library, Sparkles, Trash2 } from "lucide-react";
import { api, errorText } from "@/lib/api";
import {
  LIMITS,
  authApi,
  authErrorFor,
  loginHref,
  passwordStrength,
  validateBio,
  validateEmail,
  validateNickname,
  validatePassword,
  type LearningRecord,
  type Page,
  type Preferences,
  type UserStats,
} from "@/lib/auth";
import type { Rating, WorldSummary } from "@/lib/types";
import { AVATAR_MAX_BYTES, AVATAR_TYPES, HINTS } from "@/lib/authRules";
import { mirrorPrefs, useAuth, useCooldown } from "@/hooks/useAuth";
import { usePrefs } from "@/hooks/usePrefs";
import { setCurrentWorld } from "@/hooks/useCurrentWorld";
import { AVATAR_PRESETS, Avatar, presetValue } from "@/components/Avatar";
import { AvatarCropper } from "@/components/AvatarCropper";
import { EduSummaryDialog } from "@/components/EduSummaryDialog";
import { FormField, PasswordMeter } from "@/components/FormField";
import { useToast } from "@/components/Toast";
import { downloadBlob } from "@/lib/video";

export const fmtDate = (s?: string | null) =>
  s ? new Date(s).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric", year: "numeric" }) : "—";

type Load<T> = { state: "loading" } | { state: "ok"; data: T } | { state: "error"; message: string };

/** Load once on mount (and on demand). */
function useLoad<T>(fn: () => Promise<T>) {
  const [s, setS] = useState<Load<T>>({ state: "loading" });
  const ref = useRef(fn);
  useEffect(() => {
    ref.current = fn;
  });
  const run = useCallback(
    () =>
      ref.current().then(
        (data) => setS({ state: "ok", data }),
        (e) => setS({ state: "error", message: errorText(e) }),
      ),
    [],
  );
  const load = useCallback(() => {
    setS({ state: "loading" });
    void run();
  }, [run]);
  useEffect(() => {
    void run(); // initial state is already "loading"
  }, [run]);
  return [s, load, setS] as const;
}

function ErrorBox({ message, onRetry, testId }: { message: string; onRetry: () => void; testId: string }) {
  return (
    <div className="notice warn row" role="alert" data-testid={testId}>
      <span style={{ flex: 1 }}>{message}</span>
      <button type="button" className="btn sm ghost" onClick={onRetry}>
        重试
      </button>
    </div>
  );
}

function Skel({ n = 2, h = 64, testId }: { n?: number; h?: number; testId: string }) {
  return (
    <div className="stack" aria-busy data-testid={testId}>
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="skel" style={{ height: h }} />
      ))}
    </div>
  );
}

/**
 * Shown in place of account-only sections (profile, password, avatar) while browsing as the demo account —
 * these always need a real login (contract §6), so the user is guided before submitting anything.
 */
function LoginNeeded({ what, tab }: { what: string; tab: string }) {
  const next = `/me?tab=${tab}`;
  return (
    <div className="empty small" data-testid="me-login-required">
      <p>
        当前为演示账号，{what}需要登录自己的账号。
      </p>
      <div className="row" style={{ justifyContent: "center" }}>
        <Link href={loginHref(next)} className="btn sm" data-testid="me-login-required-login">
          登录
        </Link>
        <Link href={`/register?next=${encodeURIComponent(next)}`} className="btn sm ghost">
          注册新账号
        </Link>
      </div>
    </div>
  );
}

/* ================= 概览 ================= */
function StatCard({ k, n, label, sub, icon }: { k: string; n: number; label: string; sub?: string; icon?: ReactNode }) {
  return (
    <div className="stat-card" data-testid={`stat-card-${k}`}>
      <div className="stat-label">
        {icon}
        {label}
      </div>
      <div className="stat-num">{n.toLocaleString("zh-CN")}</div>
      {sub ? <div className="faint stat-sub">{sub}</div> : null}
    </div>
  );
}

export function OverviewPanel({ onGo }: { onGo: (tab: string) => void }) {
  const [s, reload] = useLoad<UserStats>(() => authApi.stats());
  if (s.state === "loading")
    return (
      <div className="stat-grid" aria-busy data-testid="stats-loading">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="stat-card stat-skel skel" />
        ))}
      </div>
    );
  if (s.state === "error") return <ErrorBox message={s.message} onRetry={reload} testId="stats-error" />;
  const d = s.data;
  const recent = d.recent_worlds ?? [];
  return (
    <div className="stack">
      <div className="stat-grid" data-testid="stats">
        <StatCard
          k="worlds"
          n={d.worlds.total}
          label="世界"
          icon={<Library size={14} aria-hidden />}
          sub={`故事 ${d.worlds.story} · 学习 ${d.worlds.education}${d.worlds.draft ? ` · 草稿 ${d.worlds.draft}` : ""}`}
        />
        <StatCard
          k="saves"
          n={d.saves.slots}
          label="存档"
          icon={<Layers size={14} aria-hidden />}
          sub={d.saves.imported ? `其中导入 ${d.saves.imported} 个` : "每个世界自动存档"}
        />
        <StatCard
          k="turns"
          n={d.play.turns}
          label="回合"
          icon={<Sparkles size={14} aria-hidden />}
          sub={`共 ${d.play.chapters} 章 · 插入事件 ${d.play.injected_events} 次`}
        />
        <StatCard
          k="memories"
          n={d.play.memories}
          label="角色记忆"
          sub={`幕后事件 ${d.play.offscreen_events} 条`}
        />
        <StatCard
          k="cards"
          n={d.learning.knowledge_cards}
          label="知识卡"
          icon={<BookOpen size={14} aria-hidden />}
          sub={`学习世界 ${d.learning.worlds} 个 · 小结 ${d.learning.summaries} 份`}
        />
        <StatCard k="assets" n={d.assets.image + d.assets.audio} label="插画与配音" sub={`插画 ${d.assets.image} · 配音 ${d.assets.audio}`} />
      </div>
      {d.play.last_played_at ? (
        <p className="faint" style={{ margin: 0, fontSize: 13 }} data-testid="stats-played">
          {d.play.first_played_at ? `${fmtDate(d.play.first_played_at)} 开始织梦，` : ""}最近一次游玩：
          {fmtDate(d.play.last_played_at)}
        </p>
      ) : null}

      <section className="stack" data-testid="overview-recent">
        <div className="row">
          <h2 className="h2" style={{ margin: 0, flex: 1 }}>
            最近的世界
          </h2>
          <button type="button" className="linkish" onClick={() => onGo("works")}>
            全部作品 →
          </button>
        </div>
        {recent.length ? (
          <div className="work-list">
            {recent.map((w) => (
              <WorkItem key={w.id} w={w} compact />
            ))}
          </div>
        ) : (
          <EmptyWorks />
        )}
      </section>

      {d.learning.latest ? (
        <section className="stack" data-testid="overview-learning">
          <div className="row">
            <h2 className="h2" style={{ margin: 0, flex: 1 }}>
              最近的学习
            </h2>
            <button type="button" className="linkish" onClick={() => onGo("learning")}>
              学习记录 →
            </button>
          </div>
          <LearnItem r={d.learning.latest} />
        </section>
      ) : null}
    </div>
  );
}

function EmptyWorks() {
  return (
    <div className="empty small" data-testid="works-empty">
      <p>还没有作品。写一句开场，织出你的第一个世界吧。</p>
      <Link href="/" className="btn sm">
        去开局
      </Link>
    </div>
  );
}

/* ================= 个人资料 ================= */

export function ProfilePanel() {
  const { user } = useAuth();
  if (!user || user.is_demo) return <LoginNeeded what="修改资料和上传头像" tab="profile" />;
  return (
    <div className="stack form-narrow">
      <AvatarSection />
      <ProfileForm key={user.updated_at} />
      <EmailForm key={`e-${user.email ?? ""}`} />
    </div>
  );
}

function AvatarSection() {
  const { user, setUser } = useAuth();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  if (!user) return null;

  const pick = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    setErr(null);
    if (!f) return;
    if (!(AVATAR_TYPES as readonly string[]).includes(f.type)) return setErr("头像仅支持 PNG、JPG 或 WebP 图片");
    // the cropped upload is small; the original just has to be something a browser can decode
    if (f.size > 20 * 1024 * 1024) return setErr("图片太大了，请选择 20MB 以内的图片");
    setFile(f);
  };
  const upload = async (blob: Blob, name: string) => {
    if (blob.size > AVATAR_MAX_BYTES) return setErr("裁剪后的头像仍超过 2MB，请换一张图片");
    setBusy(true);
    try {
      setUser(await authApi.uploadAvatar(blob, name));
      setFile(null);
      toast("头像已更新");
    } catch (e) {
      setErr(authErrorFor(e).message);
      setFile(null);
    } finally {
      setBusy(false);
    }
  };
  const isPreset = !!user.avatar_url?.startsWith("preset:");
  const choosePreset = async (key: string) => {
    setBusy(true);
    setErr(null);
    try {
      setUser(await authApi.updateProfile({ avatar_url: presetValue(key) }));
      toast("头像已更新");
    } catch (e) {
      setErr(authErrorFor(e).message);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    setBusy(true);
    setErr(null);
    try {
      // presets are a profile field; uploaded files have their own DELETE (which also removes the file)
      setUser(isPreset ? await authApi.updateProfile({ avatar_url: null }) : await authApi.deleteAvatar());
      toast("已恢复默认头像");
    } catch (e) {
      setErr(authErrorFor(e).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card flat stack" data-testid="profile-avatar-section">
      <span className="label">头像</span>
      <div className="avatar-row">
        <Avatar src={user.avatar_url} name={user.nickname} size={72} testId="profile-avatar" />
        <div className="stack" style={{ gap: 8 }}>
          <div className="row">
            <button
              type="button"
              className="btn sm"
              disabled={busy}
              onClick={() => input.current?.click()}
              data-testid="profile-avatar-upload"
            >
              <ImageUp size={14} aria-hidden /> {user.avatar_url ? "更换头像" : "上传头像"}
            </button>
            {user.avatar_url ? (
              <button
                type="button"
                className="btn sm ghost"
                disabled={busy}
                onClick={() => void remove()}
                data-testid="profile-avatar-remove"
              >
                <Trash2 size={14} aria-hidden /> 恢复默认
              </button>
            ) : null}
          </div>
          <span className="faint" style={{ fontSize: 12 }}>
            {HINTS.avatar}
          </span>
        </div>
      </div>
      <div className="avatar-picks" role="radiogroup" aria-label="预设头像" data-testid="profile-avatar-presets">
        {AVATAR_PRESETS.map((p) => {
          const on = user.avatar_url === presetValue(p.key);
          return (
            <button
              key={p.key}
              type="button"
              role="radio"
              aria-checked={on}
              aria-label={`预设头像：${p.label}`}
              title={p.label}
              className={`avatar-pick${on ? " on" : ""}`}
              disabled={busy}
              data-testid={`avatar-preset-${p.key}`}
              onClick={() => void choosePreset(p.key)}
            >
              <Avatar src={presetValue(p.key)} name={p.glyph} size={40} />
            </button>
          );
        })}
        <input
          ref={input}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          hidden
          onChange={pick}
          data-testid="profile-avatar-input"
        />
      </div>
      {err ? (
        <div className="field-error" role="alert" data-testid="profile-avatar-error">
          {err}
        </div>
      ) : null}
      {file ? <AvatarCropper file={file} busy={busy} onCancel={() => setFile(null)} onDone={(b, n) => void upload(b, n)} /> : null}
    </section>
  );
}

function ProfileForm() {
  const { user, setUser } = useAuth();
  const toast = useToast();
  const [nickname, setNickname] = useState(user?.nickname ?? "");
  const [bio, setBio] = useState(user?.bio ?? "");
  const [errs, setErrs] = useState<{ nickname?: string | null; bio?: string | null }>({});
  const [formErr, setFormErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!user) return null;
  const dirty = nickname.trim() !== user.nickname || bio !== (user.bio ?? "");

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setFormErr(null);
    const e = { nickname: validateNickname(nickname), bio: validateBio(bio) };
    setErrs(e);
    if (e.nickname || e.bio) return;
    setBusy(true);
    try {
      const patch: { nickname?: string; bio?: string } = {};
      if (nickname.trim() !== user.nickname) patch.nickname = nickname.trim();
      if (bio !== (user.bio ?? "")) patch.bio = bio.trim();
      setUser(await authApi.updateProfile(patch));
      toast("资料已保存");
    } catch (err) {
      const { field, message } = authErrorFor(err);
      if (field === "nickname" || field === "bio") setErrs((x) => ({ ...x, [field]: message }));
      else setFormErr(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="card flat stack" onSubmit={submit} noValidate data-testid="profile-form">
      {formErr ? (
        <div className="notice warn" role="alert" data-testid="profile-error">
          {formErr}
        </div>
      ) : null}
      <FormField
        label="昵称"
        testId="profile-nickname"
        value={nickname}
        maxLength={40}
        error={errs.nickname}
        hint={HINTS.nickname}
        onValue={(v) => {
          setNickname(v);
          if (errs.nickname) setErrs((x) => ({ ...x, nickname: validateNickname(v) }));
        }}
      />
      <FormField
        label="个人简介"
        testId="profile-bio"
        multiline
        rows={3}
        value={bio}
        error={errs.bio}
        hint={`${[...bio].length} / ${LIMITS.bio}`}
        placeholder="喜欢什么样的故事？"
        onValue={(v) => {
          setBio(v);
          setErrs((x) => ({ ...x, bio: validateBio(v) }));
        }}
      />
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button type="submit" className="btn" disabled={busy || !dirty} data-testid="profile-save">
          {busy ? "正在保存…" : "保存资料"}
        </button>
      </div>
    </form>
  );
}

function EmailForm() {
  const { user, setUser } = useAuth();
  const toast = useToast();
  const [email, setEmail] = useState(user?.email ?? "");
  const [pw, setPw] = useState("");
  const [errs, setErrs] = useState<{ email?: string | null; current_password?: string | null }>({});
  const [formErr, setFormErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const cool = useCooldown();
  if (!user) return null;
  const next = email.trim().toLowerCase();
  const dirty = next !== (user.email ?? "");

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setFormErr(null);
    const e = { email: validateEmail(email), current_password: pw ? null : "修改邮箱需要输入当前密码" };
    setErrs(e);
    if (e.email || e.current_password) return;
    setBusy(true);
    try {
      setUser(await authApi.updateProfile({ email: next || null, current_password: pw }));
      setPw("");
      toast(next ? "邮箱已更新" : "已解除邮箱");
    } catch (err) {
      const { field, message, retryAfter } = authErrorFor(err);
      if (retryAfter) cool.start(retryAfter);
      if (field === "email" || field === "current_password") setErrs((x) => ({ ...x, [field]: message }));
      else setFormErr(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="card flat stack" onSubmit={submit} noValidate data-testid="email-form">
      <span className="label">登录邮箱</span>
      {formErr ? (
        <div className="notice warn" role="alert" data-testid="email-error">
          {formErr}
        </div>
      ) : null}
      <FormField
        label="邮箱"
        testId="profile-email"
        type="email"
        autoComplete="email"
        value={email}
        error={errs.email}
        hint={user.email ? "清空后保存即解除邮箱" : "绑定后可以用邮箱登录"}
        onValue={(v) => {
          setEmail(v);
          if (errs.email) setErrs((x) => ({ ...x, email: null }));
        }}
      />
      {dirty ? (
        <FormField
          label="当前密码"
          testId="profile-email-password"
          type="password"
          autoComplete="current-password"
          value={pw}
          error={errs.current_password}
          onValue={(v) => {
            setPw(v);
            if (errs.current_password) setErrs((x) => ({ ...x, current_password: null }));
          }}
        />
      ) : null}
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button type="submit" className="btn ghost" disabled={busy || !dirty || cool.left > 0} data-testid="profile-email-save">
          {cool.left ? `请 ${cool.left} 秒后再试` : busy ? "正在保存…" : next ? "保存邮箱" : "解除邮箱"}
        </button>
      </div>
    </form>
  );
}

/* ================= 账号安全 ================= */
export function SecurityPanel() {
  const { user, logout } = useAuth();
  const toast = useToast();
  const [v, setV] = useState({ current: "", next: "", confirm: "" });
  const [errs, setErrs] = useState<{ current?: string | null; next?: string | null; confirm?: string | null }>({});
  const [formErr, setFormErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const cool = useCooldown();
  if (!user || user.is_demo) return <LoginNeeded what="修改密码" tab="security" />;

  const check = (all = v) => ({
    current: all.current ? null : "请输入当前密码",
    next:
      validatePassword(all.next, user.username, user.email ?? "") ??
      (all.next && all.next === all.current ? "新密码不能与当前密码相同" : null),
    confirm: !all.confirm ? "请再次输入新密码" : all.confirm === all.next ? null : "两次输入的新密码不一致",
  });
  const set = (k: keyof typeof v) => (val: string) => {
    const nv = { ...v, [k]: val };
    setV(nv);
    setDone(false);
    if (errs[k] || (k === "next" && errs.confirm)) {
      const c = check(nv);
      setErrs((x) => ({ ...x, [k]: c[k], ...(k === "next" && x.confirm ? { confirm: c.confirm } : {}) }));
    }
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (cool.left) return;
    setFormErr(null);
    const e = check();
    setErrs(e);
    if (e.current || e.next || e.confirm) return;
    setBusy(true);
    try {
      await authApi.changePassword({ current_password: v.current, new_password: v.next }); // 204
      setV({ current: "", next: "", confirm: "" });
      setDone(true);
      toast("密码已修改");
    } catch (err) {
      const { field, message, retryAfter } = authErrorFor(err, { current_password: "current", new_password: "next", password: "next" });
      if (retryAfter) cool.start(retryAfter);
      if (field === "current" || field === "next") setErrs((x) => ({ ...x, [field]: message }));
      else setFormErr(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack form-narrow">
      <form className="card flat stack" onSubmit={submit} noValidate data-testid="password-form">
        <h2 className="h2" style={{ margin: 0 }}>
          修改密码
        </h2>
        {done ? (
          <div className="notice info" role="status" data-testid="password-done">
            密码已修改。其他设备上的登录已失效，本设备保持登录。
          </div>
        ) : null}
        {formErr ? (
          <div className="notice warn" role="alert" data-testid="password-error">
            {formErr}
            {cool.left ? <span data-testid="password-cooldown">（{cool.left} 秒后可重试）</span> : null}
          </div>
        ) : null}
        <FormField
          label="当前密码"
          testId="password-current"
          type="password"
          autoComplete="current-password"
          value={v.current}
          error={errs.current}
          onValue={set("current")}
        />
        <FormField
          label="新密码"
          testId="password-new"
          type="password"
          autoComplete="new-password"
          value={v.next}
          error={errs.next}
          hint={
            <>
              <span>{HINTS.password}</span>
              <PasswordMeter score={passwordStrength(v.next)} />
            </>
          }
          onValue={set("next")}
        />
        <FormField
          label="确认新密码"
          testId="password-confirm"
          type="password"
          autoComplete="new-password"
          value={v.confirm}
          error={errs.confirm}
          onValue={set("confirm")}
        />
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="submit" className="btn" disabled={busy || cool.left > 0} data-testid="password-submit">
            {cool.left ? `请 ${cool.left} 秒后再试` : busy ? "正在修改…" : "修改密码"}
          </button>
        </div>
      </form>

      <div className="card flat stack" data-testid="security-account">
        <h2 className="h2" style={{ margin: 0 }}>
          登录信息
        </h2>
        <dl className="kv">
          <dt>用户名</dt>
          <dd>@{user.username}</dd>
          <dt>邮箱</dt>
          <dd>{user.email ?? "未绑定"}</dd>
          <dt>注册时间</dt>
          <dd>{fmtDate(user.created_at)}</dd>
          <dt>上次登录</dt>
          <dd>{fmtDate(user.last_login_at)}</dd>
        </dl>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button
            type="button"
            className="btn ghost"
            data-testid="security-logout"
            onClick={() => void logout().then(() => toast("已退出登录"))}
          >
            退出登录
          </button>
        </div>
      </div>
    </div>
  );
}

/* ================= 我的作品（世界 / 故事 / 存档） ================= */
const FILTERS = [
  { key: "all", label: "全部" },
  { key: "story", label: "故事" },
  { key: "education", label: "学习" },
  { key: "active", label: "进行中" },
  { key: "ended", label: "已完结" },
] as const;

function WorkItem({ w, compact }: { w: WorldSummary & { origin?: string }; compact?: boolean }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const exportOne = async () => {
    setBusy(true);
    try {
      const s = await api.exportSave(w.id);
      downloadBlob(new Blob([JSON.stringify(s, null, 2)], { type: "application/json" }), `织梦存档-${w.title}.json`);
      toast("存档已导出");
    } catch (e) {
      toast(`导出失败：${errorText(e)}`);
    } finally {
      setBusy(false);
    }
  };
  const href = w.status === "draft" ? `/preview/${w.id}` : `/play/${w.id}`;
  return (
    <article className="work-item" data-testid="work-item" data-mode={w.mode}>
      <div className="work-main">
        <div className="row" style={{ gap: 6 }}>
          <strong className="ellipsis">{w.title}</strong>
          {w.mode === "education" ? <span className="tag jade">学习</span> : <span className="tag gold">故事</span>}
          {w.status === "draft" ? <span className="tag">草稿</span> : null}
          {w.status === "ended" ? <span className="tag">已完结</span> : null}
          {w.origin === "imported" ? <span className="tag">导入</span> : null}
        </div>
        <div className="faint" style={{ fontSize: 12 }}>
          {[w.genre, w.tone].filter(Boolean).join(" · ")}
          {w.genre || w.tone ? " · " : ""}第 {w.turn || 0} 回合 · 更新于 {fmtDate(w.updated_at)}
        </div>
      </div>
      <div className="row work-actions">
        <Link href={href} className="btn sm" data-testid="work-continue" onClick={() => setCurrentWorld(w.id)}>
          {w.status === "draft" ? "查看预览" : w.status === "ended" ? "回看" : "继续"}
        </Link>
        {!compact ? (
          <button
            type="button"
            className="icon-btn"
            aria-label={`导出《${w.title}》存档`}
            title="导出存档"
            disabled={busy}
            data-testid="work-export"
            onClick={() => void exportOne()}
          >
            <Download size={14} aria-hidden />
          </button>
        ) : null}
      </div>
    </article>
  );
}

export function WorksPanel() {
  const [worlds, reload] = useLoad<WorldSummary[]>(() => authApi.worlds().then((d) => (Array.isArray(d) ? d : [])));
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const all = worlds.state === "ok" ? worlds.data : [];
  const list = [...all]
    .filter((w) =>
      filter === "all"
        ? true
        : filter === "active" || filter === "ended"
          ? w.status === filter
          : filter === "education"
            ? w.mode === "education"
            : w.mode !== "education",
    )
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  return (
    <div className="stack">
      <div className="row wrap">
        <div className="chips" role="group" aria-label="筛选作品" style={{ flex: 1 }}>
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              className={`chip${filter === f.key ? " on" : ""}`}
              aria-pressed={filter === f.key}
              data-testid={`works-filter-${f.key}`}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
              {worlds.state === "ok" && f.key === "all" ? ` ${all.length}` : ""}
            </button>
          ))}
        </div>
        <Link href="/saves" className="btn sm ghost">
          存档管理（导入 / 删除）
        </Link>
      </div>
      {worlds.state === "loading" ? <Skel testId="works-loading" /> : null}
      {worlds.state === "error" ? <ErrorBox message={worlds.message} onRetry={reload} testId="works-error" /> : null}
      {worlds.state === "ok" && !all.length ? <EmptyWorks /> : null}
      {worlds.state === "ok" && all.length && !list.length ? (
        <p className="faint" data-testid="works-filter-empty">
          这个分类下还没有作品。
        </p>
      ) : null}
      <div className="work-list" data-testid="works-list">
        {list.map((w) => (
          <WorkItem key={w.id} w={w} />
        ))}
      </div>
    </div>
  );
}

/* ================= 学习记录 ================= */
const STATUS_TEXT: Record<string, string> = { draft: "未开始", active: "学习中", ended: "已完成" };

function LearnItem({ r, onSummary }: { r: LearningRecord; onSummary?: (id: string) => void }) {
  return (
    <article className="learn-item" data-testid="learning-item">
      <div className="learn-main">
        <div className="row" style={{ gap: 6 }}>
          <strong className="ellipsis">{r.title}</strong>
          {r.subject ? <span className="tag jade">{r.subject}</span> : null}
          {r.grade ? <span className="tag">{r.grade}</span> : null}
          <span className="tag">{STATUS_TEXT[r.status] ?? r.status}</span>
        </div>
        <div className="faint" style={{ fontSize: 12 }}>
          探索 {r.turns} 回合 · 知识卡 {r.cards} 张 · 更新于 {fmtDate(r.updated_at)}
        </div>
        {r.summary ? (
          <div className="learn-summary" data-testid="learning-summary">
            {r.summary.key_points.length ? (
              <ul>
                {r.summary.key_points.slice(0, 3).map((k, i) => (
                  <li key={i}>{k}</li>
                ))}
              </ul>
            ) : null}
            {r.summary.reflection ? <p className="muted">{r.summary.reflection}</p> : null}
          </div>
        ) : null}
      </div>
      <div className="row work-actions">
        <Link href={`/play/${r.world_id}`} className="btn sm ghost" onClick={() => setCurrentWorld(r.world_id)}>
          继续学习
        </Link>
        {onSummary && r.turns > 0 ? (
          <button type="button" className="btn sm ghost" data-testid="learning-summary-btn" onClick={() => onSummary(r.world_id)}>
            {r.summary ? "查看小结" : "生成学习小结"}
          </button>
        ) : null}
      </div>
    </article>
  );
}

const PAGE = 20;
export function LearningPanel() {
  const [s, reload, setS] = useLoad<Page<LearningRecord>>(() => authApi.learning(PAGE, 0));
  const [more, setMore] = useState<"idle" | "loading" | string>("idle");
  const [summary, setSummary] = useState<string | null>(null);

  const loadMore = async () => {
    if (s.state !== "ok") return;
    setMore("loading");
    try {
      const p = await authApi.learning(PAGE, s.data.items.length);
      setS({ state: "ok", data: { ...p, items: [...s.data.items, ...p.items] } });
      setMore("idle");
    } catch (e) {
      setMore(errorText(e));
    }
  };

  if (s.state === "loading") return <Skel h={84} testId="learning-loading" />;
  if (s.state === "error") return <ErrorBox message={s.message} onRetry={reload} testId="learning-error" />;
  const { items, total } = s.data;
  if (!items.length)
    return (
      <div className="empty small" data-testid="learning-empty">
        <p>还没有学习记录。把一篇课文或一段史料变成可以走进去的世界吧。</p>
        <Link href="/education" className="btn sm">
          去教育模式
        </Link>
      </div>
    );
  const cards = items.reduce((n, r) => n + r.cards, 0);
  return (
    <div className="stack">
      <p className="muted" style={{ margin: 0 }} data-testid="learning-total">
        共 {total} 个学习世界{items.length < total ? `（已显示 ${items.length} 个）` : ""}，解锁 {cards} 张知识卡。
      </p>
      <div className="learn-list" data-testid="learning-list">
        {items.map((r) => (
          <LearnItem key={r.world_id} r={r} onSummary={setSummary} />
        ))}
      </div>
      {items.length < total ? (
        <div className="row" style={{ justifyContent: "center" }}>
          <button
            type="button"
            className="btn sm ghost"
            disabled={more === "loading"}
            onClick={() => void loadMore()}
            data-testid="learning-more"
          >
            {more === "loading" ? "加载中…" : "加载更多"}
          </button>
        </div>
      ) : null}
      {more !== "idle" && more !== "loading" ? (
        <p className="field-error" role="alert">
          {more}
        </p>
      ) : null}
      {summary ? (
        <EduSummaryDialog
          worldId={summary}
          onClose={() => {
            setSummary(null);
            reload(); // the summary is persisted server-side once complete
          }}
        />
      ) : null}
    </div>
  );
}

/* ================= 偏好设置 ================= */
type PrefsPatch = Parameters<typeof authApi.patchPreferences>[0];
const RATINGS: { key: Rating; label: string }[] = [
  { key: "all", label: "全年龄" },
  { key: "teen", label: "青少年" },
  { key: "mature", label: "成人" },
];

export function PrefsPanel() {
  const { user, setUser } = useAuth();
  const [s, reload, setS] = useLoad<Preferences>(() => authApi.getPreferences());
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [askPw, setAskPw] = useState(false);
  const [pw, setPw] = useState("");
  const [pwErr, setPwErr] = useState<string | null>(null);

  const save = async (patch: PrefsPatch): Promise<boolean> => {
    if (s.state !== "ok") return false;
    const prev = s.data;
    const { current_password: _pw, ...visible } = patch;
    void _pw;
    // optimistic, rolled back on failure
    setS({
      state: "ok",
      data: { ...prev, ...visible, education: { ...prev.education, ...(visible.education ?? {}) } } as Preferences,
    });
    setSaving(true);
    setErr(null);
    try {
      const p = await authApi.patchPreferences(patch);
      setS({ state: "ok", data: p });
      mirrorPrefs(p);
      if (user) setUser({ ...user, preferences: p });
      return true;
    } catch (e) {
      setS({ state: "ok", data: prev });
      const { message } = authErrorFor(e);
      if (patch.current_password !== undefined) setPwErr(message);
      else setErr(message);
      return false;
    } finally {
      setSaving(false);
    }
  };

  const toggleMinor = (on: boolean) => {
    if (on) return void save({ minor_mode: true, rating: "all" });
    // turning it off is the parent's decision: needs the account password
    setPwErr(null);
    setPw("");
    setAskPw(true);
  };
  const confirmOff = async (ev: FormEvent) => {
    ev.preventDefault();
    if (!pw) return setPwErr("请输入账号密码");
    if (await save({ minor_mode: false, current_password: pw })) {
      setAskPw(false);
      setPw("");
    }
  };

  return (
    <div className="stack form-narrow">
      <section className="card flat stack" data-testid="prefs-account">
        <div className="row">
          <h2 className="h2" style={{ margin: 0, flex: 1 }}>
            账号偏好
          </h2>
          <span className="faint" style={{ fontSize: 12 }} role="status" data-testid="prefs-sync">
            {s.state === "loading" ? "正在读取…" : saving ? "正在保存…" : s.state === "ok" ? "已保存到账号，换设备也会沿用" : ""}
          </span>
        </div>
        {!user ? (
          <p className="faint" style={{ margin: 0, fontSize: 13 }} data-testid="prefs-demo">
            当前为演示账号，偏好保存在演示账号下；登录后可保存到你自己的账号。
          </p>
        ) : null}
        {s.state === "loading" ? <Skel n={3} h={28} testId="prefs-loading" /> : null}
        {s.state === "error" ? <ErrorBox message={s.message} onRetry={reload} testId="prefs-load-error" /> : null}
        {err ? (
          <div className="notice warn" role="alert" data-testid="prefs-error">
            {err}
          </div>
        ) : null}
        {s.state === "ok" ? (
          <>
            <label className="switch">
              <input
                type="checkbox"
                data-testid="prefs-minor-mode"
                checked={s.data.minor_mode}
                disabled={saving}
                onChange={(e) => toggleMinor(e.target.checked)}
              />
              未成年人模式（只生成全年龄内容；关闭需要输入账号密码）
            </label>
            {askPw ? (
              <form className="notice stack" onSubmit={confirmOff} noValidate data-testid="prefs-minor-confirm">
                <span>关闭未成年人模式需要家长确认，请输入账号密码。</span>
                <FormField
                  label="账号密码"
                  testId="prefs-minor-password"
                  type="password"
                  autoComplete="current-password"
                  value={pw}
                  error={pwErr}
                  onValue={(v) => {
                    setPw(v);
                    setPwErr(null);
                  }}
                />
                <div className="row" style={{ justifyContent: "flex-end" }}>
                  <button type="button" className="btn sm ghost" onClick={() => setAskPw(false)} data-testid="prefs-minor-cancel">
                    取消
                  </button>
                  <button type="submit" className="btn sm" disabled={saving} data-testid="prefs-minor-submit">
                    确认关闭
                  </button>
                </div>
              </form>
            ) : null}
            <div className="form-field">
              <span className="label">内容分级</span>
              <div className="chips" role="radiogroup" aria-label="内容分级">
                {RATINGS.map((r) => (
                  <button
                    key={r.key}
                    type="button"
                    role="radio"
                    aria-checked={s.data.rating === r.key}
                    className={`chip${s.data.rating === r.key ? " on" : ""}`}
                    disabled={saving || (s.data.minor_mode && r.key !== "all")}
                    data-testid={`prefs-rating-${r.key}`}
                    onClick={() => void save({ rating: r.key })}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
              {s.data.minor_mode ? <span className="field-hint">未成年人模式下固定为全年龄</span> : null}
            </div>
            <label className="switch">
              <input
                type="checkbox"
                data-testid="prefs-tts"
                checked={s.data.tts_enabled}
                disabled={saving}
                onChange={(e) => void save({ tts_enabled: e.target.checked })}
              />
              为关键场景配音
            </label>
            <label className="switch">
              <input
                type="checkbox"
                data-testid="prefs-autoplay"
                checked={s.data.autoplay_audio}
                disabled={saving || !s.data.tts_enabled}
                onChange={(e) => void save({ autoplay_audio: e.target.checked })}
              />
              配音生成后自动播放
            </label>
            <label className="switch">
              <input
                type="checkbox"
                data-testid="prefs-god-view"
                checked={s.data.show_god_view}
                disabled={saving}
                onChange={(e) => void save({ show_god_view: e.target.checked })}
              />
              在导航中显示「上帝视角」
            </label>
            <label className="switch">
              <input
                type="checkbox"
                data-testid="prefs-auto-summary"
                checked={s.data.education.auto_summary}
                disabled={saving}
                onChange={(e) => void save({ education: { auto_summary: e.target.checked } })}
              />
              学习世界结束时自动整理学习小结
            </label>
            <EduDefaults
              grade={s.data.education.grade}
              subject={s.data.education.subject}
              disabled={saving}
              onSave={(education) => void save({ education })}
            />
          </>
        ) : null}
      </section>
      <DevicePrefs />
    </div>
  );
}

function EduDefaults({
  grade,
  subject,
  disabled,
  onSave,
}: {
  grade: string | null;
  subject: string | null;
  disabled: boolean;
  onSave: (e: { grade: string | null; subject: string | null }) => void;
}) {
  const [g, setG] = useState(grade ?? "");
  const [sub, setSub] = useState(subject ?? "");
  const dirty = g.trim() !== (grade ?? "") || sub.trim() !== (subject ?? "");
  return (
    <div className="row wrap edu-defaults" style={{ alignItems: "flex-end" }}>
      <FormField label="默认年级" testId="prefs-grade" value={g} maxLength={20} placeholder="如：初二" onValue={setG} />
      <FormField label="默认学科" testId="prefs-subject" value={sub} maxLength={20} placeholder="如：语文" onValue={setSub} />
      <button
        type="button"
        className="btn sm ghost"
        disabled={disabled || !dirty}
        data-testid="prefs-edu-save"
        onClick={() => onSave({ grade: g.trim() || null, subject: sub.trim() || null })}
      >
        保存
      </button>
    </div>
  );
}

/** Display settings stay on this device (they depend on the screen, not the account). */
function DevicePrefs() {
  const [prefs, setPrefs] = usePrefs();
  return (
    <section className="card flat stack" data-testid="prefs-device">
      <div className="row">
        <h2 className="h2" style={{ margin: 0, flex: 1 }}>
          本机显示
        </h2>
        <span className="faint" style={{ fontSize: 12 }}>
          仅对这台设备生效
        </span>
      </div>
      <div className="form-field">
        <span className="label">主题</span>
        <div className="chips" role="radiogroup" aria-label="主题">
          {(
            [
              ["light", "宣纸（浅色）"],
              ["dark", "夜织（深色）"],
              ["system", "跟随系统"],
            ] as const
          ).map(([k, l]) => (
            <button
              key={k}
              type="button"
              role="radio"
              aria-checked={prefs.theme === k}
              className={`chip${prefs.theme === k ? " on" : ""}`}
              data-testid={`prefs-theme-${k}`}
              onClick={() => setPrefs({ theme: k })}
            >
              {l}
            </button>
          ))}
        </div>
      </div>
      <div className="form-field">
        <span className="label">动画效果</span>
        <div className="chips" role="radiogroup" aria-label="动画效果">
          {(
            [
              ["system", "跟随系统"],
              ["on", "开启"],
              ["off", "减少动效"],
            ] as const
          ).map(([k, l]) => (
            <button
              key={k}
              type="button"
              role="radio"
              aria-checked={prefs.reducedMotion === k}
              className={`chip${prefs.reducedMotion === k ? " on" : ""}`}
              data-testid={`prefs-motion-${k}`}
              onClick={() => setPrefs({ reducedMotion: k })}
            >
              {l}
            </button>
          ))}
        </div>
      </div>
      <label className="form-field">
        <span className="label">叙事字号 {Math.round(prefs.fontScale * 100)}%</span>
        <input
          type="range"
          min={0.85}
          max={1.3}
          step={0.05}
          value={prefs.fontScale}
          data-testid="prefs-font-scale"
          onChange={(e) => setPrefs({ fontScale: Number(e.target.value) })}
        />
      </label>
    </section>
  );
}
