import { Suspense } from "react";
import type { Metadata } from "next";
import { LoginView } from "./LoginView";

export const metadata: Metadata = { title: "登录 · 织梦" };

export default function Page() {
  return (
    <Suspense fallback={<div className="skel" style={{ height: 420, maxWidth: 440, margin: "40px auto" }} />}>
      <LoginView />
    </Suspense>
  );
}
