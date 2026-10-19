/**
 * 世界记忆 drawer + 记忆 page (mocked API, 1920×1080): the 回忆 button never wraps, the loading state
 * shows a spinner beside the label, and [n] citation markers become badges that jump to their 出处.
 * Screenshot → docs/screens/fe-40-memory-query.png.
 */
import path from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { WORLD_ID, mockApi } from "./mock-api";

const SHOTS = path.resolve(__dirname, "../../docs/screens");
test.use({ viewport: { width: 1920, height: 1080 } });

const answer = {
  answer: "线人叫**老周**[1]。他后来为了护住码头兄弟被牵连，悄悄去了码头仓库[2][3]。",
  ai_label: "内容由AI生成",
  citations: [
    {
      fact_id: "f1",
      chapter: 1,
      turn: 1,
      source: "第1章·第1回合",
      content: "你去码头仓库找线人，老周压低声音说：小心身边的人。",
    },
    {
      fact_id: "f2",
      chapter: 1,
      turn: 3,
      source: "第1章·第3回合",
      content: "老周为了护码头兄弟不被牵连，悄悄去了码头仓库寻找什么。",
    },
    { fact_id: "f3", chapter: 1, turn: 4, source: "第1章·第4回合", content: "你来到了码头仓库，铁门半掩。" },
  ],
};

async function mock(page: Page, delay = 1200) {
  await mockApi(page, {
    extra: async (method, p) => {
      if (method === "POST" && p === `/worlds/${WORLD_ID}/memory/query`) {
        await new Promise((r) => setTimeout(r, delay));
        return answer;
      }
      return undefined;
    },
  });
}

const SHOW_AI_LABEL = ["1", "true", "yes", "on"].includes(
  (process.env.NEXT_PUBLIC_ZM_SHOW_AI_LABEL ?? "").toLowerCase(),
);

async function checkButton(btn: Locator) {
  const box = (await btn.boundingBox())!;
  expect(box.height).toBeLessThanOrEqual(46); // one line, never 回/忆 stacked
  expect(box.width).toBeGreaterThanOrEqual(80);
  expect(await btn.evaluate((el) => getComputedStyle(el).whiteSpace)).toBe("nowrap");
}

async function askAndCheck(page: Page, scope: Locator, shot?: string) {
  await scope.getByTestId("memory-query-input").fill("第一回合我在码头遇到的线人叫什么？");
  const btn = scope.getByTestId("memory-query-btn");
  await checkButton(btn);
  await btn.click();
  await expect(btn).toHaveAttribute("aria-busy", "true");
  await expect(btn.locator("svg.spin")).toBeVisible();
  await checkButton(btn);
  // spinner sits beside the label, not on top of it
  const [icon, label] = [
    (await btn.locator("svg").boundingBox())!,
    (await btn.locator("span").boundingBox())!,
  ];
  expect(icon.x + icon.width).toBeLessThanOrEqual(label.x + 1);
  const ans = scope.getByTestId("memory-answer");
  await expect(ans).toBeVisible();
  await expect(ans.locator(".answer")).not.toContainText("[1]");
  await expect(ans.locator(".cite-ref a")).toHaveCount(3);
  await ans.locator(".cite-ref a").nth(1).click();
  await expect(ans.locator('[data-cite-card="2"]')).toHaveClass(/hot/);
  // visible AI badges follow NEXT_PUBLIC_ZM_SHOW_AI_LABEL (hidden by default, user request)
  await expect(page.locator('[data-testid^="ai-label"]')).toHaveCount(SHOW_AI_LABEL ? 1 : 0);
  if (shot) await page.screenshot({ path: shot });
}

test("世界记忆 drawer on the play page", async ({ page }) => {
  await mock(page);
  await page.goto(`/play/${WORLD_ID}`);
  await page.getByTestId("memory-tab").click();
  const drawer = page.getByRole("complementary", { name: "世界记忆" });
  await askAndCheck(page, drawer, `${SHOTS}/fe-40-memory-query.png`);
});

test("记忆 page uses the same query box", async ({ page }) => {
  await mock(page, 300);
  await page.goto(`/memory/${WORLD_ID}`);
  await askAndCheck(page, page.locator("main"));
});
