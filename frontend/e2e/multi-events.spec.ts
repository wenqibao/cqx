import fs from "node:fs/promises";
import { test, expect } from "@playwright/test";
import { BASE, evidence, fixture, json, visit } from "./helpers";
test("多事件协调保留实际优先序列、任务与去重依据 [F05 F09 F22]", async ({
  page,
  request,
}) => {
  const pid = await fixture(request, "多事件", {
    rising: true,
    missingMedication: true,
    missingSteps: true,
  });
  const health = await json(request, "/health");
  const now = Date.parse(health.time);
  for (const [kind, value, days] of [
    ["steps", 1000, 1],
    ["steps", 800, 0],
    ["medication_taken", 0, 1],
    ["medication_taken", 0, 0],
  ] as const) {
    expect(
      (
        await request.post(BASE + `/patients/${pid}/records`, {
          data: {
            kind,
            value,
            recorded_at: new Date(now - days * 86400000).toISOString(),
            trigger_agent: false,
          },
        })
      ).status(),
    ).toBe(201);
  }
  await visit(page, "/monitoring?tab=events", pid);
  const scanned = page.waitForResponse((r) =>
    r.url().endsWith(`/patients/${pid}/events/scan`),
  );
  await page.getByRole("button", { name: "演示：手动扫描事件" }).click();
  await page.getByRole("button", { name: /确\s*定/ }).click();
  const scan = await (await scanned).json();
  expect(scan.created.length).toBeGreaterThanOrEqual(3);
  await expect(page.locator("main")).toContainText("多次未确认服药");
  await expect(page.locator("main")).not.toContainText(
    /MEDICATION_NONADHERENCE|EVT-/,
  );
  await page.getByRole("button", { name: "监测日志", exact: true }).click();
  const monitoringLog = page.getByRole("dialog", {
    name: "技术日志",
    exact: true,
  });
  await expect(monitoringLog.locator("pre")).toContainText(scan.created[0].id);
  await expect(monitoringLog.locator("pre")).toContainText(
    "MEDICATION_NONADHERENCE",
  );
  const downloaded = page.waitForEvent("download");
  await monitoringLog.getByRole("button", { name: "下载日志 JSON" }).click();
  const download = await downloaded;
  const downloadedPath = await download.path();
  expect(downloadedPath).toBeTruthy();
  expect(JSON.parse(await fs.readFile(downloadedPath!, "utf8")).events).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ id: scan.created[0].id }),
    ]),
  );
  await page.keyboard.press("Escape");
  await visit(page, "/agent", pid);
  await page
    .getByLabel("健康管理请求", { exact: true })
    .fill("请综合处理当前健康管理事件，保留实际优先顺序与依据");
  const received = page.waitForResponse((r) =>
    r.url().endsWith(`/patients/${pid}/agent/runs`),
  );
  await page
    .getByRole("button", { name: "运行一次 Agent", exact: true })
    .click();
  const result = await (await received).json();
  expect(result.priority_order.length).toBeGreaterThanOrEqual(3);
  const tasks = await json(request, `/patients/${pid}/tasks`);
  expect(tasks.items.length).toBeGreaterThan(0);
  await visit(page, `/agent?run=${result.run_id}`, pid);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "运行日志", exact: true })
    .click();
  const technical = page.getByRole("dialog", { name: "技术日志", exact: true });
  await expect(technical.locator("pre")).toContainText("priority_order");
  await page.keyboard.press("Escape");
  await evidence("multi-events-api", { pid, scan, result, tasks });
  await page.screenshot({
    path: "docs/evidence/workbench/multi-events.png",
    fullPage: true,
  });
});
