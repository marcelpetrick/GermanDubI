import { expect, type Page, test } from "@playwright/test";

/**
 * Two videos in one session.
 *
 * Adding a second video while the first was being dubbed used to return
 * `500 database is locked`, because the worker held SQLite's write lock for the whole of
 * every stage. This drives the case that broke through the interface.
 *
 * It runs against the deterministic fake providers: what is under test is the queue, the
 * interface and the absence of errors, none of which needs a real model.
 */

const FIRST = "https://www.youtube.com/watch?v=abcdefghijk";
const SECOND = "https://www.youtube.com/watch?v=Wo0KujQEJ_s";

/** Collect anything the browser complains about, so "no warnings" can be asserted. */
function watchForProblems(page: Page): string[] {
  const problems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      problems.push(`console.${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => {
    problems.push(`pageerror: ${error.message}`);
  });
  page.on("response", (response) => {
    // A 500 is what the original defect produced, and it never reaches the console.
    if (response.status() >= 500) {
      problems.push(`http ${response.status()}: ${response.url()}`);
    }
  });
  return problems;
}

async function analyze(page: Page, url: string): Promise<string> {
  await page.goto("/");
  await page.getByLabel("YouTube URL").fill(url);
  await page.getByRole("button", { name: "Analyze" }).click();
  await expect(
    page.getByRole("heading", { name: "Fake narration clip" }),
  ).toBeVisible({ timeout: 30_000 });
  const id = new URL(page.url()).pathname.split("/").pop();
  expect(id, "the browser should be on the new project's page").toBeTruthy();
  return id as string;
}

async function dub(page: Page, id: string): Promise<void> {
  await page.goto(`/projects/${id}`);
  await page.getByRole("button", { name: "Create German dub" }).click();
  await expect(
    page.getByRole("heading", { name: "German preview" }),
  ).toBeVisible({ timeout: 120_000 });
  await expect(
    page.getByRole("link", { name: "Download export" }),
  ).toBeVisible();
}

test("dubs two different videos in one session without errors", async ({
  page,
}) => {
  const problems = watchForProblems(page);

  // The second URL is added while the first project already exists and is being worked on,
  // which is the sequence that used to fail.
  const first = await analyze(page, FIRST);
  await dub(page, first);

  const second = await analyze(page, SECOND);
  await dub(page, second);

  expect(first).not.toEqual(second);

  // Both must still be finished; one completing is not the point. Asserted per project
  // rather than by counting rows, because other specs share this server and their projects
  // are none of this test's business.
  for (const id of [first, second]) {
    await page.goto(`/projects/${id}`);
    await expect(
      page.getByRole("link", { name: "Download export" }),
    ).toBeVisible();
  }

  expect(
    problems,
    `the browser reported problems:\n${problems.join("\n")}`,
  ).toEqual([]);
});

test("clearing everything removes every project and asks first", async ({
  page,
}) => {
  const problems = watchForProblems(page);
  const id = await analyze(page, FIRST);
  await dub(page, id);

  // Stop is not asserted here. With the fake providers a stage finishes in milliseconds,
  // so catching the button while work is in progress is a race, and a conditional
  // assertion is one that can pass by never running. Cancellation is covered
  // deterministically in backend/tests/integration/test_worker_concurrency.py, where a
  // stage is held open on purpose.
  await page.goto("/");
  await expect(
    page.getByRole("link", { name: "Fake narration clip" }),
  ).not.toHaveCount(0);

  page.once("dialog", (dialog) => {
    expect(dialog.message()).toContain("cannot be undone");
    void dialog.accept();
  });
  await page.getByRole("button", { name: "Delete everything" }).click();
  await expect(page.getByText("No projects yet")).toBeVisible({
    timeout: 30_000,
  });

  expect(
    problems,
    `the browser reported problems:\n${problems.join("\n")}`,
  ).toEqual([]);
});
