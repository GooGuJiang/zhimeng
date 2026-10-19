// Dev check: every compiled panel parses cleanly against the library.
import { createParser } from "@openuidev/react-lang";
import { library } from "../src/openui/library";
import { compileComponent } from "../src/openui/compile";
import type { UIComponent } from "../src/lib/types";

const parser = createParser(library.toJSONSchema(), library.root);
const base: Pick<UIComponent, "priority" | "layout" | "actions"> = {
  priority: 1,
  layout: { area: "side", size: "md" },
  actions: [],
};
const samples: UIComponent[] = [
  {
    ...base,
    id: "status",
    type: "status_panel",
    title: "状态",
    props: {
      player: { name: "沈墨", role: "记者", location: "外滩", hp: 80, mood: "警觉" },
      stats: { 线索: 3, 声望: 40 },
      time: "黄昏",
      chapter: 1,
      turn: 2,
      tags: ["受伤"],
    },
    actions: [{ id: "a", label: "休息", kind: "turn", payload: { action: "找地方休息" } }],
  },
  {
    ...base,
    id: "rel",
    type: "relationship_graph",
    title: "关系",
    props: {
      nodes: [
        { id: "p", label: "沈墨", is_player: true },
        { id: "c1", label: "老周", role: "线人", mood: "紧张" },
      ],
      edges: [{ source: "p", target: "c1", type: "线人", affinity: 40 }],
    },
  },
  {
    ...base,
    id: "inv",
    type: "inventory",
    title: "行囊",
    props: { items: [{ id: "i", name: "相机", description: "莱卡", quantity: 1 }] },
  },
  {
    ...base,
    id: "map",
    type: "map",
    title: "地图",
    props: {
      locations: [
        { id: "l1", name: "外滩", x: 20, y: 30, description: "江风", characters: ["老周"] },
        { id: "l2", name: "码头", x: 70, y: 60 },
      ],
      edges: [{ source: "l1", target: "l2" }],
      current_location_id: "l1",
    },
  },
  {
    ...base,
    id: "ev",
    type: "event_feed",
    title: "场外",
    props: {
      events: [{ summary: "巡捕房连夜搜查", in_world_time: "子夜", type: "offscreen", impact: "high" }],
    },
  },
  {
    ...base,
    id: "kc",
    type: "knowledge_cards",
    title: "知识",
    props: { cards: [{ title: "申报", content: '近代中国历史最久的报纸 "之一"', source: "史料" }] },
  },
  {
    ...base,
    id: "ch",
    type: "choice_list",
    title: "选择",
    props: { options: [{ id: "o1", text: "追上去" }] },
  },
];
let bad = 0;
for (const s of samples) {
  const prog = compileComponent(s);
  const r = parser.parse(prog);
  const errs = r.meta?.errors ?? [];
  console.log(
    s.type,
    errs.length ? "ERR " + JSON.stringify(errs) : "ok",
    r.meta?.unresolved?.length ? "unresolved:" + r.meta.unresolved : "",
  );
  if (errs.length) {
    bad++;
    console.log(prog);
  }
}
console.log(JSON.stringify(parser.parse(compileComponent(samples[1])).root, null, 0).slice(0, 400));
process.exit(bad ? 1 : 0);
