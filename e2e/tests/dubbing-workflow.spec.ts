import { expect, test } from "@playwright/test";

test("creates, dubs, corrects, and approves one segment", async ({ page }) => {
  await page.goto("/");
  await page
    .getByLabel("YouTube URL")
    .fill("https://www.youtube.com/watch?v=abcdefghijk");
  await page.getByRole("button", { name: "Analyze" }).click();

  await expect(
    page.getByRole("heading", { name: "Fake narration clip" }),
  ).toBeVisible({
    timeout: 30_000,
  });
  await page.getByRole("button", { name: "Create German dub" }).click();

  await expect(
    page.getByRole("heading", { name: "German preview" }),
  ).toBeVisible({
    timeout: 90_000,
  });
  await expect(
    page.getByRole("heading", { name: "Review segments" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Download export" }),
  ).toBeVisible();

  const translation = page.getByLabel("German translation");
  await translation.fill("Das Timing ist besonders wichtig.");
  await page.getByRole("button", { name: "Save German & regenerate" }).click();

  await expect(
    page.getByRole("heading", { name: "German preview" }),
  ).toBeVisible({
    timeout: 90_000,
  });
  await expect(page.getByLabel("German translation")).toHaveValue(
    "Das Timing ist besonders wichtig.",
  );
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(
    page.getByText("approved", { exact: true }).last(),
  ).toBeVisible();
});
