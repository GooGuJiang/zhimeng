/**
 * 结局海报 · 分享 dialog (mocked API, 1920×1080): opaque dialog, readable secondary button, header
 * never overlaps the poster, and the exported PNG is a solid card (no transparent corners), light + dark.
 * Screenshots → docs/screens/fe-41-poster-dialog.png, fe-42-poster-export.png (exported sample).
 */
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { WORLD_ID, mockApi } from "./mock-api";

const SHOTS = path.resolve(__dirname, "../../docs/screens");
test.use({ viewport: { width: 1920, height: 1080 }, acceptDownloads: true });

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

/** RGBA of the four corner pixels of a PNG (decoded in the browser) */
const corners = (page: Page, b64: string) =>
  page.evaluate(async (src) => {
    const img = new Image();
    img.src = src;
    await img.decode();
    const c = document.createElement("canvas");
    c.width = img.naturalWidth;
    c.height = img.naturalHeight;
    const g = c.getContext("2d")!;
    g.drawImage(img, 0, 0);
    const px = (x: number, y: number) => Array.from(g.getImageData(x, y, 1, 1).data);
    return {
      w: c.width,
      h: c.height,
      px: [px(0, 0), px(c.width - 1, 0), px(0, c.height - 1), px(c.width - 1, c.height - 1)],
    };
  }, `data:image/png;base64,${b64}`);

for (const theme of ["light", "dark"] as const)
  test(`poster dialog is opaque and exports a solid PNG (${theme})`, async ({ page }) => {
    if (theme === "dark")
      await page.addInitScript(() =>
        localStorage.setItem("zhimeng.prefs", JSON.stringify({ theme: "dark" })),
      );
    await mockApi(page);
    await page.goto(`/play/${WORLD_ID}`);
    await page.getByTestId("poster-btn").click();
    const dlg = page.getByRole("dialog", { name: "结局海报 · 分享" });
    const poster = dlg.getByTestId("poster");
    await expect(poster).toBeVisible();
    await page.waitForTimeout(600);
    // no visible AI label on the poster/dialog unless NEXT_PUBLIC_ZM_SHOW_AI_LABEL=1 (user request)
    if (!["1", "true"].includes(process.env.NEXT_PUBLIC_ZM_SHOW_AI_LABEL ?? ""))
      await expect(dlg).not.toContainText("AI");

    const alpha = await dlg.evaluate(
      (el) => (getComputedStyle(el).backgroundColor.match(/[\d.]+/g) ?? []).length,
    );
    expect(alpha).toBe(3); // rgb(), not rgba() → opaque
    const head = (await dlg.locator(".dialog-h").boundingBox())!;
    expect((await poster.boundingBox())!.y).toBeGreaterThanOrEqual(head.y + head.height);
    const ghost = await dlg.getByTestId("video-btn").evaluate((el) => ({
      fg: getComputedStyle(el).color,
      bg: getComputedStyle(el).backgroundColor,
    }));
    expect(contrast(ghost.fg, ghost.bg)).toBeGreaterThanOrEqual(4.5);
    if (theme === "light") await page.screenshot({ path: `${SHOTS}/fe-41-poster-dialog.png` });

    const [dl] = await Promise.all([
      page.waitForEvent("download"),
      dlg.getByTestId("poster-download").click(),
    ]);
    const file = await dl.path();
    const b64 = fs.readFileSync(file).toString("base64");
    const info = await corners(page, b64);
    expect(info.w).toBeGreaterThanOrEqual(700); // pixelRatio 2
    for (const p of info.px) expect(p[3]).toBe(255); // opaque corners
    if (theme === "light") fs.copyFileSync(file, `${SHOTS}/fe-42-poster-export.png`);
  });
