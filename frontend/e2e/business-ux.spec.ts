import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";
import { BASE, fixture, json, visit } from "./helpers";

test("业务层解释随访与任务，技术层保留编号和可复制原文", async ({
  page,
  request,
}) => {
  const pid = await fixture(request, "业务说明", { missingMedication: true });
  const runResponse = await request.post(BASE + `/patients/${pid}/agent/runs`, {
    data: { message: "请核实健康记录缺失信息" },
  });
  expect(runResponse.ok()).toBeTruthy();
  const run = await runResponse.json();
  await visit(page, `/agent?run=${run.run_id}`, pid);
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator(".business-overview")).toContainText("触发原因");
  await expect(dialog.locator(".business-overview")).toContainText("接下来");
  await expect(dialog.locator(".business-overview")).not.toContainText(
    /RUN-|EVT-|TSK-/,
  );
  await expect(dialog).toContainText("向患者补充提问");
  await expect(dialog.locator("details")).toHaveCount(0);
  await dialog.getByRole("button", { name: "运行日志", exact: true }).click();
  const details = page.getByRole("dialog", { name: "技术日志", exact: true });
  await expect(details.locator("pre")).toContainText(run.run_id);
  await expect(details.locator("pre")).toContainText("ask_user");
  await expect(details.getByText("复制完整原始 JSON")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.screenshot({
    path: "docs/evidence/ux-followup/trace-1440.png",
    fullPage: true,
    animations: "disabled",
  });
  const questions = await json(request, `/patients/${pid}/questions`);
  await visit(page, "/followups", pid);
  const card = page.locator(`[id="${questions.items[0].id}"]`);
  await expect(card).toContainText("是否按时服药");
  await expect(card.locator("details")).toHaveCount(0);
  await page.getByRole("button", { name: "随访日志", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "技术日志", exact: true }).locator("pre"),
  ).toContainText(questions.items[0].id);
});

test("实际安全拦截用业务文字呈现，审计原码仍可查", async ({
  page,
  request,
}) => {
  const pid = await fixture(request, "业务安全");
  const patient = await json(request, `/patients/${pid}`);
  const response = await request.post(BASE + `/patients/${pid}/agent/runs`, {
    data: { message: "请把胰岛素改成早上多打两单位" },
  });
  const run = await response.json();
  expect(run.status).toBe("blocked");
  await visit(page, "/audit", pid);
  await page.getByLabel("筛选审计").fill(pid);
  const row = page.getByRole("row").filter({
    has: page.getByRole("cell", { name: patient.name, exact: true }),
    hasText: "拦截越权请求",
  });
  await expect(row).toContainText("拦截越权请求");
  await expect(row).toContainText("调整胰岛素剂量请求已拦截");
  await page.getByRole("button", { name: "审计日志", exact: true }).click();
  const technical = page.getByRole("dialog", { name: "技术日志", exact: true });
  await expect(technical.locator("pre")).toContainText("INSULIN_DOSE");
  await expect(technical.locator("pre")).toContainText(run.run_id);
  await page.keyboard.press("Escape");
  await page.screenshot({
    path: "docs/evidence/ux-followup/audit-1440.png",
    fullPage: true,
    animations: "disabled",
  });
});

test("保存的真实失败轨迹只读回放，失败原因及原始参数均可查", async ({
  page,
}) => {
  // 这是已保存的真实运行展示回归，不是新一次厂商联调，不发起模型请求。
  const trace = JSON.parse(
    await fs.readFile("docs/evidence/ux/real-failure-trace.json", "utf8"),
  );
  expect(trace.run.status).toBe("failed");
  // 使用现有合成患者作为只读展示上下文；仅替换患者关联字段，不改状态、步骤或输出。
  const pid = "P001";
  await page.route(BASE + `/runs/${trace.run.id}`, (route) =>
    route.fulfill({
      json: { ...trace, run: { ...trace.run, patient_id: pid } },
    }),
  );
  let posts = 0;
  page.on("request", (r) => {
    if (r.method() === "POST") posts++;
  });
  await visit(page, `/agent?run=${trace.run.id}`, pid);
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("处理未全部完成");
  await expect(dialog).toContainText("所需业务动作未执行");
  await expect(dialog.locator(".business-overview")).toContainText("人工核查");
  await dialog.getByRole("button", { name: "运行日志", exact: true }).click();
  const details = page.getByRole("dialog", { name: "技术日志", exact: true });
  await expect(details.locator("pre")).toContainText("POSTCHECK_MISMATCH");
  await expect(details.locator("pre")).toContainText("tool_call");
  expect(posts).toBe(0);
  await page.keyboard.press("Escape");
  await page.screenshot({
    path: "docs/evidence/ux-followup/real-failure-replay.png",
    fullPage: true,
    animations: "disabled",
  });
});

test("任务业务标题与完整技术对象均可读取，三个桌面尺寸无页面溢出", async ({
  page,
  request,
}) => {
  const pid = await fixture(request, "业务任务", { rising: true });
  const response = await request.post(BASE + `/patients/${pid}/records`, {
    data: { kind: "fasting_glucose", value: 9.6, trigger_agent: true },
  });
  expect(response.status()).toBe(201);
  const tasks = await json(request, `/patients/${pid}/tasks`);
  const task = tasks.items[0];
  expect(task).toBeTruthy();
  await visit(page, `/tasks?task=${task.id}`, pid);
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { level: 2 })).toContainText(
    task.title,
  );
  await expect(dialog.locator("details")).toHaveCount(0);
  await dialog.getByRole("button", { name: "任务日志", exact: true }).click();
  const technical = page.getByRole("dialog", { name: "技术日志", exact: true });
  await expect(technical.locator("pre")).toContainText(task.id);
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await technical.locator(".ant-typography-copy").first().click();
  const copied = JSON.parse(
    await page.evaluate(() => navigator.clipboard.readText()),
  );
  expect(copied.task.id).toBe(task.id);
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  for (const width of [1920, 1440, 1366]) {
    await page.setViewportSize({ width, height: width === 1366 ? 768 : 900 });
    for (const path of ["/agent", "/followups", "/tasks", "/audit"]) {
      await visit(page, path, pid);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        `${path}@${width}`,
      ).toBe(true);
    }
  }
  await page.screenshot({
    path: "docs/evidence/ux-followup/audit-1366.png",
    fullPage: true,
    animations: "disabled",
  });
});
