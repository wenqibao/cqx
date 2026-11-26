import { expect, test } from "@playwright/test";
import type { Trace } from "../src/api/types";
import { BASE, fixture, json, visit } from "./helpers";

test("O1 真实详情 summary 的问题入口携带患者与问题并聚焦", async ({
  page,
  request,
}) => {
  const pid = await fixture(request, "O1waiting", { missingMedication: true });
  const response = await request.post(`${BASE}/patients/${pid}/agent/runs`, {
    data: { message: "请核实健康记录缺失信息，必要时先提问" },
  });
  expect(response.ok()).toBeTruthy();
  const run = await response.json();
  const trace: Trace = await json(request, `/runs/${run.run_id}`);
  expect(trace.summary?.waiting?.kind).toBe("question");
  const question = trace.summary!.waiting!;
  // 顶部入口以运行详情的后端 summary 为准，独立问题列表失败不抹掉真实来源。
  await page.route(`${BASE}/patients/${pid}/questions`, (route) =>
    route.fulfill({ status: 502, json: { detail: "受控问题列表故障" } }),
  );
  await visit(page, `/agent?run=${run.run_id}`, pid);
  const detail = page.getByRole("dialog", {
    name: "Agent 执行轨迹",
    exact: true,
  });
  const outcome = detail.getByRole("region", {
    name: "本次业务结果",
    exact: true,
  });
  await expect(outcome).toContainText(trace.summary!.goal!);
  await expect(outcome).toContainText(question.text!);
  await expect(detail.getByText("本次没有返回动作结果", { exact: true })).toHaveCount(0);
  const answer = outcome.getByRole("link", { name: "去回答", exact: true });
  await expect(answer).toHaveAttribute(
    "href",
    new RegExp(`question=${question.id}`),
  );
  await expect(answer).toHaveAttribute("href", new RegExp(`patient=${pid}`));
  await page.reload();
  await expect(answer).toBeVisible();
  await page.unroute(`${BASE}/patients/${pid}/questions`);
  await answer.click();
  await expect(
    page
      .locator(`[id="${question.id}"]`)
      .getByLabel("模拟患者答复", { exact: true }),
  ).toBeFocused();
});

test("O1 completed/unfinished/partial_success 独立于回复中的成功声明", async ({
  page,
  request,
}) => {
  const pid = await fixture(request, "O1partial");
  const response = await request.post(`${BASE}/patients/${pid}/agent/runs`, {
    data: { message: "请核对当前健康记录和任务" },
  });
  expect(response.ok()).toBeTruthy();
  const run = await response.json();
  const trace: Trace = await json(request, `/runs/${run.run_id}`);
  // 受控显示反例，验证前端只接受结构化业务结果。生产响应来自真实接口。
  trace.run.output = { responses: ["已调整任务至晚上，已完成所有安排。"] };
  trace.summary = {
    goal: "核实任务时间调整结果",
    trigger: { label: "患者补充时间约束" },
    completed: [
      { tool: "save_preference", label: "保存偏好", refs: [] },
    ],
    unfinished: [
      {
        tool: "update_task",
        code: "INVALID_DUE",
        message: "时间不符合当前约束，任务保持原安排",
      },
    ],
    waiting: null,
    next_owner: { role: "patient", action: "确认可执行时间" },
    partial_success: true,
    refs: [run.run_id],
  };
  await page.route(`${BASE}/runs/${run.run_id}`, (route) =>
    route.fulfill({ json: trace }),
  );
  await visit(page, `/agent?run=${run.run_id}`, pid);
  const detail = page.getByRole("dialog", {
    name: "Agent 执行轨迹",
    exact: true,
  });
  const outcome = detail.getByRole("region", {
    name: "本次业务结果",
    exact: true,
  });
  await expect(
    outcome.getByRole("region", { name: "已完成动作" }),
  ).toContainText("保存已确认偏好");
  await expect(
    outcome.getByRole("region", { name: "已完成动作" }),
  ).not.toContainText("已调整");
  await expect(
    outcome.getByRole("region", { name: "未完成事项" }),
  ).toContainText("任务保持原安排");
  await expect(outcome.getByRole("alert")).toContainText("部分处理未完成");
  await expect(outcome).toContainText("患者 · 确认可执行时间");
  await expect(outcome.getByRole("link", { name: "去回答" })).toHaveCount(0);
  await detail.getByRole("button", { name: "运行日志", exact: true }).click();
  const raw = page
    .getByRole("dialog", { name: "技术日志", exact: true })
    .locator("pre");
  await expect(raw).toBeVisible();
  expect(JSON.parse((await raw.textContent())!)).toEqual(trace);
});

test("O1 失败保持空 completed，人工复核等待不生成回答入口", async ({
  page,
  request,
}) => {
  const pid = await fixture(request, "O1failure");
  const response = await request.post(`${BASE}/patients/${pid}/agent/runs`, {
    data: { message: "请核对当前健康记录和任务" },
  });
  expect(response.ok()).toBeTruthy();
  const run = await response.json();
  const trace: Trace = await json(request, `/runs/${run.run_id}`);
  trace.summary = {
    goal: null,
    trigger: { label: null },
    completed: [],
    unfinished: [{ code: "TOOL_EXECUTION_FAILED", message: "受控执行失败" }],
    waiting: { kind: "human_review", id: "REV-controlled" },
    next_owner: { role: "clinician", action: "查看复核事项" },
    partial_success: false,
    refs: [],
  };
  await page.route(`${BASE}/runs/${run.run_id}`, (route) =>
    route.fulfill({ json: trace }),
  );
  await visit(page, `/agent?run=${run.run_id}`, pid);
  const outcome = page.getByRole("region", {
    name: "本次业务结果",
    exact: true,
  });
  await expect(outcome).toContainText("本次暂无已确认完成的业务动作");
  await expect(outcome).toContainText("受控执行失败");
  await expect(outcome).toContainText("等待医护人员复核");
  await expect(outcome).toContainText("医护人员 · 查看复核事项");
  await expect(outcome.getByRole("alert")).toHaveCount(0);
  await expect(outcome.getByRole("link", { name: "去回答" })).toHaveCount(0);
});
