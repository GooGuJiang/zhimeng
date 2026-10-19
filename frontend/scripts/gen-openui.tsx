// Writes the OpenUI system prompt + JSON spec for our library so the backend's UI agent can emit
// OpenUI Lang (`UIComponent.openui`) that the frontend renders directly.
import { mkdirSync, writeFileSync } from "node:fs";
import { library } from "../src/openui/library";

mkdirSync("openui", { recursive: true });
const prompt = library.prompt({
  preamble:
    "你是《织梦》的界面导演（UI Agent）。根据当前世界数据，为一个面板写一段 OpenUI Lang 程序。只输出程序，不要解释。界面文字用中文。",
  additionalRules: [
    "Use only facts present in the provided world JSON (names, ids, numbers). Never invent characters or items.",
    "Prefer the Narrative components (RelationGraph, WorldMap, Inventory, EventLine, KnowledgeCard, Choices) and wrap them in Panel/Col.",
    'Buttons advance the story with @Act("…"); keep at most 3 buttons per panel.',
  ],
  examples: [
    `root = Col([panel])\npanel = Panel([head, hp, clues], "沈墨的状态", "gold")\nhead = Row([Stat("所在", "外滩"), Stat("时辰", "黄昏")], 4, "between")\nhp = Meter("体力", 72, 100, "rose")\nclues = Meter("线索", 3, 10, "azure")`,
    `root = Col([g, Button("去找老周", @Act("去码头找老周"), "ghost")])\ng = RelationGraph([{id: "p", label: "沈墨", is_player: true}, {id: "c1", label: "老周", role: "线人", mood: "紧张"}], [{source: "p", target: "c1", type: "线人", affinity: 40}])`,
  ],
});
writeFileSync("openui/system-prompt.txt", prompt);
writeFileSync("openui/spec.json", JSON.stringify(library.toJSONSchema(), null, 2));
console.log("wrote openui/system-prompt.txt", prompt.length, "chars");
