"use client";
/** 记忆问答 (F4): ask with citations; browse facts by kind; chapter summaries. */
import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";
import type { MemoryEntry, World } from "@/lib/types";
import { setCurrentWorld } from "@/hooks/useCurrentWorld";
import { MemoryQuery } from "@/components/MemoryQuery";

const KINDS = [
  { v: "", l: "全部" },
  { v: "fact", l: "事实" },
  { v: "event", l: "事件" },
  { v: "injected", l: "干预" },
  { v: "summary", l: "摘要" },
  { v: "setting", l: "设定" },
];

export function MemoryView({ id }: { id: string }) {
  const [world, setWorld] = useState<World | null>(null);
  const [kind, setKind] = useState("");
  const [items, setItems] = useState<MemoryEntry[] | null>(null);
  const [sums, setSums] = useState<
    { chapter: number; from_turn: number; to_turn: number; summary: string }[]
  >([]);
  useEffect(() => {
    setCurrentWorld(id);
    api
      .getWorld(id)
      .then(setWorld)
      .catch(() => {});
    api
      .summaries(id)
      .then(setSums)
      .catch(() => setSums([]));
  }, [id]);
  useEffect(() => {
    api
      .memory(id, kind, 100)
      .then(setItems)
      .catch(() => setItems([]));
  }, [id, kind]);
  return (
    <div className="stack">
      <div className="row">
        <Link href={`/play/${id}`} className="btn sm ghost">
          <ArrowLeft size={14} aria-hidden /> 回到游玩
        </Link>
        <div>
          <div className="eyebrow">世界记忆</div>
          <h1 className="h1">{world?.title ?? "…"}</h1>
        </div>
      </div>
      <div className="grid-2" style={{ alignItems: "start" }}>
        <div className="stack">
          <section className="card">
            <div className="card-h">
              <i className="knot" aria-hidden />
              <h2 className="h2">考考世界的记忆</h2>
            </div>
            <MemoryQuery worldId={id} />
          </section>
          <section className="card flat">
            <div className="card-h">
              <i className="knot" aria-hidden />
              <h2 className="h2">章节摘要</h2>
            </div>
            {sums.length ? (
              sums.map((s) => (
                <div key={s.chapter} className="timeline-row">
                  <span className="num faint">
                    第{s.chapter}章
                    <br />
                    {s.from_turn}–{s.to_turn}回
                  </span>
                  <span className="serif">{s.summary}</span>
                </div>
              ))
            ) : (
              <p className="faint" style={{ margin: 0 }}>
                每 5 回合为一章，章末会自动压缩为摘要。
              </p>
            )}
          </section>
        </div>
        <section className="card flat">
          <div className="card-h">
            <i className="knot" aria-hidden />
            <h2 className="h2">记忆库</h2>
            <span className="faint" style={{ fontSize: 12 }}>
              {items?.length ?? 0} 条
            </span>
          </div>
          <div className="chips" style={{ marginBottom: 12 }}>
            {KINDS.map((k) => (
              <button
                key={k.v}
                type="button"
                className={`chip${kind === k.v ? " on" : ""}`}
                onClick={() => {
                  setItems(null);
                  setKind(k.v);
                }}
              >
                {k.l}
              </button>
            ))}
          </div>
          <div className="stack" style={{ gap: 8 }}>
            {items === null ? <div className="skel" style={{ height: 120 }} /> : null}
            {items?.map((m) => (
              <div key={m.id} className="citation">
                <span className="src">{m.source || `第${m.chapter}章·第${m.turn}回合`}</span>
                <span>{m.content}</span>
              </div>
            ))}
            {items && !items.length ? <p className="faint">暂无记忆条目。</p> : null}
          </div>
        </section>
      </div>
    </div>
  );
}
