import { test, expect } from "@playwright/test";
import { BASE, evidence, fixture, json, visit } from "./helpers";
test("真实后端：录入→自动触发→轨迹→人工改期→任务完成→复评 [F03 F05 F06 F09 F10 F11 F12 F14 F23 F26]", async ({
  page,
  request,
}) => {
  const pid = await fixture(request, "闭环", { rising: true });
  const before = await json(request, "/patients/P002/state");
  const agentPosts: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().includes("/agent/runs"))
      agentPosts.push(r.url());
  });
  await visit(page, "/monitoring", pid);
  await page.getByLabel("记录数值", { exact: true }).fill("9.6");
  const savedResponse = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      r.url().endsWith(`/patients/${pid}/records`),
  );
  await page.getByRole("button", { name: "保存并查看自动触发结果" }).click();
  const response = await savedResponse;
  expect(response.status()).toBe(201);
  const saved = await response.json();
  expect(saved.record.patient_id).toBe(pid);
  expect(
    saved.automation.events_created.map((e: { code: string }) => e.code),
  ).toContain("GLUCOSE_RISING");
  expect(saved.automation.runs.length).toBeGreaterThan(0);
  expect(agentPosts).toEqual([]);
  const writeResult = page.getByTestId("write-result");
  await expect(writeResult).toContainText("已保存记录");
  await writeResult.getByRole("button", { name: "查看本次操作日志" }).click();
  const writeLog = page.getByRole("dialog", { name: "技术日志", exact: true });
  expect(
    JSON.parse((await writeLog.locator("pre").textContent())!).record.id,
  ).toBe(saved.record.id);
  await page.keyboard.press("Escape");
  const runId = saved.automation.runs[0].run_id;
  await visit(page, `/agent?run=${runId}`, pid);
  const drawer = page.getByRole("dialog");
  await drawer.getByRole("button", { name: "运行日志", exact: true }).click();
  const runTechnical = page.getByRole("dialog", {
    name: "技术日志",
    exact: true,
  });
  await expect(runTechnical.locator("pre")).toContainText(runId);
  await expect(runTechnical.locator("pre")).toContainText('"llm_mode": "mock"');
  await expect(runTechnical.locator("pre")).toContainText("tool_result");
  await page.keyboard.press("Escape");
  await page.screenshot({
    path: "docs/evidence/workbench/trace-mock-1440.png",
    fullPage: true,
  });
  await page.keyboard.press("Escape");
  const tasks = await json(request, `/patients/${pid}/tasks`);
  const target = tasks.items.find(
    (t: { status: string }) => t.status === "pending",
  );
  expect(target).toBeTruthy();
  await visit(page, `/tasks?task=${target.id}`, pid);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "任务日志", exact: true })
    .click();
  await expect(
    page.getByRole("dialog", { name: "技术日志", exact: true }).locator("pre"),
  ).toContainText(target.id);
  await page.keyboard.press("Escape");
  const due = new Date(Date.now() + 2 * 86400000).toISOString().slice(0, 16);
  await page.getByLabel("新的截止时间（本地时间）").fill(due);
  await page
    .getByLabel("工作人员调整原因")
    .fill("合成病例演示，工作人员确认时间");
  const changed = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/tasks/${target.id}/reschedule`) &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "人工确认改期并保存版本" }).click();
  const updated = await (await changed).json();
  expect(updated.task.version).toBeGreaterThan(target.version);
  expect(updated.versions.at(-1).changed_by).toBe("staff_demo");
  await expect(page.getByRole("dialog")).toContainText("医护演示工作人员");
  await page.keyboard.press("Escape");
  await page
    .getByRole("row")
    .filter({ hasText: target.title })
    .getByRole("button", { name: "标记完成" })
    .click();
  const completed = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/tasks/${target.id}/complete`) &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: /确\s*定/ }).click();
  const complete = await (await completed).json();
  expect(complete.task.status).toBe("done");
  expect(
    complete.reviews.some((r: { branch: string }) => r.branch === "CLOSED"),
  ).toBeTruthy();
  const versions = await json(request, `/tasks/${target.id}/versions`);
  expect(versions.versions.at(-1).changed_by).toBe("staff_demo");
  const actual = await json(request, `/tasks/${target.id}`);
  expect(actual.task.status).toBe("done");
  await page.reload();
  await expect(
    page.getByRole("row").filter({ hasText: target.title }),
  ).toContainText("已完成");
  const after = await json(request, "/patients/P002/state");
  expect(after.latest).toEqual(before.latest);
  await evidence("core-api", {
    pid,
    saved,
    runId,
    task: target.id,
    updated,
    complete,
    versions,
    agentPosts,
    patientIsolation: true,
  });
  await page.screenshot({
    path: "docs/evidence/workbench/task-complete-1440.png",
    fullPage: true,
  });
});
test("患者切换及三种桌面尺寸页面 [F01 F02 F04 F15]", async ({ page }) => {
  test.setTimeout(180000);
  await visit(page, "/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("监管总览");
  await expect(page.locator("body")).not.toContainText("我的健康空间");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByLabel("当前演示患者").click();
  await page.getByLabel("当前演示患者").fill("P002");
  await page
    .locator(".ant-select-dropdown:visible")
    .getByText("李秀英（虚构） · P002", { exact: true })
    .click();
  await expect(page.locator("header")).toContainText("李秀英");
  await page.goto("/patients/P002?tab=records");
  await expect(page.locator(".patient-summary")).toContainText("李秀英");
  await page.reload();
  await expect(page.locator(".patient-summary")).toContainText("李秀英");
  await expect(page.locator("main")).not.toContainText("张伟");
  await page
    .getByRole("navigation")
    .getByRole("link", { name: "健康监测", exact: true })
    .click();
  await expect(page.getByLabel("记录类型", { exact: true })).toBeVisible();
  for (const viewport of [
    { width: 1920, height: 1080 },
    { width: 1440, height: 900 },
    { width: 1366, height: 768 },
  ]) {
    await page.setViewportSize(viewport);
    for (const path of [
      "/",
      "/patients",
      "/monitoring",
      "/followups",
      "/tasks",
      "/agent",
      "/agent/knowledge",
      "/audit",
      "/system",
    ]) {
      await visit(page, path, "P002");
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        `${path} @${viewport.width}`,
      ).toBe(true);
      await expect(page.locator("nav a")).toHaveCount(8);
    }
    await visit(page, "/", "P002");
    await page.screenshot({
      path: `docs/evidence/workbench/dashboard-${viewport.width}.png`,
      fullPage: true,
    });
  }
});
test("后端断连明确报错且无静态患者回退 [F15 F18]", async ({ page }) => {
  await page.route(BASE + "/**", (r) => r.abort("connectionrefused"));
  await page.goto("/");
  await expect(page.locator("header")).toContainText("后端连接失败");
  await expect(page.getByRole("alert")).toContainText("未切换前端模拟数据");
  await expect(page.locator("main")).not.toContainText("张伟");
  await page.screenshot({
    path: "docs/evidence/workbench/backend-offline.png",
    fullPage: true,
  });
});
