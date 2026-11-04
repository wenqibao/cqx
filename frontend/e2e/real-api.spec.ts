import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";
test("真实后端：录入→自动触发→轨迹→任务完成→复评", async ({
  page,
  request,
}) => {
  const before = await request.get(
    "http://127.0.0.1:8000/api/patients/P002/state",
  );
  const p2 = await before.json();
  const agentPosts: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().includes("/agent/runs"))
      agentPosts.push(r.url());
  });
  await page.goto("/");
  await expect(page.locator("header")).toContainText("后端已连接");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("张伟");
  await page.screenshot({
    path: "docs/evidence/overview-1440.png",
    fullPage: true,
  });
  await page
    .getByRole("navigation")
    .getByRole("link", { name: "健康数据", exact: true })
    .click();
  await page.getByLabel("记录数值", { exact: true }).fill("9.61");
  // Unique minute avoids a dedupe hit on repeated test runs, without changing backend rules.
  await page
    .getByLabel("记录时间（本地时间，留空使用后端演示时钟）")
    .fill(
      new Date(Date.now() + Math.random() * 600000).toISOString().slice(0, 16),
    );
  const savedResponse = page.waitForResponse(
    (r) =>
      r.url().endsWith("/patients/P001/records") &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "保存并查看自动触发结果" }).click();
  const response = await savedResponse;
  expect(response.status()).toBe(201);
  const saved = await response.json();
  expect(saved.record.patient_id).toBe("P001");
  expect(saved.automation).not.toBeNull();
  expect(saved.automation.events_created.length).toBeGreaterThan(0);
  expect(saved.automation.runs.length).toBeGreaterThan(0);
  await expect(page.getByTestId("write-result")).toContainText(
    String(saved.record.id),
  );
  const runs = await (
    await request.get("http://127.0.0.1:8000/api/patients/P001/runs")
  ).json();
  expect(runs.items.length).toBeGreaterThan(0);
  const runId = saved.automation.runs[0].run_id;
  await page.goto(`/runs?run=${runId}`);
  await expect(page.getByRole("dialog")).toContainText(runId);
  await expect(page.getByRole("dialog")).toContainText("tool_call");
  await page.screenshot({
    path: "docs/evidence/trace-1440.png",
    fullPage: true,
  });
  await page.keyboard.press("Escape");
  await page
    .getByRole("navigation")
    .getByRole("link", { name: "健康任务", exact: true })
    .click();
  const tasks = await (
    await request.get("http://127.0.0.1:8000/api/patients/P001/tasks")
  ).json();
  const target = tasks.items.find((t: { status: string }) =>
    ["pending", "missed"].includes(t.status),
  );
  expect(target).toBeTruthy();
  await page
    .getByRole("row")
    .filter({ hasText: target.title })
    .getByRole("button", { name: "标记完成" })
    .click();
  const completion = page.waitForResponse((r) =>
    r.url().endsWith(`/tasks/${target.id}/complete`),
  );
  await page.getByRole("button", { name: /确\s*定/ }).click();
  const complete = await (await completion).json();
  expect(complete.task.status).toBe("done");
  expect(Array.isArray(complete.reviews)).toBe(true);
  await expect(page.getByTestId("write-result")).toContainText("reviews");
  const actual = await (
    await request.get(`http://127.0.0.1:8000/api/patients/P001/tasks`)
  ).json();
  expect(
    actual.items.find((t: { id: string }) => t.id === target.id).status,
  ).toBe("done");
  expect(agentPosts).toEqual([]);
  const after = await (
    await request.get("http://127.0.0.1:8000/api/patients/P002/state")
  ).json();
  expect(after.latest).toEqual(p2.latest);
  await fs.mkdir("docs/evidence", { recursive: true });
  await fs.writeFile(
    "docs/evidence/real-api.json",
    JSON.stringify(
      { saved, runId, complete, agentPosts, patientIsolation: true },
      null,
      2,
    ),
  );
  await page.screenshot({
    path: "docs/evidence/tasks-completed-1440.png",
    fullPage: true,
  });
});
test("患者切换及笔记本尺寸页面", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("张伟");
  await page.getByLabel("当前演示患者").click();
  await page.getByText("李秀英（虚构） · P002", { exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("李秀英");
  for (const path of ["/", "/records", "/tasks", "/runs"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  await page.screenshot({
    path: "docs/evidence/laptop-1366.png",
    fullPage: true,
  });
});
test("后端断连明确报错且无静态患者回退", async ({ page }) => {
  await page.route("http://127.0.0.1:8000/api/**", (r) => r.abort("connectionrefused"));
  await page.goto("/");
  await expect(page.locator("header")).toContainText("后端连接失败");
  await expect(page.getByRole("alert")).toContainText("未切换前端模拟数据");
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(0);
  await page.screenshot({
    path: "docs/evidence/backend-offline.png",
    fullPage: true,
  });
});
