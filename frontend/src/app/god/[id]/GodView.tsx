"use client";
/** 上帝视角 (F7): every NPC's state, trajectory and memories; inject events; run the world once. */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { FastForward, Zap, ArrowLeft } from "lucide-react";
import { api, errorText } from "@/lib/api";
import type { MemoryEntry, NpcView, World, WorldEvent } from "@/lib/types";
import { setCurrentWorld } from "@/hooks/useCurrentWorld";
import { kindLabel } from "@/openui/library";
import { useToast } from "@/components/Toast";
import { WorldMapView } from "@/components/WorldBits";
import { AiLabel } from "@/components/AiLabel";

const IMPACTS = [
  { v: "low", l: "微澜" },
  { v: "medium", l: "波折" },
  { v: "high", l: "巨变" },
] as const;

export function GodView({ id }: { id: string }) {
  const toast = useToast();
  const [world, setWorld] = useState<World | null>(null);
  const [npcs, setNpcs] = useState<NpcView[] | null>(null);
  const [events, setEvents] = useState<WorldEvent[]>([]);
  const [injected, setInjected] = useState<MemoryEntry[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [content, setContent] = useState("");
  const [targets, setTargets] = useState<string[]>([]);
  const [location, setLocation] = useState("");
  const [impact, setImpact] = useState<(typeof IMPACTS)[number]["v"]>("high");
  const [busy, setBusy] = useState<"inject" | "tick" | null>(null);
  const [focus, setFocus] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [w, n, e, m] = await Promise.allSettled([
      api.getWorld(id),
      api.npcs(id),
      api.events(id, "", 40),
      api.memory(id, "injected", 20),
    ]);
    if (w.status === "fulfilled") setWorld(w.value);
    else setErr(errorText(w.reason));
    if (n.status === "fulfilled") setNpcs(n.value);
    else setNpcs([]);
    if (e.status === "fulfilled") setEvents(e.value);
    if (m.status === "fulfilled") setInjected(m.value);
  }, [id]);

  useEffect(() => {
    setCurrentWorld(id);
    // load() only sets state after its awaits resolve
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [id, load]);

  const inject = async () => {
    if (!content.trim()) return;
    setBusy("inject");
    try {
      const ev = await api.inject(id, {
        content: content.trim(),
        target_character_ids: targets.length ? targets : undefined,
        location_id: location || undefined,
        impact,
      });
      toast(`天意已降：${ev.summary || content}`);
      setContent("");
      await load();
    } catch (e) {
      toast(`插入失败：${errorText(e)}`);
    } finally {
      setBusy(null);
    }
  };
  const tick = async () => {
    setBusy("tick");
    try {
      const r = await api.tick(id);
      toast(`世界运转了一轮，发生 ${r.events.length} 件事`);
      await load();
    } catch (e) {
      toast(`推进失败：${errorText(e)}`);
    } finally {
      setBusy(null);
    }
  };

  if (!world)
    return err ? (
      <div className="empty">
        <h1 className="h1">世界无法载入</h1>
        <p>{err}</p>
      </div>
    ) : (
      <div className="skel" style={{ height: 300 }} />
    );
  const loc = (lid: string | null) => world.locations.find((l) => l.id === lid)?.name ?? "行踪不明";
  const list = (npcs ?? []).filter((n) => !n.character.is_player);

  return (
    <div className="god-page">
      <section className="card god-banner" style={{ marginBottom: 20 }}>
        <div className="row">
          <Link href={`/play/${id}`} className="btn sm ghost">
            <ArrowLeft size={14} aria-hidden /> 回到游玩
          </Link>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div className="eyebrow">上帝视角</div>
            <h1 className="h1">{world.title}</h1>
          </div>
          <span className="tag gold">
            第{world.state.chapter}章 · 第{world.state.turn}回合 · {world.state.time}
          </span>
          <button
            type="button"
            className="btn ghost"
            data-testid="tick-btn"
            disabled={!!busy}
            onClick={() => void tick()}
          >
            <FastForward size={16} aria-hidden /> {busy === "tick" ? "众生行动中…" : "推进一次世界"}
          </button>
        </div>
        <p className="muted" style={{ margin: "10px 0 0" }}>
          俯瞰众生：每位角色都有自己的目标与记忆，会在你不在场时行动。你在此插入的事件将写入世界记忆，并影响后续叙事。
        </p>
      </section>

      <div className="god">
        <div className="stack">
          {npcs === null ? (
            <div className="npc-grid">
              {[0, 1, 2].map((i) => (
                <div key={i} className="skel" style={{ height: 220 }} />
              ))}
            </div>
          ) : (
            <div className="npc-grid">
              {list.map(({ character: c, trajectory, recent_events, memories }) => (
                <article
                  key={c.id}
                  className={`npc-card${focus === c.id ? " on" : ""}`}
                  data-testid="npc-card"
                  onMouseEnter={() => setFocus(c.id)}
                  onMouseLeave={() => setFocus(null)}
                >
                  <header>
                    <span className="av" aria-hidden>
                      {c.avatar_emoji || c.name.slice(0, 1)}
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <strong className="serif">{c.name}</strong> <span className="tag">{c.role}</span>
                      <div className="faint" style={{ fontSize: 12 }}>
                        {loc(c.location_id)} · {c.mood || "神色如常"} · {c.status}
                      </div>
                    </div>
                    <label className="pick" title="作为插入事件的目标">
                      <input
                        type="checkbox"
                        checked={targets.includes(c.id)}
                        onChange={(e) =>
                          setTargets(
                            e.target.checked ? [...targets, c.id] : targets.filter((t) => t !== c.id),
                          )
                        }
                      />
                      目标
                    </label>
                  </header>
                  {c.goals?.length ? (
                    <p className="npc-goal">
                      <span className="faint">所求 </span>
                      {c.goals.join("；")}
                    </p>
                  ) : null}
                  <div className="eyebrow" style={{ letterSpacing: "0.2em" }}>
                    行动轨迹
                  </div>
                  <ol className="npc-trajectory" data-testid="npc-trajectory">
                    {trajectory.length ? (
                      [...trajectory]
                        .sort((a, b) => b.turn - a.turn)
                        .slice(0, 6)
                        .map((t, i) => (
                          <li key={i}>
                            <span className="faint num">
                              第{t.turn}回合 · {t.location_name}
                            </span>
                            <div>{t.action}</div>
                          </li>
                        ))
                    ) : (
                      <li className="faint">尚未离开初始位置</li>
                    )}
                  </ol>
                  {memories?.length ? (
                    <details>
                      <summary className="faint" style={{ cursor: "pointer", fontSize: 13 }}>
                        TA 记得的事（{memories.length}）
                      </summary>
                      <ul className="npc-mem">
                        {memories.slice(0, 8).map((m, i) => (
                          <li key={i}>{m}</li>
                        ))}
                      </ul>
                    </details>
                  ) : null}
                  {recent_events?.length ? (
                    <p className="faint" style={{ margin: 0, fontSize: 12 }}>
                      最近：{recent_events[0].summary}
                    </p>
                  ) : null}
                </article>
              ))}
              {!list.length ? <p className="faint">这个世界里暂时没有其他角色。</p> : null}
            </div>
          )}

          <section className="card flat">
            <div className="card-h">
              <i className="knot" aria-hidden />
              <h2 className="h2">世界时间线</h2>
            </div>
            <div className="offscreen-list">
              {events.slice(0, 20).map((e) => (
                <article key={e.id} className={`offscreen-event k-${e.type}`}>
                  <p style={{ margin: 0 }}>{e.summary}</p>
                  <p className="faint" style={{ margin: "2px 0 0" }}>
                    {[e.in_world_time, kindLabel(e.type), loc(e.location_id), `第${e.turn}回合`, e.impact]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </article>
              ))}
              {!events.length ? <p className="faint">尚无事件。</p> : null}
            </div>
          </section>
        </div>

        <div className="stack god-side">
          <section className="card">
            <div className="card-h">
              <Zap size={16} aria-hidden />
              <h2 className="h2">插入事件</h2>
            </div>
            <div className="stack">
              <textarea
                className="textarea"
                data-testid="inject-input"
                placeholder="插入一个改变世界走向的事件，例如：十六铺码头突发大火"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                maxLength={300}
              />
              <label className="field">
                <span>发生地点</span>
                <select className="select" value={location} onChange={(e) => setLocation(e.target.value)}>
                  <option value="">不限</option>
                  {world.locations.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.name}
                    </option>
                  ))}
                </select>
              </label>
              <div className="field">
                <span>影响程度</span>
                <div className="chips">
                  {IMPACTS.map((i) => (
                    <button
                      key={i.v}
                      type="button"
                      className={`chip${impact === i.v ? " on" : ""}`}
                      onClick={() => setImpact(i.v)}
                    >
                      {i.l}
                    </button>
                  ))}
                </div>
              </div>
              {targets.length ? (
                <p className="faint" style={{ margin: 0, fontSize: 13 }}>
                  牵涉：{targets.map((t) => world.characters.find((c) => c.id === t)?.name).join("、")}
                </p>
              ) : null}
              <button
                type="button"
                className="btn"
                data-testid="inject-btn"
                disabled={!!busy || !content.trim()}
                onClick={() => void inject()}
              >
                <Zap size={16} aria-hidden /> {busy === "inject" ? "天意降临中…" : "插入事件"}
              </button>
            </div>
          </section>
          <section className="card flat">
            <div className="card-h">
              <i className="knot" aria-hidden />
              <h2 className="h2">干预留痕</h2>
              <AiLabel />
            </div>
            {injected.length ? (
              <ul className="npc-mem">
                {injected.map((m) => (
                  <li key={m.id}>
                    {m.content} <span className="faint">（{m.source || `第${m.turn}回合`}）</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="faint" style={{ margin: 0 }}>
                尚未插入事件。
              </p>
            )}
          </section>
          <section className="card flat">
            <div className="card-h">
              <i className="knot" aria-hidden />
              <h2 className="h2">众生分布</h2>
            </div>
            <WorldMapView world={world} />
          </section>
        </div>
      </div>
    </div>
  );
}
