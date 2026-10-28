import { Suspense } from "react";
import type { Metadata } from "next";
import { RegisterView } from "./RegisterView";

export const metadata: Metadata = { title: "注册 · 织梦" };

export default function Page() {
  return (
    <Suspense fallback={<div className="skel" style={{ height: 520, maxWidth: 440, margin: "40px auto" }} />}>
      <RegisterView />
    </Suspense>
  );
}
