import { Suspense } from "react";
import type { Metadata } from "next";
import { RequireAuth } from "@/components/RequireAuth";
import { MeView } from "./MeView";

export const metadata: Metadata = { title: "个人中心 · 织梦" };

export default function Page() {
  return (
    <Suspense fallback={<div className="skel" style={{ height: 320 }} />}>
      <RequireAuth>
        <MeView />
      </RequireAuth>
    </Suspense>
  );
}
