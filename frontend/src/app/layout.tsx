import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "@xyflow/react/dist/style.css";
import "./globals.css";
import { AppShell } from "@/components/AppShell";
import { SHOW_AI_LABEL } from "@/components/AiLabel";

export const metadata: Metadata = {
  title: SHOW_AI_LABEL ? "织梦 · AI 原生互动叙事引擎" : "织梦 · 互动叙事引擎",
  description: "一句话，生成一个可玩、有记忆、会自己运转的世界。",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#f5f0e6",
};

const THEME_BOOT = `try{var t=(JSON.parse(localStorage.getItem("zhimeng.prefs")||"{}").theme)||"light";if(t==="dark"||(t==="system"&&matchMedia("(prefers-color-scheme: dark)").matches))document.documentElement.setAttribute("data-theme","dark")}catch(e){}`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        {/* apply the saved theme before first paint (no light→dark flash) */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
      </head>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
