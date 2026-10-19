/**
 * UI polish (mocked API): the 世界面板 stays in view while the story scrolls, model text renders as
 * Markdown (headings / bold / lists / tables, no raw HTML), partial markdown streams without breaking,
 * and phones get a 故事/世界面板 switch. Screenshots → docs/screens/fe-27…fe-29.
 */
import path from "node:path";
import { expect, test } from "@playwright/test";
import { WORLD_ID, fixtures, mockApi, sse, type Json } from "./mock-api";

const PLAY = `/play/${WORLD_ID}`;
const SHOTS = path.resolve(__dirname, "../../docs/screens");

const MD = [
  "### 十六铺码头 · 夜",
  "",
  "汽笛声里，顾长庚把一张**泛黄的船票**塞进你手心，*压低了声音*：",
  "",
  "> “别回头，有人跟着你。”",
  "",
  "你迅速记下眼前的线索：",
  "",
  "- **船票**：明晚十点，开往香港",
  "- **袖口的油渍**：来自法租界的印刷厂",
  "- 远处那盏忽明忽暗的~~灯~~信号",
  "",
  "| 人物 | 态度 | 所在 |",
  "| --- | --- | --- |",
  "| 顾长庚 | 紧张 | 码头 |",
  "| 沈墨言 | 未知 | 报馆 |",
  "",
  "<script>window.__xss = 1</script><b>raw html must not render</b>",
].join("\n");

function manyTurns(n: number): Json[] {
  const base = fixtures.turns[0] as Json;
  const out: Json[] = [];
  for (let i = 1; i <= n; i++)
    out.push({
      ...base,
      id: `t_long_${i}`,
      index: i,
      action: `第${i}步：继续追查`,
      narration:
        i === n
          ? MD
          : `第${i}回合。雨落在黄浦江上，**霓虹**在水面碎成一片。\n你沿着弄堂往前走，石板路湿滑，远处传来电车的铃声。\n\n- 线索 ${i}：一枚纽扣\n- 线索 ${i + 1}：半张报纸`,
    });
  return out;
}

test("世界面板 is sticky while the story scrolls; narration renders markdown safely", async ({ page }) => {
  const st = await mockApi(page);
  st.turns = manyTurns(8);
  await page.goto(PLAY);
  const latest = page.getByTestId("narration-latest");
  await expect(latest.locator("h3")).toHaveText("十六铺码头 · 夜");
  await expect(latest.locator("strong").first()).toHaveText("泛黄的船票");
  await expect(latest.locator("ul > li")).toHaveCount(3);
  await expect(latest.locator("table tr")).toHaveCount(3);
  await expect(latest.locator("blockquote")).toBeVisible();
  // raw HTML is dropped, never executed / rendered
  await expect(latest.locator("script, b")).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();

  const side = page.getByTestId("world-panel");
  await expect(side).toBeVisible();
  const before = await side.boundingBox();
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight * 0.55));
  await page.waitForTimeout(400);
  expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(800);
  const after = await side.boundingBox();
  // sticks just under the 64px top bar instead of scrolling away
  expect(after!.y).toBeGreaterThanOrEqual(0);
  expect(after!.y).toBeLessThan(120);
  expect(after!.y + after!.height).toBeLessThanOrEqual(900 + 1);
  expect(before).not.toBeNull();
  await page.screenshot({ path: `${SHOTS}/fe-27-sticky-world.png` });

  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await page.waitForTimeout(400);
  await expect(side).toBeInViewport();
  await latest
    .locator("h3")
    .evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 140));
  await page.waitForTimeout(300);
  await expect(side).toBeInViewport();
  await page.screenshot({ path: `${SHOTS}/fe-28-markdown.png` });
});

test("streaming partial markdown types cleanly and the panel updates from the stream", async ({ page }) => {
  const st = await mockApi(page);
  const w = fixtures.world as Json;
  const state = { ...(w.state as Json), turn: 2, time: "第1天·深夜" };
  const chunks = [
    "## 巡捕房",
    "\n\n探长**眯起",
    "眼睛**，",
    "*慢慢*说：\n\n1. 先",
    "看口供\n2. 再看`案卷",
    "`",
  ];
  const narration = chunks.join("");
  const turn = { ...(fixtures.turns[0] as Json), id: "t_md2", index: 2, action: "去巡捕房", narration };
  st.turnStream = () =>
    sse([
      ["progress", { stage: "narrate", message: "落笔", pct: 60 }],
      ...chunks.map((t) => ["token", { text: t }] as [string, unknown]),
      ["options", { options: [{ id: "o1", text: "继续" }] }],
      ["done", { turn, state }],
    ]);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(PLAY);
  await page.getByTestId("free-input").fill("去巡捕房");
  await page.keyboard.press("Enter");
  const t2 = page.locator('article[data-turn="2"]');
  await expect(t2.locator("h2")).toHaveText("巡捕房");
  await expect(t2.locator("strong")).toHaveText("眯起眼睛");
  await expect(t2.locator("ol > li")).toHaveCount(2);
  await expect(t2.locator("code")).toHaveText("案卷");
  await expect(page.locator(".story-head .tag.gold")).toContainText("第2回合");
  await expect(page.locator(".story-head")).toContainText("第1天·深夜");
  expect(errors).toEqual([]);
});

test("phones: 故事 / 世界面板 switch keeps the layout single-column", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page);
  await page.goto(PLAY);
  const tabs = page.getByRole("tablist", { name: "切换视图" });
  await expect(tabs).toBeVisible();
  await expect(page.getByTestId("world-panel")).toBeHidden();
  await page.getByTestId("world-panel-tab").click();
  await expect(page.getByTestId("world-panel")).toBeVisible();
  await expect(page.getByTestId("narration")).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: `${SHOTS}/fe-29-mobile-world-tab.png` });
  await tabs.getByRole("tab", { name: "故事" }).click();
  await expect(page.getByTestId("narration")).toBeVisible();
});
