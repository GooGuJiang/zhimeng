"use client";
/** F3 "场外大事件": what NPCs and the world did while the player was elsewhere. */
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { World, WorldEvent } from "@/lib/types";
import { kindLabel } from "@/openui/library";

export function OffscreenPanel({ world, events }: { world: World; events: WorldEvent[] }) {
  const [sent, setSent] = useState<Set<string>>(() => new Set());
  const list = [...events]
    .filter((e) => e.type !== "player")
    .sort((a, b) => b.turn - a.turn || (b.timestamp ?? "").localeCompare(a.timestamp ?? ""))
    .slice(0, 20);
  const unseen = list.filter((e) => !e.seen && !sent.has(e.id)).map((e) => e.id);
  useEffect(() => {
    if (!unseen.length) return;
    const t = setTimeout(() => {
      setSent((old) => new Set([...old, ...unseen]));
      api.markSeen(world.id, unseen).catch(() => {});
    }, 4000);
    return () => clearTimeout(t);
  }, [unseen.join(","), world.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const name = (id: string) => world.characters.find((c) => c.id === id)?.name ?? id;
  const loc = (id: string | null) => world.locations.find((l) => l.id === id)?.name;
  return (
    <section className="card flat genui-panel" data-testid="offscreen-panel" aria-label="场外大事件">
      <div className="card-h">
        <i className="knot" aria-hidden />
        <h3 className="h2" style={{ fontSize: 16 }}>
          场外大事件
        </h3>
        <span className="faint" style={{ fontSize: 12 }}>
          你不在场时
        </span>
      </div>
      {list.length ? (
        <div className="offscreen-list">
          {list.map((e) => (
            <article
              key={e.id}
              className={`offscreen-event k-${e.type}${e.seen ? "" : " new"}`}
              data-testid="offscreen-event"
            >
              <p style={{ margin: 0 }}>{e.summary}</p>
              <p className="faint" style={{ margin: "2px 0 0" }}>
                {[
                  e.in_world_time,
                  kindLabel(e.type),
                  e.actor_ids?.length ? e.actor_ids.map(name).join("、") : null,
                  loc(e.location_id),
                  `第${e.turn}回合`,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </article>
          ))}
        </div>
      ) : (
        <p className="faint" style={{ margin: 0 }}>
          暂时风平浪静。推进剧情后，众人会各自行动。
        </p>
      )}
    </section>
  );
}
