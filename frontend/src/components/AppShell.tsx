"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { BookOpen, Brain, Eye, Feather, Archive, Settings, Sparkles, Moon, Sun } from "lucide-react";
import { useApplyPrefs, usePrefs } from "@/hooks/usePrefs";
import { useCurrentWorld } from "@/hooks/useCurrentWorld";
import { ToastProvider } from "./Toast";
import { api } from "@/lib/api";

export function BrandMark({ className = "brand-mark" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 32 32" aria-hidden>
      <defs>
        <linearGradient id="bm" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" style={{ stopColor: "var(--gold-2)" }} />
          <stop offset="1" style={{ stopColor: "var(--rose)" }} />
        </linearGradient>
      </defs>
      <circle cx="16" cy="16" r="14" fill="none" stroke="url(#bm)" strokeWidth="1.2" opacity="0.6" />
      <path
        d="M6 12 C 12 6, 20 18, 26 12"
        fill="none"
        stroke="url(#bm)"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <path
        d="M6 20 C 12 14, 20 26, 26 20"
        fill="none"
        style={{ stroke: "var(--azure)" }}
        strokeWidth="1.2"
        strokeLinecap="round"
      />
      <path d="M16 4 L16 28" style={{ stroke: "var(--gold)" }} strokeWidth="0.8" strokeDasharray="1.5 2" />
    </svg>
  );
}

function ThreadsBg() {
  return (
    <svg className="threads-bg" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice" aria-hidden>
      <path d="M-40 180 C 300 80, 520 320, 860 200 S 1300 120, 1500 260" style={{ stroke: "var(--gold)" }} />
      <path d="M-40 520 C 260 420, 640 700, 980 540 S 1340 460, 1500 600" style={{ stroke: "var(--rose)" }} />
      <path
        d="M-40 760 C 380 640, 700 860, 1080 720 S 1380 700, 1500 780"
        style={{ stroke: "var(--azure)" }}
      />
      <path d="M-40 360 C 340 300, 600 480, 900 380 S 1320 300, 1500 400" style={{ stroke: "var(--jade)" }} />
    </svg>
  );
}

const NAV = [
  {
    key: "home",
    href: () => "/",
    label: "开局",
    icon: Sparkles,
    match: (p: string) => p === "/" || p.startsWith("/preview"),
  },
  {
    key: "play",
    href: (w: string | null) => (w ? `/play/${w}` : "/play"),
    label: "游玩",
    icon: Feather,
    match: (p: string) => p.startsWith("/play"),
  },
  {
    key: "god",
    href: (w: string | null) => (w ? `/god/${w}` : "/god"),
    label: "上帝视角",
    icon: Eye,
    match: (p: string) => p.startsWith("/god"),
  },
  {
    key: "memory",
    href: (w: string | null) => (w ? `/memory/${w}` : "/memory"),
    label: "记忆",
    icon: Brain,
    match: (p: string) => p.startsWith("/memory"),
  },
  {
    key: "edu",
    href: () => "/education",
    label: "教育",
    icon: BookOpen,
    match: (p: string) => p.startsWith("/education"),
  },
  {
    key: "saves",
    href: () => "/saves",
    label: "存档",
    icon: Archive,
    match: (p: string) => p.startsWith("/saves"),
  },
  {
    key: "settings",
    href: () => "/settings",
    label: "设置",
    icon: Settings,
    match: (p: string) => p.startsWith("/settings"),
  },
];
const TAB_KEYS = ["home", "play", "god", "memory", "settings"];

function WorldChip({ id }: { id: string }) {
  const [title, setTitle] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api
      .getWorld(id)
      .then((w) => live && setTitle(w.title))
      .catch(() => live && setTitle(null));
    return () => {
      live = false;
    };
  }, [id]);
  if (!title) return null;
  return (
    <Link href={`/play/${id}`} className="world-chip" title={`当前世界：${title}`}>
      ◈ {title}
    </Link>
  );
}

function ThemeToggle() {
  const [prefs, setPrefs] = usePrefs();
  const dark = prefs.theme === "dark";
  return (
    <button
      type="button"
      className="icon-btn theme-toggle"
      data-testid="theme-toggle"
      aria-label={dark ? "切换到浅色「宣纸」主题" : "切换到深色「夜织」主题"}
      title={dark ? "浅色主题" : "深色主题"}
      onClick={() => setPrefs({ theme: dark ? "light" : "dark" })}
    >
      {dark ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />}
    </button>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  useApplyPrefs();
  const path = usePathname() ?? "/";
  const [worldId] = useCurrentWorld();
  return (
    <ToastProvider>
      <ThreadsBg />
      <div className="shell">
        <header className="topbar">
          <Link href="/" className="brand" aria-label="织梦 首页">
            <BrandMark />
            织梦<small>ZHIMENG</small>
          </Link>
          {worldId ? <WorldChip id={worldId} /> : null}
          <nav className="nav" aria-label="主导航">
            {NAV.map((n) => (
              <Link key={n.key} href={n.href(worldId)} className={n.match(path) ? "on" : undefined}>
                {n.label}
              </Link>
            ))}
          </nav>
          <ThemeToggle />
        </header>
        <main className="page page-enter" key={path.split("/")[1] || "home"}>
          {children}
        </main>
        <nav className="tabbar" aria-label="底部导航">
          {NAV.filter((n) => TAB_KEYS.includes(n.key)).map((n) => (
            <Link key={n.key} href={n.href(worldId)} className={n.match(path) ? "on" : undefined}>
              <n.icon aria-hidden />
              {n.label === "上帝视角" ? "上帝" : n.label}
            </Link>
          ))}
        </nav>
      </div>
    </ToastProvider>
  );
}
