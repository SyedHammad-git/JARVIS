import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, devices: [] }),
    });
  });
});

test("home renders every landing section and switches themes", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1, name: /Your AI/ })).toBeVisible();
  await expect(page.locator('meta[property="og:image"]')).toHaveAttribute("content", /\/opengraph-image/);
  await expect(page.locator("#features article")).toHaveCount(4);
  await expect(page.getByRole("heading", { name: "Connect your devices" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Choose an AI model" })).toBeVisible();
  await expect(page.getByText("Groq", { exact: true })).toBeVisible();
  await expect(page.getByText("Gemini", { exact: true })).toBeVisible();
  await expect(page.getByText("OpenRouter", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Smart camera access" })).toBeVisible();
  await expect(page.locator(".install-steps li")).toHaveCount(4);
  await expect(page.getByRole("link", { name: "Privacy (draft)" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Terms (draft)" })).toBeVisible();

  const themeToggle = page.getByRole("button", { name: /Switch to .* theme/ }).first();
  await expect(themeToggle).toBeVisible();
  await themeToggle.click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.getByRole("button", { name: "Switch to light theme" }).first()).toBeVisible();
});

test("Try JARVIS opens Clerk sign-in", async ({ page }) => {
  await page.goto("/");
  const tryButton = page.getByRole("button", { name: "Try JARVIS" });
  await expect(tryButton).toBeEnabled();
  await tryButton.click();
  await expect(page.getByRole("dialog")).toBeVisible({ timeout: 20_000 });
});

test("download page reports unavailable until a release is configured", async ({ page }) => {
  await page.goto("/download");
  await expect(page.getByRole("button", { name: "Coming soon" })).toBeDisabled();
  await expect(page.getByRole("link", { name: "Download installer" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Install and pair" })).toBeVisible();
  await expect(page.locator("ol li")).toHaveCount(4);
});

test("legal pages are present and clearly marked as drafts", async ({ page }) => {
  await page.goto("/privacy");
  await expect(page.getByRole("heading", { name: "Privacy notice" })).toBeVisible();
  await expect(page.getByText("Draft — review before launch")).toBeVisible();

  await page.goto("/terms");
  await expect(page.getByRole("heading", { name: "Terms of service" })).toBeVisible();
  await expect(page.getByText("Draft — review before launch")).toBeVisible();
});

test("mobile layout keeps navigation and primary actions usable", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");

  await expect(page.locator("summary[aria-label='Open navigation menu']")).toBeVisible();
  await page.locator("summary[aria-label='Open navigation menu']").click();
  await expect(page.locator(".mobile-menu nav").getByRole("link", { name: "Download" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Try JARVIS" })).toBeVisible();
  const hasNoHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  );
  expect(hasNoHorizontalOverflow).toBe(true);
});
