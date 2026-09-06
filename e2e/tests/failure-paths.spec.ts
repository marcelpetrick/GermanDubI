import { expect, test } from "@playwright/test";

/**
 * The half of the interface the other two specs never reach.
 *
 * Both existing specs drive a dub that works. A stage that fails and a run that is
 * stopped are where the interface has the most to say and the most to get wrong, and
 * where "a spinner forever" is the failure people actually report. The fake downloader
 * fails deliberately for a marked source so this can be driven end to end.
 */

const FAILING = "https://www.youtube.com/watch?v=germandubi-fail";
const WORKING = "https://www.youtube.com/watch?v=abcdefghijk";

test("a stage that fails says so, and offers a way on", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("YouTube URL").fill(FAILING);
  await page.getByRole("button", { name: "Analyze" }).click();

  // Inspection succeeds -- the marked source only fails once the dub tries to fetch it,
  // which is deliberately deeper than the first stage.
  await expect(
    page.getByRole("heading", { name: "Fake narration clip" }),
  ).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Create German dub" }).click();

  // What matters is that the failure surfaces rather than leaving a bar turning.
  await expect(page.getByText(/failed/i).first()).toBeVisible({
    timeout: 60_000,
  });

  // An explanation, not just a state: the reason the stage gave has to reach the reader,
  // and it has to be attached to the stage that produced it rather than floating free.
  // Asserted by where it appears, not by how many times -- the same sentence is rendered
  // in more than one place and counting them pins something nobody meant to promise.
  await expect(page.getByText(/marked to fail/i).first()).toBeVisible({
    timeout: 30_000,
  });
  await expect(
    page
      .getByRole("listitem")
      .filter({ hasText: "Downloading media" })
      .getByText(/marked to fail/i),
  ).toBeVisible();

  // And a way out of the dead end.
  await expect(
    page.getByRole("button", { name: "Resume unfinished work" }),
  ).toBeVisible();
});

test("stopping a run leaves the project explained, not spinning", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("YouTube URL").fill(WORKING);
  await page.getByRole("button", { name: "Analyze" }).click();
  await expect(
    page.getByRole("heading", { name: "Fake narration clip" }),
  ).toBeVisible({ timeout: 30_000 });

  await page.getByRole("button", { name: "Create German dub" }).click();
  await page.getByRole("button", { name: "Stop processing" }).click();

  // Stopping must reach a settled state that says what happened and offers to continue.
  await expect(
    page.getByRole("button", { name: "Resume unfinished work" }),
  ).toBeVisible({ timeout: 60_000 });
});
