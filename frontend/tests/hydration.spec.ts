/**
 * AUTH-QA-4 sweep: no hydration errors and no invalid DOM nesting (e.g. <div> inside <p>) on any page, including
 * states that only appear after interaction (password meter, field errors, 个人中心 tabs, the user menu).
 * React reports both through console.error ("In HTML, <div> cannot be a descendant of <p>…",
 * "Hydration failed…"), so we listen to console + pageerror and assert none match.
 */
import { expect, test, type Page } from "@playwright/test";
import { WORLD_ID, mockApi } from "./mock-api";
import { mockAuth, signedIn } from "./auth-mock";

const BAD = /hydrat|cannot be a descendant of|cannot contain a nested|cannot be a child of|did not match|server rendered (HTML|text)|validateDOMNesting/i;

function watch(page: Page) {
  const hits: string[] = [];
  page.on("console", (m) => {
    if ((m.type() === "error" || m.type() === "warning") && BAD.test(m.text())) hits.push(`${m.type()}: ${m.text().slice(0, 300)}`);
  });
  page.on("pageerror", (e) => {
    if (BAD.test(String(e))) hits.push(`pageerror: ${String(e).slice(0, 300)}`);
  });
  return hits;
}

const settle = async (page: Page) => {
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(400);
};

test("auth pages (with meter, field and server errors)", async ({ page }) => {
  const hits = watch(page);
  await mockApi(page);
  await mockAuth(page);
  await page.goto("/register");
  await settle(page);
  await page.getByTestId("register-password").fill("abc"); // password meter + hint
  await page.getByTestId("register-username").fill("1x");
  await page.getByTestId("register-submit").click(); // field errors
  await settle(page);
  await page.goto("/login");
  await settle(page);
  await page.getByTestId("login-username").fill("nobody");
  await page.getByTestId("login-password").fill("Wrong12345");
  await page.getByTestId("login-submit").click(); // server error banner
  await settle(page);
  await page.goto("/");
  await settle(page);
  expect(hits).toEqual([]);
});

test("个人中心 every tab + user menu (signed in)", async ({ page }) => {
  const hits = watch(page);
  await mockApi(page);
  await signedIn(page);
  for (const t of ["overview", "profile", "security", "works", "learning", "prefs"]) {
    await page.goto(`/me?tab=${t}`); // full load each time: hydration is checked per tab
    await expect(page.getByTestId("me-page")).toBeVisible();
    await settle(page);
  }
  await page.getByTestId("user-menu-btn").click();
  await expect(page.getByTestId("user-menu")).toBeVisible();
  expect(hits).toEqual([]);
});

test("demo mode 个人中心 (auth_required=false, anonymous)", async ({ page }) => {
  const hits = watch(page);
  await mockApi(page);
  await mockAuth(page);
  for (const t of ["overview", "profile", "security", "prefs"]) {
    await page.goto(`/me?tab=${t}`);
    await settle(page);
  }
  expect(hits).toEqual([]);
});

for (const path of ["/", "/education", "/saves", "/settings", "/memory", "/god", `/play/${WORLD_ID}`, `/preview/${WORLD_ID}`, `/god/${WORLD_ID}`, `/memory/${WORLD_ID}`]) {
  test(`world pages: ${path}`, async ({ page }) => {
    const hits = watch(page);
    await mockApi(page);
    await signedIn(page);
    await page.goto(path);
    await settle(page);
    await page.waitForTimeout(600);
    expect(hits).toEqual([]);
  });
}
