"use client";
import Link from "next/link";
import type { ReactNode } from "react";
import { BrandMark } from "./AppShell";

/** Shared frame for 登录 / 注册: brand, title, the form, and a footer link. */
export function AuthCard({ title, sub, children, foot }: { title: string; sub: string; children: ReactNode; foot: ReactNode }) {
  return (
    <div className="auth-page">
      <section className="auth-card card">
        <Link href="/" className="auth-brand" aria-label="返回织梦首页">
          <BrandMark className="brand-mark" /> 织梦
        </Link>
        <h1 className="h1" id="auth-title">
          {title}
        </h1>
        <p className="muted auth-sub">{sub}</p>
        {children}
        <div className="auth-foot">{foot}</div>
      </section>
    </div>
  );
}
