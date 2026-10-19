"use client";
/** /play, /god, /memory without an id: jump to the current world from localStorage, or explain. */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useCurrentWorld } from "@/hooks/useCurrentWorld";

export function NeedWorld({ section, label }: { section: string; label: string }) {
  const [id] = useCurrentWorld();
  const router = useRouter();
  useEffect(() => {
    if (id) router.replace(`/${section}/${id}`);
  }, [id, router, section]);
  if (id) return <div className="skel" style={{ height: 200 }} />;
  return (
    <div className="empty">
      <h1 className="h1">还没有正在进行的世界</h1>
      <p>先在开局页用一句话造化一个世界，再来{label}。</p>
      <div className="row" style={{ justifyContent: "center" }}>
        <Link href="/" className="btn">
          去开局
        </Link>
        <Link href="/saves" className="btn ghost">
          打开存档
        </Link>
      </div>
    </div>
  );
}
