/**
 * v1.3 regression (mocked API): asset pending → in-place upgrade, final placeholders, stream asset
 * upgrades, mid-stream safety block, post-commit narration replacement, long-poll abort on leave.
 */
import { expect, test } from "@playwright/test";
import {
  WORLD_ID,
  fixtures,
  mockApi,
  opening,
  pendingCopy,
  sse,
  upgraded,
  type Asset,
  type Json,
} from "./mock-api";

const PLAY = `/play/${WORLD_ID}`;
const openingFig = (page: import("@playwright/test").Page) => page.locator("article.turn.opening");

test("pending opening image/audio show progress, then upgrade in place via deduped long-poll", async ({
  page,
}) => {
  const st = await mockApi(page);
  const img = opening(st, "image");
  const aud = opening(st, "audio");
  st.assets = st.assets.map((a) => (a.id === img.id || a.id === aud.id ? pendingCopy(a) : a));
  const inflight = new Map<string, number>();
  let maxInflight = 0;
  st.assetGet = async (id, n) => {
    inflight.set(id, (inflight.get(id) ?? 0) + 1);
    maxInflight = Math.max(maxInflight, inflight.get(id)!);
    await new Promise((r) => setTimeout(r, 900));
    inflight.set(id, inflight.get(id)! - 1);
    const base = st.assets.find((a) => a.id === id)!;
    return n < 3 ? base : upgraded(base);
  };
  await page.goto(PLAY);
  const fig = openingFig(page);
  await expect(fig.getByTestId("illustration-pending")).toBeVisible();
  await expect(fig.getByTestId("audio-pending")).toBeVisible();
  await expect(fig.getByTestId("illustration")).toHaveAttribute("data-version", "2", { timeout: 15_000 });
  await expect(fig.getByTestId("illustration")).toHaveAttribute("src", /_real\.svg\?v=2$/);
  await expect(fig.getByTestId("illustration-pending")).toHaveCount(0);
  await expect(fig.getByTestId("audio-player")).toHaveAttribute("src", /\?v=2$/);
  await expect(fig.getByTestId("audio-pending")).toHaveCount(0);
  expect(maxInflight).toBe(1); // never two concurrent long-polls for one id
  const polls = st.log.filter((l) => l.path.startsWith("/assets/")).length;
  await page.waitForTimeout(2500);
  expect(st.log.filter((l) => l.path.startsWith("/assets/")).length).toBe(polls); // stopped once ready
});

test("ready + fallback is a final placeholder: no polling, offers 重新生成 which upgrades", async ({
  page,
}) => {
  const st = await mockApi(page);
  const img = opening(st, "image");
  st.assets = st.assets.map((a) => (a.id === img.id ? { ...a, status: "ready", source: "fallback" } : a));
  let regenerated: Asset | null = null;
  st.extra = (method, path) => {
    if (method === "POST" && path === `/assets/${img.id}/regenerate`) {
      regenerated = { ...img, status: "pending", source: "fallback", version: 2 };
      return regenerated;
    }
  };
  st.assetGet = (id) => (regenerated && id === img.id ? upgraded(regenerated, 3) : null);
  await page.goto(PLAY);
  const fig = openingFig(page);
  await expect(fig.getByTestId("illustration-placeholder")).toBeVisible();
  await page.waitForTimeout(1500);
  expect(st.log.some((l) => l.path === `/assets/${img.id}`)).toBe(false);
  await fig.getByTestId("regen-image-btn").click();
  await expect(fig.getByTestId("illustration")).toHaveAttribute("data-version", "3", { timeout: 10_000 });
  await expect(fig.getByTestId("illustration-placeholder")).toHaveCount(0);
});

test("audio upgrade waits while playing, swaps after it ends", async ({ page }) => {
  const st = await mockApi(page);
  const aud = opening(st, "audio");
  st.assets = st.assets.map((a) => (a.id === aud.id ? { ...a, status: "ready", source: "dashscope" } : a));
  await page.goto(PLAY);
  const player = openingFig(page).getByTestId("audio-player");
  await expect(player).toBeAttached();
  const before = await player.getAttribute("src");
  // pretend it is playing, then deliver an upgrade (same id, v2) through a turn stream's asset event
  await player.evaluate((el: HTMLAudioElement) => {
    Object.defineProperty(el, "paused", { configurable: true, get: () => false });
  });
  const up = upgraded(st.assets.find((a) => a.id === aud.id)!);
  st.turnStream = () =>
    sse([
      ["asset", up],
      ["done", { blocked: true }],
    ]);
  await page.getByRole("textbox").last().fill("听一听");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(800);
  expect(await player.getAttribute("src")).toBe(before); // not swapped mid-playback
  await expect(player).toHaveAttribute("data-version", "2"); // …but the newer version is known
  await player.evaluate((el: HTMLAudioElement) => {
    Object.defineProperty(el, "paused", { configurable: true, get: () => true });
    el.dispatchEvent(new Event("ended"));
  });
  await expect(player).toHaveAttribute("src", /\?v=2$/);
});

