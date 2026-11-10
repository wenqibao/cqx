import { expect, test } from "@playwright/test";
import type { Trace } from "../src/api/types";
import { BASE, fixture, json, visit } from "./helpers";

test("C-UX-02 已展示的 Agent 回复只出现一次，技术日志保留原文", async ({
  page,
  request,
}) => {
  const pid = await fixture(request, "回复去重");
  const started = await request.post(`${BASE}/patients/${pid}/agent/runs`, {
    data: { message: "请核对当前健康记录和任务" },
  });
  expect(started.ok()).toBeTruthy();
  const run = await started.json();
  expect(run.responses).toHaveLength(1);
  const [reply] = run.responses as string[];
  expect(reply.trim()).not.toBe("");

  const trace: Trace = await json(request, `/runs/${run.run_id}`);
  expect(trace.run.output).toMatchObject({ responses: [reply] });
  const steps = trace.steps.filter(
    (step) => step.kind === "tool_result" && step.tool_name === "respond",
  );
  expect(steps).toHaveLength(1);
  expect(steps[0].payload.result).toMatchObject({ ok: true, text: reply });

  await visit(page, `/agent?run=${run.run_id}`, pid);
  const detail = page.getByRole("dialog", { name: "Agent 执行轨迹" });
  await expect(
    detail.locator(".business-overview").getByText(reply, { exact: true }),
  ).toBeVisible();
  await expect(detail.getByText(reply, { exact: true })).toHaveCount(1);
  await expect(detail.getByText("已给出回复", { exact: true })).toBeVisible();

  await detail.getByRole("button", { name: "运行日志" }).click();
  const log = page.getByRole("dialog", { name: "技术日志", exact: true });
  const raw = log.locator("pre");
  await expect(raw).toBeVisible();
  const logged: Trace = JSON.parse((await raw.textContent())!);
  expect(logged.steps).toContainEqual(steps[0]);
  expect(logged.run.output).toMatchObject({ responses: [reply] });
});
