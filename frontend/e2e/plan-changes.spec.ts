import { expect, test } from "@playwright/test";
import fs from "node:fs/promises";
import type { Trace } from "../src/api/types";
import { BASE, fixture, json, visit } from "./helpers";

test("O4 真实协商的前后版本保存在各自运行，随后修改不覆盖旧对照", async ({
  page,
  request,
}) => {
  const pid = await fixture(request, "O4changes", { rising: true });
  const recorded = await request.post(`${BASE}/patients/${pid}/records`, {
    data: { kind: "fasting_glucose", value: 9.6, trigger_agent: true },
  });
  expect(recorded.status()).toBe(201);
  const response = await request.post(`${BASE}/patients/${pid}/agent/runs`, {
    data: { message: "我19:00上班，改成08:00记录血糖" },
  });
  expect(response.ok()).toBeTruthy();
  const run = await response.json();
  const first: Trace = await json(request, `/runs/${run.run_id}`);
  const change = first.summary!.plan_changes!.find(
    (item) => item.changed_fields.due_at,
  );
  expect(change?.result).toBe("saved");
  expect(change!.version_after).toBe(change!.version_before! + 1);
  const versions = await json(request, `/tasks/${change!.task_id}/versions`);
  expect(versions.versions.at(-1).run_id).toBe(run.run_id);

  await visit(page, `/agent?run=${run.run_id}`, pid);
  const comparison = page.getByRole("region", {
    name: "本次计划变化",
    exact: true,
  });
  await expect(comparison).toContainText(
    `版本 ${change!.version_before} → 版本 ${change!.version_after}`,
  );
  await expect(comparison).toContainText(change!.reason!);
  const row = comparison.getByRole("row").filter({ hasText: "执行时间" });
  const formatted = await page.evaluate(
    (value) => ({
      before: new Date(String(value.before)).toLocaleString("zh-CN", {
        hour12: false,
      }),
      after: new Date(String(value.after)).toLocaleString("zh-CN", {
        hour12: false,
      }),
    }),
    change!.changed_fields.due_at,
  );
  await expect(row).toContainText(formatted.before);
  await expect(row).toContainText(formatted.after);
  await expect(comparison.getByRole("link")).toHaveAttribute(
    "href",
    new RegExp(`task=${change!.task_id}`),
  );
  await expect(comparison.getByRole("link")).toHaveAttribute(
    "href",
    new RegExp(`patient=${pid}`),
  );
  await page.screenshot({
    path: ".runtime/o4-plan-changes.png",
    fullPage: true,
  });

  const secondResponse = await request.post(
    `${BASE}/patients/${pid}/agent/runs`,
    {
      data: { message: "改成20:00记录血糖" },
    },
  );
  expect(secondResponse.ok()).toBeTruthy();
  const secondRun = await secondResponse.json();
  const second: Trace = await json(request, `/runs/${secondRun.run_id}`);
  const secondChange = second.summary!.plan_changes!.find(
    (item) => item.task_id === change!.task_id,
  );
  expect(secondChange!.version_before).toBe(change!.version_after);
  await page.reload();
  await expect(comparison).toContainText(
    `版本 ${change!.version_before} → 版本 ${change!.version_after}`,
  );
  await expect(
    comparison.getByRole("row").filter({ hasText: "执行时间" }),
  ).toContainText(formatted.after);
  await fs.writeFile(
    ".runtime/o4-api-evidence.json",
    JSON.stringify(
      { mode: "backend mock, real HTTP/SQLite", pid, first, second },
      null,
      2,
    ),
  );
});

test("O4 只显示实际差异，忽略相同字段、空差异和未保存结果", async ({
  page,
  request,
}) => {
  const pid = await fixture(request, "O4filtered");
  const response = await request.post(`${BASE}/patients/${pid}/agent/runs`, {
    data: { message: "请核实记录" },
  });
  expect(response.ok()).toBeTruthy();
  const run = await response.json();
  const trace: Trace = await json(request, `/runs/${run.run_id}`);
  const change = {
    task_id: "TSK-controlled",
    title: "时间核实任务",
    version_before: 1,
    version_after: 2,
    changed_fields: {
      description: { before: "白天核实", after: "晚上核实" },
      title: { before: "相同标题", after: "相同标题" },
      priority: { before: 0, after: 1 },
    },
    reason: "患者补充可用时间",
    result: "saved",
  };
  trace.summary!.plan_changes = [
    change,
    { ...change, version_after: 88, changed_fields: {} },
    { ...change, version_after: 99, result: "failed" },
  ];
  await page.route(`${BASE}/runs/${run.run_id}`, (route) =>
    route.fulfill({ json: trace }),
  );
  await visit(page, `/agent?run=${run.run_id}`, pid);
  const comparison = page.getByRole("region", {
    name: "本次计划变化",
    exact: true,
  });
  await expect(comparison.getByRole("table")).toHaveCount(1);
  await expect(
    comparison.getByRole("row").filter({ hasText: "任务标题" }),
  ).toHaveCount(0);
  await expect(
    comparison.getByRole("row").filter({ hasText: "任务说明" }),
  ).toContainText("晚上核实");
  await expect(
    comparison
      .getByRole("row")
      .filter({ hasText: "优先级" })
      .getByRole("cell")
      .nth(1),
  ).toHaveText("0");
  await expect(comparison).not.toContainText("版本 88");
  await expect(comparison).not.toContainText("版本 99");
  await page
    .getByRole("dialog", { name: "Agent 执行轨迹", exact: true })
    .getByRole("button", { name: "运行日志", exact: true })
    .click();
  const raw = page
    .getByRole("dialog", { name: "技术日志", exact: true })
    .locator("pre");
  await expect(raw).toBeVisible();
  expect(JSON.parse((await raw.textContent())!).summary.plan_changes).toEqual(
    trace.summary!.plan_changes,
  );
});

test("O4 调整失败、未变化和旧summary均不展示新版本", async ({
  page,
  request,
}) => {
  const pid = await fixture(request, "O4empty");
  const response = await request.post(`${BASE}/patients/${pid}/agent/runs`, {
    data: { message: "请核实记录" },
  });
  expect(response.ok()).toBeTruthy();
  const run = await response.json();
  const trace: Trace = await json(request, `/runs/${run.run_id}`);
  trace.summary!.plan_changes = [];
  trace.summary!.completed = [];
  trace.summary!.unfinished = [
    {
      tool: "update_task",
      code: "INVALID_DUE",
      message: "时间不符合约束，调整未保存",
    },
  ];
  trace.summary!.partial_success = false;
  trace.run.status = "failed";
  await page.route(`${BASE}/runs/${run.run_id}`, (route) =>
    route.fulfill({ json: trace }),
  );
  await visit(page, `/agent?run=${run.run_id}`, pid);
  const detail = page.getByRole("dialog", {
    name: "Agent 执行轨迹",
    exact: true,
  });
  await expect(detail).toContainText("调整未保存");
  await expect(
    detail.getByRole("region", { name: "本次计划变化", exact: true }),
  ).toHaveCount(0);
  await expect(detail).not.toContainText("版本 ");
  delete trace.summary!.plan_changes;
  await page.reload();
  await expect(detail).toContainText("调整未保存");
  await expect(
    detail.getByRole("region", { name: "本次计划变化", exact: true }),
  ).toHaveCount(0);
});
