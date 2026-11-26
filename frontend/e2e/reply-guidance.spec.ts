import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";
import { BASE, fixture, json, visit } from "./helpers";

test("人工请求后首屏可见提问，一键定位回答并继续沟通", async ({
  page,
  request,
}) => {
  const pid = await fixture(request, "回答引导", { missingMedication: true });
  await visit(page, "/agent", pid);
  await page
    .getByLabel("健康管理请求", { exact: true })
    .fill("请核实健康记录缺失信息，必要时先提问");
  const posted = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/patients/${pid}/agent/runs`) &&
      r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "运行一次 Agent", exact: true })
    .click();
  const run = await (await posted).json();
  expect(run.status).toBe("waiting_user");
  const questions = await json(request, `/patients/${pid}/questions`);
  const q = questions.items.find(
    (q: { run_id: string; status: string }) =>
      q.run_id === run.run_id && q.status === "waiting",
  );
  expect(q).toBeTruthy();
  const result = page.getByTestId("write-result");
  await expect(result).toContainText(q.question);
  await expect(
    result.getByRole("link", { name: "去回答", exact: true }),
  ).toBeVisible();
  await expect(result).not.toContainText(/RUN-|Q-|ask_user/);
  await expect(
    page
      .getByRole("row")
      .filter({ hasText: "等待患者补充信息" })
      .getByRole("link", { name: "去回答", exact: true }),
  ).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/agent");
  await page.screenshot({
    path: "docs/evidence/ux-followup/question-next-step.png",
    fullPage: true,
    animations: "disabled",
  });
  await result.getByRole("link", { name: "去回答", exact: true }).click();
  expect(new URL(page.url()).searchParams.get("question")).toBe(q.id);
  expect(new URL(page.url()).searchParams.get("patient")).toBe(pid);
  const card = page.locator(`[id="${q.id}"]`);
  await expect(card.getByLabel("模拟患者答复", { exact: true })).toBeFocused();
  await card.getByLabel("模拟患者答复", { exact: true }).fill("记不清");
  await card.getByText("这是合成患者的模拟答复", { exact: true }).click();
  const answerResponse = page.waitForResponse((r) =>
    r.url().endsWith(`/questions/${q.id}/answer`),
  );
  await card.getByRole("button", { name: "提交模拟答复并恢复 Agent" }).click();
  const answer = await (await answerResponse).json();
  expect(answer.resume.uncertain).toBe(true);
  await expect(card).toContainText("患者答复：记不清");
  await expect(card).toContainText("尚不确定");
  await expect(result.locator(".run-conversation")).not.toBeEmpty();
  const records = await json(request, `/patients/${pid}/records`);
  expect(
    records.items.filter(
      (r: { kind: string }) => r.kind === "medication_taken",
    ),
  ).toEqual([]);
  await fs.writeFile(
    "docs/evidence/ux-followup/reply-flow.json",
    JSON.stringify(
      { mode: "mock", pid, run, question: q, answer, no_medication_fact: true },
      null,
      2,
    ),
  );
});

test("Agent实际回复直接出现在结果区和运行详情顶部，无需打开日志", async ({
  page,
  request,
}) => {
  const pid = await fixture(request, "回复可见");
  await visit(page, "/agent", pid);
  await page
    .getByLabel("健康管理请求", { exact: true })
    .fill("请检索知识库说明连续记录血糖的意义");
  const response = page.waitForResponse((r) =>
    r.url().endsWith(`/patients/${pid}/agent/runs`),
  );
  await page
    .getByRole("button", { name: "运行一次 Agent", exact: true })
    .click();
  const run = await (await response).json();
  expect(run.responses.length).toBeGreaterThan(0);
  const message = page
    .getByTestId("write-result")
    .locator(".agent-message")
    .filter({ hasText: "Agent 回复" })
    .first();
  await expect(message).toBeVisible();
  await expect(message).toContainText("Agent 回复");
  // 已返回原文可能含技术引用，业务展示会转换编号；比较实际回复的正文片段。
  expect((await message.innerText()).length).toBeGreaterThan(30);
  await page
    .getByTestId("write-result")
    .getByRole("link", { name: "查看处理经过" })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Agent 执行轨迹",
    exact: true,
  });
  await expect(
    dialog.locator(".business-overview .agent-message").first(),
  ).toBeVisible();
  await expect(dialog.locator(".business-overview")).toContainText(
    "Agent 回复",
  );
  await expect(dialog.locator("pre, details")).toHaveCount(0);
  await page.screenshot({
    path: "docs/evidence/ux-followup/reply-at-top.png",
    fullPage: true,
    animations: "disabled",
  });
  await fs.writeFile(
    "docs/evidence/ux-followup/visible-reply.json",
    JSON.stringify({ mode: "mock", pid, run }, null, 2),
  );
});

test("待回答问题缺失或读取失败时不编造去回答入口", async ({
  page,
  request,
}) => {
  const pid = await fixture(request, "提问异常", { missingMedication: true });
  const run = await (
    await request.post(BASE + `/patients/${pid}/agent/runs`, {
      data: { message: "请核实缺失记录" },
    })
  ).json();
  expect(run.status).toBe("waiting_user");
  // 此用例继续验证旧后端缺少 summary 时的问题查询兼容路径。
  await page.route(BASE + `/runs/${run.run_id}`, async (route) => {
    const trace = await (await route.fetch()).json();
    delete trace.summary;
    await route.fulfill({ json: trace });
  });
  await page.route(BASE + `/patients/${pid}/questions`, (r) =>
    r.fulfill({ json: { items: [] } }),
  );
  await visit(page, `/agent?run=${run.run_id}`, pid);
  let dialog = page.getByRole("dialog", {
    name: "Agent 执行轨迹",
    exact: true,
  });
  await expect(
    dialog.getByRole("link", { name: "去回答", exact: true }),
  ).toHaveCount(0);
  await expect(dialog).toContainText("没有查到本次运行的待回答问题");
  await page.unroute(BASE + `/patients/${pid}/questions`);
  await page.route(BASE + `/patients/${pid}/questions`, (r) =>
    r.fulfill({ status: 502, json: { detail: "受控问题列表读取失败" } }),
  );
  await page.reload();
  dialog = page.getByRole("dialog", { name: "Agent 执行轨迹", exact: true });
  await expect(dialog).toContainText("暂时无法读取待回答问题");
  await expect(
    dialog.getByRole("link", { name: "去回答", exact: true }),
  ).toHaveCount(0);
  await expect(
    dialog.getByRole("button", { name: "重新读取问题" }),
  ).toBeVisible();
});
