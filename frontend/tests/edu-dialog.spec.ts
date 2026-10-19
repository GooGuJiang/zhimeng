/**
 * 学习小结 dialog (mocked API, 1920×1080): opaque paper surface in light + dark, readable section
 * labels, sticky header with the body scrolling inside, compact knowledge cards that flip.
 * Screenshots → docs/screens/fe-38-edu-summary-light.png, fe-39-edu-summary-dark.png.
 */
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { WORLD_ID, fixtures, mockApi, type Json } from "./mock-api";

const SHOTS = path.resolve(__dirname, "../../docs/screens");
test.use({ viewport: { width: 1920, height: 1080 } });

const cards = [
  ["桃花源意象", "桃花源象征远离战乱、人人安居乐业的**理想社会**，寄托了陶渊明对现实的不满。"],
  ["晋代渔猎生活", "“武陵人捕鱼为业”交代人物身份，渔人是连接现实与理想世界的线索人物。"],
  ["自然与人文和谐", "“土地平旷，屋舍俨然”写出秩序井然、人与自然和谐共处的景象。"],
  ["避世思想起源", "“先世避秦时乱”说明桃源人为躲避暴政而来，体现魏晋时期的避世思想。"],
].map(([title, content], i) => ({ id: `kc${i}`, title, content, source: "《桃花源记》" }));

const summary = {
  title: "桃花源记",
  key_points: [
    "桃花源寄托理想社会，反映古代对和平安定生活的向往",
    "东晋渔民以捕鱼为业，沿江行舟，体现底层劳动者真实生活",
    "文中“芳草鲜美，落英缤纷”展现人与自然和谐共生的理想图景",
    "“不足为外人道也”暗示桃源与现实的隔绝",
  ],
  cards,
  timeline: [
    { turn: 1, summary: "你沿溪前行，忽逢桃花林，夹岸数百步，中无杂树。" },
    { turn: 2, summary: "林尽水源，便得一山，山有小口，仿佛若有光。" },
    { turn: 3, summary: "你从口入，豁然开朗，见到屋舍俨然、阡陌交通。" },
  ],
  quiz: [
    {
      question: "《桃花源记》中，“落英缤纷”主要体现了什么意境？",
      options: ["战乱纷飞的现实", "人与自然和谐共生的理想图景", "渔民劳作的艰辛", "时间流逝的无情"],
      answer_index: 1,
      explanation: "落英缤纷描绘了桃花飘落、美景如画的景象，正是人与自然和谐共处的理想画面。",
    },
    {
      question: "桃源人“先世避秦时乱”，说明了什么？",
      options: ["他们是秦朝官员", "他们为躲避战乱而隐居", "他们来自海外", "他们被流放至此"],
      answer_index: 1,
      explanation: "交代桃源来历，突出其与乱世隔绝。",
    },
  ],
  reflection:
    "当你在溪边驻足，是否也渴望一片不被纷扰的宁静？桃花源不仅是避世之境，更是心灵对安宁的永恒追寻。",
  ai_label: "内容由AI生成",
  source: "llm",
  status: "complete",
};

async function open(page: Page) {
  const st = await mockApi(page, {
    extra: (method, p) =>
      method === "GET" && p === `/worlds/${WORLD_ID}/education/summary` ? summary : undefined,
  });
  st.world = { ...(fixtures.world as Json), mode: "education", title: "桃花源记", knowledge_cards: cards };
  await page.goto(`/play/${WORLD_ID}`);
  await page.getByTestId("edu-summary-btn").click();
  const dlg = page.getByRole("dialog", { name: "学习小结" });
  await expect(dlg.getByTestId("edu-summary")).toBeVisible();
  await page.waitForTimeout(500); // pop-in animation
  return dlg;
}

/** effective, fully composited background of an element must be opaque */
const bgAlpha = (page: Page, sel: string) =>
  page
    .locator(sel)
    .first()
    .evaluate((el) => {
      const m = getComputedStyle(el).backgroundColor.match(/[\d.]+/g) ?? [];
      return m.length > 3 ? Number(m[3]) : 1;
    });

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

for (const theme of ["light", "dark"] as const)
  test(`学习小结 dialog is opaque and readable (${theme})`, async ({ page }) => {
    if (theme === "dark")
      await page.addInitScript(() =>
        localStorage.setItem("zhimeng.prefs", JSON.stringify({ theme: "dark" })),
      );
    const dlg = await open(page);
    expect(await bgAlpha(page, ".dialog")).toBe(1);
    expect(await bgAlpha(page, ".dialog .quiz")).toBe(1);
    // section labels: AA against the dialog paper
    const { label, paper } = await dlg
      .locator(".eyebrow")
      .first()
      .evaluate((el) => ({
        label: getComputedStyle(el).color,
        paper: getComputedStyle(el.closest(".dialog")!).backgroundColor,
      }));
    expect(contrast(label, paper)).toBeGreaterThanOrEqual(4.5);

    // header stays put while the body scrolls inside the dialog
    const body = dlg.locator(".dialog-body");
    const headBefore = await dlg.locator(".dialog-h").boundingBox();
    expect(await body.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true);
    await page.screenshot({ path: `${SHOTS}/fe-${theme === "light" ? 38 : 39}-edu-summary-${theme}.png` });
    await body.evaluate((el) => el.scrollTo(0, el.scrollHeight));
    await page.waitForTimeout(200);
    expect((await dlg.locator(".dialog-h").boundingBox())!.y).toBeCloseTo(headBefore!.y, 0);
    expect(await page.evaluate(() => window.scrollY)).toBe(0); // page behind doesn't scroll

    // compact knowledge cards with a preview; flip shows the full explanation
    const card = dlg.getByTestId("knowledge-card").first();
    await expect(card.locator(".zu-kc-peek")).toContainText("桃花源象征");
    expect((await card.boundingBox())!.height).toBeLessThan(170);
    await card.click();
    await expect(card).toHaveAttribute("aria-expanded", "true");
    await page.waitForTimeout(700);
    await expect(card.locator(".zu-kc-back")).toContainText("理想社会");
    await expect(card.locator(".zu-kc-back strong")).toHaveText("理想社会");
    await card.click();
    await expect(card).toHaveAttribute("aria-expanded", "false");

    // quiz still works
    await dlg.getByRole("button", { name: "人与自然和谐共生的理想图景" }).click();
    await expect(dlg).toContainText("✓ 答对了");
  });
