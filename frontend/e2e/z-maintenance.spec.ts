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
  await page.getByLabel("向前推进秒数").fill("172801");
  await page
    .getByText("已核对为专用合成数据库，理解时钟对全部患者生效", {
      exact: true,
    })
    .click();
  const clockResponse = page.waitForResponse((r) =>
    r.url().endsWith("/automation/clock"),
  );
  await page.getByRole("button", { name: "确认推进演示时钟" }).click();
  const clock = await (await clockResponse).json();
  expect(clock.clock_offset_seconds).toBe(172801);
  try {
    await page
      .getByText("确认执行当前到期作业；real模式可能触发收费模型", {
        exact: true,
      })
      .click();
    const tickResponse = page.waitForResponse((r) =>
      r.url().endsWith("/automation/tick"),
    );
    await page.getByRole("button", { name: "确认执行一次 tick" }).click();
    const tick = await (await tickResponse).json();
    expect((await tickResponse).status()).toBe(200);
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
