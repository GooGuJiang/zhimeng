"use client";
/** 个人中心：头部名片 + 标签页（概览 / 资料 / 账号安全 / 我的作品 / 学习记录 / 偏好设置），?tab= 可直达。 */
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { BarChart3, BookOpen, Library, Settings2, ShieldCheck, UserRound, type LucideIcon } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { loginHref } from "@/lib/auth";
import { Avatar } from "@/components/Avatar";
import { LearningPanel, OverviewPanel, PrefsPanel, ProfilePanel, SecurityPanel, WorksPanel } from "./panels";

export const TABS: { key: string; label: string; icon: LucideIcon }[] = [
  { key: "overview", label: "概览", icon: BarChart3 },
  { key: "profile", label: "个人资料", icon: UserRound },
  { key: "security", label: "账号安全", icon: ShieldCheck },
  { key: "works", label: "我的作品", icon: Library },
  { key: "learning", label: "学习记录", icon: BookOpen },
  { key: "prefs", label: "偏好设置", icon: Settings2 },
];

const fmtDate = (s?: string | null) => (s ? new Date(s).toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric" }) : "");

export function MeView() {
  const { user, actingAs } = useAuth();
  const router = useRouter();
  const path = usePathname() ?? "/me";
  const params = useSearchParams();
  const raw = params?.get("tab") ?? "overview";
  const tab = TABS.some((t) => t.key === raw) ? raw : "overview";
  const go = (k: string) => router.replace(k === "overview" ? path : `${path}?tab=${k}`, { scroll: false });
  // demo mode (server does not require a login): show the demo account's data, read-only profile
  const nickname = user?.nickname ?? actingAs?.nickname ?? "演示账号";
  const username = user?.username ?? actingAs?.username ?? "demo";

  return (
    <div className="me" data-testid="me-page">
      <section className="me-head card">
        <Avatar src={user?.avatar_url} name={nickname} size={72} testId="me-avatar" />
        <div className="me-id">
          <div className="eyebrow">个人中心</div>
          <h1 className="h1" data-testid="me-nickname">
            {nickname}
          </h1>
          <div className="faint" style={{ fontSize: 13 }}>
            @{username}
            {user?.created_at ? ` · ${fmtDate(user.created_at)} 加入` : ""}
          </div>
          {!user || user.is_demo ? (
            <p className="muted me-bio" data-testid="me-demo">
              当前为演示账号，数据会和其他未登录的访客共用。
              <Link href={loginHref("/me")}>登录</Link>或<Link href={`/register?next=${encodeURIComponent("/me")}`}>注册</Link>
              后保存到你自己的账号。
            </p>
          ) : user.bio ? (
            <p className="muted me-bio" data-testid="me-bio">
              {user.bio}
            </p>
          ) : (
            <button type="button" className="linkish faint me-bio" onClick={() => go("profile")} data-testid="me-bio-empty">
              写一句简介，让旅伴认识你 →
            </button>
          )}
        </div>
      </section>

      <div className="me-body">
        <nav className="me-tabs" role="tablist" aria-label="个人中心分区">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              id={`me-tab-${t.key}`}
              aria-selected={tab === t.key}
              aria-controls={`me-panel-${t.key}`}
              className={tab === t.key ? "on" : undefined}
              data-testid={`me-tab-${t.key}`}
              onClick={() => go(t.key)}
            >
              <t.icon size={16} aria-hidden />
              <span>{t.label}</span>
            </button>
          ))}
        </nav>
        <section
          className="me-panel"
          role="tabpanel"
          id={`me-panel-${tab}`}
          aria-labelledby={`me-tab-${tab}`}
          data-testid={`me-panel-${tab}`}
          key={tab}
        >
          {tab === "overview" ? <OverviewPanel onGo={go} /> : null}
          {tab === "profile" ? <ProfilePanel /> : null}
          {tab === "security" ? <SecurityPanel /> : null}
          {tab === "works" ? <WorksPanel /> : null}
          {tab === "learning" ? <LearningPanel /> : null}
          {tab === "prefs" ? <PrefsPanel /> : null}
        </section>
      </div>
    </div>
  );
}
