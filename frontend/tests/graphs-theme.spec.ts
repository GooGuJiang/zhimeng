/**
 * Graph canvases (React Flow + d3-force) and the light "宣纸" palette (mocked API).
 * Screenshots → docs/screens/fe-33…fe-37.
 */
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { WORLD_ID, fixtures, mockApi, sse, type Json } from "./mock-api";

const PLAY = `/play/${WORLD_ID}`;
const SHOTS = path.resolve(__dirname, "../../docs/screens");

/** WCAG relative-luminance contrast of two computed `rgb(...)` colours. */
function contrast(a: string, b: string) {
  const lum = (c: string) => {
    const [r, g, bl] = (c.match(/[\d.]+/g) ?? ["0", "0", "0"]).slice(0, 3).map((v) => {
      const x = Number(v) / 255;
      return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [l1, l2] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
}
const colors = (page: Page, sel: string) =>
  page
    .locator(sel)
    .first()
    .evaluate((el) => {
      const cs = getComputedStyle(el);
      return { color: cs.color, bg: getComputedStyle(document.body).backgroundColor };
    });

test("relationship graph renders with React Flow: nodes, labelled ties, selection popover", async ({
  page,
}) => {
  await mockApi(page);
  await page.goto(PLAY);
  const panel = page.getByTestId("ui-relationship_graph").first();
  const flow = panel.getByTestId("relation-flow");
  await expect(flow).toBeVisible();
  await expect(flow.locator(".react-flow__node")).toHaveCount(4);
  await expect(flow.getByTestId("relation-node").filter({ hasText: "沈墨言" })).toBeVisible();
  // A↔B pairs are merged into one tie whose label lists both directions
  await expect(flow.locator(".rf-tie-label").filter({ hasText: "暗中提防 · 对手" })).toBeVisible();
  await expect(flow.locator(".react-flow__controls")).toBeVisible();
  await flow.getByTestId("relation-node").filter({ hasText: "白玉兰" }).click();
  const pop = panel.getByRole("dialog", { name: "白玉兰" });
  await expect(pop).toBeVisible();
  await expect(pop.getByRole("button", { name: "去找白玉兰谈谈" })).toBeVisible();
  // 白玉兰 is tied to 你 and 沈墨言 only: 顾长庚 fades out, the neighbours stay lit
  await expect(flow.locator(".rf-person.dim")).toHaveCount(1);
  await expect(flow.locator(".rf-person.dim")).toContainText("顾长庚");
  for (const n of await flow.locator(".react-flow__node").all()) await expect(n).toBeVisible();
  await panel.scrollIntoViewIfNeeded();
  await panel.screenshot({ path: `${SHOTS}/fe-33-relation-graph.png` });
});

test("world map renders with React Flow and highlights the current place; updates live", async ({ page }) => {
  const st = await mockApi(page);
  await page.goto(`/preview/${WORLD_ID}`);
  const map = page.getByTestId("world-map");
  const flow = map.getByTestId("map-flow");
  await expect(flow).toBeVisible();
  const locs = (fixtures.world as unknown as { locations: unknown[] }).locations.length;
  await expect(flow.getByTestId("map-node")).toHaveCount(locs);
  await expect(flow.locator('[data-here="true"]')).toHaveCount(1);
  await expect(flow.locator(".rf-road").first()).toBeAttached();
  await flow
    .getByTestId("map-node")
    .filter({ hasNot: page.locator('[data-here="true"]') })
    .first()
    .click();
  await expect(map.getByRole("button", { name: /^前往/ })).toBeVisible();
  await map.screenshot({ path: `${SHOTS}/fe-34-world-map.png` });
  void st;
});

test("play page in the light palette: readable contrast, sticky panel, dark toggle", async ({ page }) => {
  await mockApi(page);
  await page.goto(PLAY);
  await expect(page.getByTestId("relation-flow")).toBeVisible();
  await expect(page.locator("html")).not.toHaveAttribute("data-theme", "dark");
  const narr = await colors(page, ".narr");
  expect(contrast(narr.color, narr.bg)).toBeGreaterThanOrEqual(7);
  const meta = await colors(page, ".turn-meta");
  expect(contrast(meta.color, meta.bg)).toBeGreaterThanOrEqual(4.5);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${SHOTS}/fe-35-play-light.png` });

  await page.getByTestId("theme-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const dark = await colors(page, ".narr");
  expect(contrast(dark.color, dark.bg)).toBeGreaterThanOrEqual(7);
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark"); // persisted, applied before paint
  await expect(page.getByTestId("relation-flow").locator(".react-flow__node")).toHaveCount(4);
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${SHOTS}/fe-37-play-dark.png` });
  await page.getByTestId("theme-toggle").click();
  await expect(page.locator("html")).not.toHaveAttribute("data-theme", "dark");
});

test("home page in the light palette", async ({ page }) => {
  await mockApi(page, {
    extra: (method, p) => (method === "GET" && p === "/worlds" ? [fixtures.world as Json] : undefined),
  });
  await page.goto("/");
  await expect(page.locator(".h-display").first()).toBeVisible();
  const h = await colors(page, ".h-display");
  expect(contrast(h.color, h.bg)).toBeGreaterThanOrEqual(7);
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${SHOTS}/fe-36-home-light.png` });
});

test("graphs update live from a streamed turn and stay visible (current place moves, ties change)", async ({
  page,
}) => {
  const st = await mockApi(page);
  const comps = (fixtures.ui as unknown as { components: Json[] }).components;
  const map = structuredClone(comps.find((c) => c.type === "map")!) as Json & { openui: string };
  map.openui = map.openui.replace(/"loc_3"\)\s*$/m, '"loc_4")');
  const rel = structuredClone(comps.find((c) => c.type === "relationship_graph")!) as Json & {
    openui: string;
  };
  rel.openui = rel.openui.replace('type: "初识", affinity: 22', 'type: "盟友", affinity: 70');
  const w = fixtures.world as Json;
  const turn = {
    ...(fixtures.turns[0] as Json),
    id: "t_g2",
    index: 2,
    action: "去巡捕房",
    narration: "你到了巡捕房。",
  };
  let played = false;
  // after the turn the panel re-syncs from GET /ui — serve the updated panels there too
  st.extra = (method, p) =>
    played && method === "GET" && p === `/worlds/${WORLD_ID}/ui`
      ? {
          ...(fixtures.ui as Json),
          components: comps.map((c) => (c.type === "map" ? map : c.type === "relationship_graph" ? rel : c)),
        }
      : undefined;
  st.turnStream = () => (
    (played = true),
    sse([
      ["progress", { stage: "narrate", message: "落笔", pct: 60 }],
      ["token", { text: "你到了巡捕房。" }],
      ["ui", { components: [map, rel] }],
      ["done", { turn, state: { ...(w.state as Json), turn: 2, player_location_id: "loc_4" } }],
    ])
  );
  await page.goto(PLAY);
  const mapFlow = page.getByTestId("ui-map").getByTestId("map-flow");
  await expect(mapFlow.locator('[data-here="true"]')).toContainText("十六铺码头");
  await page.getByTestId("free-input").fill("去巡捕房");
  await page.keyboard.press("Enter");
  await expect(mapFlow.locator('[data-here="true"]')).toContainText("法租界巡捕房");
  const relFlow = page.getByTestId("ui-relationship_graph").getByTestId("relation-flow");
  await expect(relFlow.locator(".rf-tie-label").filter({ hasText: "盟友" })).toBeVisible();
  // React Flow hides nodes it considers unmeasured — rebuilt nodes must keep their measured size
  for (const n of await relFlow.locator(".react-flow__node").all()) await expect(n).toBeVisible();
  for (const n of await mapFlow.locator(".react-flow__node").all()) await expect(n).toBeVisible();
});
