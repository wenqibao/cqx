import { test, expect } from "@playwright/test";
import { BASE, evidence, fixture, json, visit } from "./helpers";
test("隔离演示时钟与tick产生实际缺数据复评 [F07 F12]", async ({
  page,
  request,
}) => {
  const pid = await fixture(request, "到期复评", { rising: true });
  const saved = await (
    await request.post(BASE + `/patients/${pid}/records`, {
      data: { kind: "fasting_glucose", value: 9.6, trigger_agent: true },
    })
  ).json();
  expect(saved.automation.runs.length).toBeGreaterThan(0);
  await visit(page, "/system?tab=maintenance", pid);
  await expect(page.getByRole("tab", { name: "API 与持久化" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tab", { name: "本地演示维护" })).toHaveCount(0);
  const clockResponse = await request.post(BASE + "/automation/clock", {
    data: { advance_seconds: 172801 },
  });
  expect(clockResponse.ok()).toBe(true);
  const clock = await clockResponse.json();
  expect(clock.clock_offset_seconds).toBe(172801);
  try {
    const tickResponse = await request.post(BASE + "/automation/tick", {
      data: { limit: 50 },
    });
    expect(tickResponse.ok()).toBe(true);
    const tick = await tickResponse.json();
    const reviews = await json(request, `/patients/${pid}/reviews`);
    expect(
      reviews.items.some(
        (r: { branch: string }) => r.branch === "MISSING_DATA",
      ),
    ).toBe(true);
    await visit(page, "/tasks?tab=reviews", pid);
    await expect(page.locator("main")).toContainText("缺少数据");
    const jobs = await json(request, "/automation/jobs");
    expect(
      jobs.items.some((j: { status: string }) => j.status === "done"),
    ).toBe(true);
    await evidence("maintenance-api", { pid, clock, tick, reviews, jobs });
    await page.screenshot({
      path: "docs/evidence/workbench/missing-data-review.png",
      fullPage: true,
    });
  } finally {
    await request.post(BASE + "/automation/clock", { data: { reset: true } });
  }
});