test("turn stream: asset events upgrade older assets in place; this turn's pending media is polled after done", async ({
  page,
}) => {
  const st = await mockApi(page);
  const img = opening(st, "image");
  st.assets = st.assets.map((a) => (a.id === img.id ? pendingCopy(a) : a));
  const newImg: Asset = {
    ...pendingCopy(img),
    id: "ast_new_turn_img",
    turn_id: "t_mock2",
    url: "/api/static/assets/new.svg",
  };
  st.assetGet = async (id, n) => {
    if (id === img.id) {
      await new Promise((r) => setTimeout(r, 8000)); // the stream's asset event wins
      return st.assets.find((a) => a.id === id)!;
    }
    if (id === newImg.id) return n < 2 ? newImg : upgraded(newImg);
    return null;
  };
  const w = fixtures.world as Json;
  const turn = {
    ...(fixtures.turns[0] as Json),
    id: "t_mock2",
    index: 2,
    action: "我去巡捕房",
    narration: "巡捕房里灯火通明。",
  };
  st.turnStream = () =>
    sse([
      ["progress", { stage: "narrate", message: "落笔", pct: 60 }],
      ["token", { text: "巡捕房里" }],
      ["asset", upgraded(img)],
      ["token", { text: "灯火通明。" }],
      ["asset", newImg],
      ["options", { options: [{ id: "o1", text: "继续" }] }],
      ["done", { turn, state: w.state }],
    ]);
  await page.goto(PLAY);
  await expect(openingFig(page).getByTestId("illustration-pending")).toBeVisible();
  await page.getByRole("textbox").last().fill("我去巡捕房");
  await page.keyboard.press("Enter");
  await expect(openingFig(page).getByTestId("illustration")).toHaveAttribute("data-version", "2");
  await expect(openingFig(page).getByTestId("illustration-pending")).toHaveCount(0);
  const latest = page.locator('article[data-turn="2"]');
  await expect(latest).toContainText("灯火通明");
  await expect(latest.getByTestId("illustration")).toHaveAttribute("data-version", "2", { timeout: 10_000 });
});

test("safety block after partial tokens discards shown + buffered narration, nothing committed", async ({
  page,
}) => {
  const st = await mockApi(page);
  const long = "半截旁白XYZ".repeat(60);
  st.turnStream = () =>
    sse([
      ["progress", { stage: "narrate", message: "落笔", pct: 60 }],
      ["token", { text: long }],
      [
        "safety",
        {
          allowed: false,
          blocked: true,
          crisis: false,
          categories: ["violence"],
          rating: "teen",
          message: "这个行动不适合继续，换个方向吧。",
        },
      ],
      ["token", { text: "不应出现的尾巴QQQ" }],
      ["done", { blocked: true }],
    ]);
  await page.goto(PLAY);
  await expect(page.locator('article[data-turn="1"]')).toBeVisible();
  const turnsBefore = await page.locator("article.turn[data-turn]").count();
  await page.getByRole("textbox").last().fill("越界的行动");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("safety-notice")).toBeVisible();
  await page.waitForTimeout(1500);
  await expect(page.locator("main")).not.toContainText("XYZ");
  await expect(page.locator("main")).not.toContainText("QQQ");
  expect(await page.locator("article.turn[data-turn]").count()).toBe(turnsBefore);
  expect(await page.evaluate((id) => localStorage.getItem(`zhimeng.pending.${id}`), WORLD_ID)).toBeNull();
});

test("post-commit narration replacement: server copy wins on tab return and on reload", async ({ page }) => {
  const st = await mockApi(page);
  const orig = String((fixtures.turns[0] as Json).narration);
  await page.goto(PLAY);
  await expect(page.locator('article[data-turn="1"]')).toContainText(orig.slice(0, 12));
  st.turns = st.turns.map((t, i) =>
    i === 0 ? { ...t, narration: "【该段内容经复审已替换为安全文本】" } : t,
  );
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await expect(page.locator('article[data-turn="1"]')).toContainText("已替换为安全文本");
  await expect(page.locator('article[data-turn="1"]')).not.toContainText(orig.slice(0, 12));
  await page.reload();
  await expect(page.locator('article[data-turn="1"]')).toContainText("已替换为安全文本");
});

test("leaving the page aborts in-flight long-polls", async ({ page }) => {
  const st = await mockApi(page);
  const img = opening(st, "image");
  st.assets = st.assets.map((a) => (a.id === img.id ? pendingCopy(a) : a));
  st.assetGet = async (id) => {
    await new Promise((r) => setTimeout(r, 6000));
    return st.assets.find((a) => a.id === id)!;
  };
  const aborted: string[] = [];
  page.on(
    "requestfailed",
    (r) => r.url().includes(`/api/assets/${img.id}`) && aborted.push(r.failure()?.errorText ?? ""),
  );
  await page.goto(PLAY);
  await expect.poll(() => st.log.filter((l) => l.path === `/assets/${img.id}`).length).toBeGreaterThan(0);
  await page.getByRole("link", { name: "设置" }).first().click();
  await expect(page).toHaveURL(/\/settings/);
  await expect.poll(() => aborted.length).toBeGreaterThan(0);
  const n = st.log.filter((l) => l.path === `/assets/${img.id}`).length;
  await page.waitForTimeout(7000);
  expect(st.log.filter((l) => l.path === `/assets/${img.id}`).length).toBe(n);
});
