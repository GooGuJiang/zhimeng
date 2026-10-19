/**
 * Local generative-UI fallback (F6): when the backend sends no `ui` components (or they fail to
 * render), derive the same UIComponent specs from the structured world state so the panels still
 * reflect the current plot. Output goes through the same OpenUI compiler + renderer.
 */
import type { Option, UIComponent, World, WorldEvent } from "@/lib/types";

const layout = (area: UIComponent["layout"]["area"], size: UIComponent["layout"]["size"]) => ({ area, size });

export function fallbackComponents(
  world: World,
  events: WorldEvent[] = [],
  options: Option[] = [],
): UIComponent[] {
  const st = world.state;
  const player = world.characters.find((c) => c.is_player || c.id === world.player?.character_id);
  const locName = (id: string | null | undefined) => world.locations.find((l) => l.id === id)?.name ?? "未知";
  const out: UIComponent[] = [
    {
      id: "status",
      type: "status_panel",
      title: `${world.player?.name || player?.name || "你"}的状态`,
      priority: 100,
      layout: layout("side", "md"),
      props: {
        player: {
          name: world.player?.name || player?.name || "你",
          role: world.player?.role || player?.role || "",
          location: locName(st.player_location_id ?? player?.location_id),
          hp: st.hp ?? 100,
          mood: player?.mood ?? "",
        },
        stats: st.stats ?? {},
        time: st.time,
        chapter: st.chapter,
        turn: st.turn,
        tags: [world.genre, world.tone].filter(Boolean),
      },
      actions: [],
    },
    {
      id: "relations",
      type: "relationship_graph",
      title: "人物关系",
      priority: 80,
      layout: layout("side", "md"),
      props: {
        nodes: world.characters.map((c) => ({
          id: c.id,
          label: c.name,
          role: c.role,
          mood: c.mood,
          is_player: c.is_player || c.id === world.player?.character_id,
          emoji: c.avatar_emoji,
        })),
        edges: world.characters.flatMap((c) =>
          (c.relations ?? []).map((r) => ({
            source: c.id,
            target: r.target_id,
            type: r.type,
            affinity: r.affinity,
          })),
        ),
      },
      actions: [],
    },
    {
      id: "map",
      type: "map",
      title: "舆图",
      priority: 60,
      layout: layout("side", "md"),
      props: mapProps(world),
      actions: [],
    },
  ];
  const items = world.items.filter(
    (i) => !i.owner_id || i.owner_id === world.player?.character_id || i.owner_id === player?.id,
  );
  out.push({
    id: "inventory",
    type: "inventory",
    title: "行囊",
    priority: 40,
    layout: layout("side", "sm"),
    props: {
      items: items.map((i) => ({ id: i.id, name: i.name, description: i.description, quantity: i.quantity })),
    },
    actions: [],
  });
  if (world.mode === "education")
    out.push({
      id: "knowledge",
      type: "knowledge_cards",
      title: "知识卡片",
      priority: 90,
      layout: layout("side", "md"),
      props: { cards: world.knowledge_cards ?? [] },
      actions: [],
    });
  void events;
  void options;
  return out;
}

export function mapProps(world: World) {
  const here = world.state?.player_location_id ?? null;
  const edges: { source: string; target: string }[] = [];
  const seen = new Set<string>();
  for (const l of world.locations)
    for (const t of l.connections ?? []) {
      const k = [l.id, t].sort().join("|");
      if (!seen.has(k)) {
        seen.add(k);
        edges.push({ source: l.id, target: t });
      }
    }
  return {
    locations: world.locations.map((l) => ({
      id: l.id,
      name: l.name,
      x: l.x,
      y: l.y,
      description: l.description,
      characters: world.characters.filter((c) => c.location_id === l.id && !c.is_player).map((c) => c.name),
    })),
    edges,
    current_location_id: here ?? "",
  };
}
