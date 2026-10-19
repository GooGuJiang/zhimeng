"use client";
/** Shared world renderers: map (OpenUI), character list, knowledge cards (OpenUI). */
import type { Character, KnowledgeCard, World } from "@/lib/types";
import { compileComponent } from "@/openui/compile";
import { mapProps } from "@/openui/fallback";
import { OpenUIBlock, type GenUIHandlers } from "./GenUI";

export function WorldMapView({ world, handlers }: { world: World; handlers?: GenUIHandlers }) {
  const program = compileComponent({
    id: "map",
    type: "map",
    title: "地图",
    priority: 1,
    layout: { area: "main", size: "lg" },
    props: mapProps(world),
    actions: [],
  });
  return (
    <div data-testid="world-map" aria-label="地图">
      <OpenUIBlock program={program} handlers={handlers} />
    </div>
  );
}

export function CharacterList({
  characters,
  onPick,
}: {
  characters: Character[];
  onPick?: (c: Character) => void;
}) {
  return (
    <div className="char-list" data-testid="character-list">
      {characters.map((c, i) => (
        <div
          key={c.id}
          className={`char${c.is_player ? " me" : ""}`}
          data-testid="character-item"
          style={{ animationDelay: `${i * 70}ms` }}
          onClick={onPick ? () => onPick(c) : undefined}
        >
          <span className="av" aria-hidden>
            {c.avatar_emoji || c.name.slice(0, 1)}
          </span>
          <div style={{ minWidth: 0 }}>
            <strong>{c.name}</strong>{" "}
            {c.is_player ? <span className="tag gold">你</span> : <span className="tag">{c.role}</span>}
            <p>{c.persona}</p>
            {c.goals?.length ? <p className="faint">所求：{c.goals.slice(0, 2).join("；")}</p> : null}
          </div>
        </div>
      ))}
    </div>
  );
}

export function KnowledgeCards({ cards }: { cards: KnowledgeCard[] }) {
  if (!cards.length) return <p className="faint">继续探索，解锁知识卡片。</p>;
  const program = compileComponent({
    id: "knowledge",
    type: "knowledge_cards",
    title: "知识卡片",
    priority: 1,
    layout: { area: "main", size: "md" },
    props: { cards },
    actions: [],
  });
  return <OpenUIBlock program={program} />;
}
