/**
 * User request: no visible AI declarations by default (NEXT_PUBLIC_ZM_SHOW_AI_LABEL unset). Scans visible
 * text, document title and accessible attributes (aria-label / alt / title / placeholder) of the main pages.
 * The backend still sends ai_label / ai_generated — they must not surface either.
 */
import { expect, test, type Page } from "@playwright/test";
import { WORLD_ID, mockApi } from "./mock-api";

const ON = ["1", "true", "yes", "on"].includes(
  (process.env.NEXT_PUBLIC_ZM_SHOW_AI_LABEL ?? "").toLowerCase(),
);
const AI = /\bAI\b|AI(?=[\u4e00-\u9fa5])|(?<=[\u4e00-\u9fa5\s])AI|人工智能/;

async function aiHits(page: Page) {
  return page.evaluate((src) => {
    const re = new RegExp(src);
    const hits: string[] = [];
    if (re.test(document.title)) hits.push(`title: ${document.title}`);
    if (re.test(document.body.innerText)) {
      for (const line of document.body.innerText.split("\n")) if (re.test(line)) hits.push(`text: ${line}`);
    }
    for (const el of Array.from(document.querySelectorAll("[aria-label],[alt],[title],[placeholder]"))) {
      for (const a of ["aria-label", "alt", "title", "placeholder"]) {
        const v = el.getAttribute(a);
        if (v && re.test(v)) hits.push(`${a}: ${v}`);
      }
    }
    return hits;
  }, AI.source);
}

test.skip(ON, "AI labels are switched on for this build");

for (const [name, path] of [
  ["home", "/"],
  ["education", "/education"],
  ["play", `/play/${WORLD_ID}`],
] as const) {
  test(`no visible AI wording: ${name}`, async ({ page }) => {
    await mockApi(page);
    await page.goto(path);
    if (name === "play") await expect(page.locator('article[data-turn="1"]')).toBeVisible();
    else await page.waitForLoadState("networkidle");
    await page.waitForTimeout(800);
    expect(await aiHits(page)).toEqual([]);
    await expect(page.locator('[data-testid^="ai-label"]')).toHaveCount(0);
  });
}
