import { expect, test } from "@playwright/test";
import fs from "node:fs/promises";
import { BASE, fixture, json, visit } from "./helpers";
// 专用服务产生实际 API 结果；脚本模型和故障均在服务端，未伪造浏览器响应。
const fixtures = async () =>
  JSON.parse(
    await fs.readFile(".runtime/v021/fixtures.json", "utf8"),
  ) as Record<string, string>;
test("v0.2.1 已纠正warning保留原日志，顶部不误报失败", async ({
  page,
  request,
}) => {
  const f = await fixtures();
  const trace = await json(request, `/runs/${f.warning_run}`);
  expect(trace.run.status).toBe("completed");
  expect(trace.run.output.warnings[0].resolved).toBe(true);
  expect(trace.run.output.rejections).toHaveLength(1);
  await visit(page, `/agent?run=${f.warning_run}`, f.warning);
  const drawer = page.locator(".ant-drawer:visible");
  await expect(drawer).toContainText("先前校验问题已纠正");
  await expect(drawer).toContainText(
    trace.reviews.some((r: { branch: string }) => r.branch === "MISSING_DATA")
      ? "请补充缺失记录后跟进复评。"
      : "请按计划跟进后续复评。",
  );
  await expect(drawer).toContainText("首次尝试未完成，后续已纠正");
  await expect(drawer.getByText("部分处理未完成", { exact: true })).toHaveCount(
    0,
  );
  await drawer.getByRole("button", { name: "运行日志", exact: true }).click();
  const raw = JSON.parse(
    await page.locator(".ant-drawer:visible pre.json").innerText(),
  );
  expect(raw.run.output).toEqual(trace.run.output);
});
test("v0.2.1 记录部分成功与偏好部分成功显示待补偿，真实tick补偿", async ({
  page,
  request,
}) => {
  const f = await fixtures();
  await visit(page, "/monitoring", f.record);
  await page.getByLabel("记录数值", { exact: true }).fill("7.2");
  const pending = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/patients/${f.record}/records`) &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: /保存并查看自动触发结果/ }).click();
  const saved = await (await pending).json();
  expect(saved.partial_success).toBe(true);
  expect(saved.outbox_id).toBeTruthy();
  const result = page.getByTestId("write-result");
  await expect(result).toContainText("已保存，后续处理待补偿");
  await expect(result).not.toContainText("未产生新事件");
  expect(
    (await json(request, `/patients/${f.record}/records`)).items,
  ).toHaveLength(1);
  await visit(page, "/followups?tab=preferences", f.preference);
  await page.getByLabel("偏好内容", { exact: true }).fill("20:30");
  await page.getByRole("checkbox", { name: /确认是合成患者/ }).check();
  const prefResponse = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/patients/${f.preference}/preferences`) &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "保存并读取实际生效偏好" }).click();
  expect((await (await prefResponse).json()).partial_success).toBe(true);
  await expect(page.getByTestId("write-result")).toContainText(
    "已保存，后续处理待补偿",
  );
  await fs.writeFile(
    ".runtime/v021/partial-results.json",
    JSON.stringify({ record: saved }, null, 2),
  );
});
test("v0.2.1 重复完成任务不要求reviews，不再次触发", async ({
  page,
  request,
}) => {
  const f = await fixtures();
  const complete = () =>
    request.post(BASE + `/tasks/${f.task_id}/complete`, {
      data: { run_agent: false },
    });
  // 第一次从其他工作人员完成，页面仍保留旧待办，模拟并发/陈旧视图。
  await visit(page, "/tasks", f.task);
  expect((await (await complete()).json()).partial_success).toBe(true);
  const before = await json(request, `/patients/${f.task}/runs`);
  await page.getByRole("button", { name: "标记完成" }).click();
  const response = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/tasks/${f.task_id}/complete`) &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "确 定", exact: true }).click();
  const body = await (await response).json();
  expect(body.already_done).toBe(true);
  expect(body.run).toBeNull();
  await expect(page.getByTestId("write-result")).toContainText(
    "任务此前已完成",
  );
  expect((await json(request, `/patients/${f.task}/runs`)).items).toEqual(
    before.items,
  );
});
test("C-DS-03 选项、回答恢复与不确定性不补造服药事实", async ({
  page,
  request,
}) => {
  const f = await fixtures();
  await visit(page, `/followups?question=${f.answer_question}`, f.answer);
  await expect(
    page.getByRole("textbox", { name: "模拟患者答复" }),
  ).toBeFocused();
  await page.getByRole("button", { name: "记不清", exact: true }).click();
  await page.getByRole("checkbox", { name: "这是合成患者的模拟答复" }).check();
  const response = page.waitForResponse((r) =>
    r.url().endsWith(`/questions/${f.answer_question}/answer`),
  );
  await page.getByRole("button", { name: "提交模拟答复并恢复 Agent" }).click();
  const body = await (await response).json();
  expect(body.resume.uncertain).toBe(true);
  expect(body.resume.recorded).toBeNull();
  expect(body.resume.run.run_id).toBeTruthy();
  await expect(page.getByTestId("write-result")).toContainText(
    "患者表示不确定",
  );
  expect(
    (await json(request, `/patients/${f.answer}/records`)).items,
  ).toHaveLength(0);
  await fs.writeFile(
    ".runtime/v021/answer-result.json",
    JSON.stringify(body, null, 2),
  );
});
test("v0.2.1 过期回答422后重读状态，不保存/不恢复", async ({
  page,
  request,
}) => {
  const f = await fixtures();
  await visit(page, `/followups?question=${f.expired_question}`, f.expired);
  await page.getByRole("textbox", { name: "模拟患者答复" }).fill("已按时完成");
  await page.getByRole("checkbox", { name: "这是合成患者的模拟答复" }).check();
  const response = page.waitForResponse((r) =>
    r.url().endsWith(`/questions/${f.expired_question}/answer`),
  );
  await page.getByRole("button", { name: "提交模拟答复并恢复 Agent" }).click();
  expect((await response).status()).toBe(422);
  await expect(
    page.getByText("问题已过期，未保存本次答复。请重新发起随访。"),
  ).toBeVisible();
  const q = (await json(request, `/patients/${f.expired}/questions`)).items[0];
  expect(q.answer).toBeNull();
  expect(q.status).toBe("expired");
  expect(
    (await json(request, `/patients/${f.expired}/runs`)).items,
  ).toHaveLength(0);
});
test("v0.2.1 真实409与422无重复副作用", async ({ request }) => {
  const f = await fixtures();
  expect(
    (
      await request.post(BASE + "/patients", {
        data: { id: f.record, name: "重复（虚构）" },
      })
    ).status(),
  ).toBe(409);
  expect(
    (
      await request.post(BASE + "/patients", {
        data: { name: "非合成", is_synthetic: false },
      })
    ).status(),
  ).toBe(422);
  expect(
    (
      await request.post(BASE + `/patients/${f.record}/records`, {
        data: { kind: "blood_magic" },
      })
    ).status(),
  ).toBe(422);
  expect(
    (await json(request, `/patients/${f.record}/records`)).items,
  ).toHaveLength(1);
});
test("C-DS-01 超过15秒仍等待，探测可用且只发送一次记录", async ({
  page,
  request,
}) => {
  const f = await fixtures();
  await page.clock.install();
  await visit(page, "/monitoring", f.slow);
  const before = (await json(request, `/patients/${f.slow}/records`)).items
    .length;
  const writes: string[] = [];
  let healthReads = 0;
  page.on("request", (r) => {
    if (r.method() === "POST") writes.push(r.url());
    if (r.url().endsWith("/health")) healthReads++;
  });
  await page.getByLabel("记录数值", { exact: true }).fill("7.2");
  const response = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/patients/${f.slow}/records`) &&
      r.request().method() === "POST",
    { timeout: 45000 },
  );
  await page.getByRole("button", { name: /保存并查看自动触发结果/ }).click();
  await page.clock.fastForward(31000);
  await expect(page.getByText(/处理时间较长，正在等待后端结果/)).toBeVisible();
  await expect.poll(() => healthReads).toBeGreaterThan(0);
  expect((await response).status()).toBe(201);
  await expect(page.getByTestId("write-result")).toContainText("已保存记录");
  expect(writes).toEqual([BASE + `/patients/${f.slow}/records`]);
  expect(
    (await json(request, `/patients/${f.slow}/records`)).items,
  ).toHaveLength(before + 1);
});
test("C-DS-01 保存后丢失响应，保护重复提交并只读核对", async ({
  page,
  request,
}) => {
  const id = await fixture(request, "lost-response");
  await visit(page, "/monitoring", id);
  let posts = 0;
  await page.route(`**/patients/${id}/records`, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    posts++;
    const saved = await route.fetch();
    expect(saved.status()).toBe(201);
    await route.abort("failed");
  });
  await page.getByLabel("记录数值", { exact: true }).fill("8.2");
  await page.getByRole("button", { name: /保存并查看自动触发结果/ }).click();
  const recovery = page.getByTestId("operation-recovery");
  await expect(recovery).toBeVisible();
  await page.getByRole("button", { name: /保存并查看自动触发结果/ }).click();
  expect(posts).toBe(1);
  await recovery.getByRole("button", { name: "查询已保存结果" }).click();
  await expect(
    recovery.getByRole("button", { name: "已核对，解除提交保护" }),
  ).toBeVisible();
  await recovery.getByRole("button", { name: "核对结果日志" }).click();
  const raw = JSON.parse(
    await page.locator(".ant-drawer:visible pre.json").innerText(),
  );
  expect(raw.records.some((r: { value: number }) => r.value === 8.2)).toBe(
    true,
  );
  expect(posts).toBe(1);
});
test("v0.2.1 实际tick补偿待处理副作用", async ({ request }) => {
  const tick = await request.post(BASE + "/automation/tick", { data: {} });
  expect(tick.ok()).toBe(true);
  await fs.writeFile(
    ".runtime/v021/tick-result.json",
    JSON.stringify(await tick.json(), null, 2),
  );
});
test("C-DS-01 保存后等待超时，不自动重发且保留核对入口", async ({
  page,
  request,
}) => {
  const id = await fixture(request, "timeout-response");
  await page.clock.install();
  await visit(page, "/monitoring", id);
  let posts = 0;
  let saved = false;
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**/patients/${id}/records`, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    posts++;
    expect((await route.fetch()).status()).toBe(201);
    saved = true;
    await held;
    await route.abort("timedout").catch(() => {});
  });
  await page.getByLabel("记录数值", { exact: true }).fill("8.5");
  await page.getByRole("button", { name: /保存并查看自动触发结果/ }).click();
  await expect.poll(() => saved).toBe(true);
  await page.clock.fastForward(59000);
  await expect(page.getByTestId("operation-recovery")).toHaveCount(0);
  await expect(page.getByText(/处理时间较长，正在等待后端结果/)).toBeVisible();
  await page.clock.fastForward(2000);
  await expect(page.getByTestId("operation-recovery")).toBeVisible();
  await expect(
    page.getByRole("alert").filter({ hasText: "等待超时" }),
  ).toBeVisible();
  await expect(page.getByTestId("operation-recovery")).toContainText(
    "后端可能仍在运行",
  );
  expect(posts).toBe(1);
  expect(
    (await json(request, `/patients/${id}/records`)).items.filter(
      (r: { value: number }) => r.value === 8.5,
    ),
  ).toHaveLength(1);
  release();
});
test("v0.2.1 缺失患者和子资源实际返回404，失败写入无副作用", async ({
  request,
}) => {
  const missing = "CT021-does-not-exist";
  for (const path of [
    `/patients/${missing}`,
    `/patients/${missing}/state`,
    `/patients/${missing}/questions`,
    "/runs/RUN-does-not-exist",
    "/tasks/TSK-does-not-exist",
  ]) {
    const response = await request.get(BASE + path);
    expect(response.status(), path).toBe(404);
    expect((await response.json()).detail).toBeTruthy();
  }
  const patientsBefore = (await json(request, "/patients")).items;
  const response = await request.post(BASE + `/patients/${missing}/records`, {
    data: { kind: "steps", value: 4000, trigger_agent: true },
  });
  expect(response.status()).toBe(404);
  expect((await json(request, "/patients")).items).toEqual(patientsBefore);
});
test("v0.2.1 缺失运行和任务在页面显示404，日志保留原文", async ({
  page,
  request,
}) => {
  const id = await fixture(request, "missing-resource");
  for (const [path, endpoint] of [
    ["/agent?run=RUN-does-not-exist", "/runs/RUN-does-not-exist"],
    ["/tasks?task=TSK-does-not-exist", "/tasks/TSK-does-not-exist"],
  ]) {
    const response = page.waitForResponse((r) => r.url() === BASE + endpoint);
    await visit(page, path, id);
    expect((await response).status()).toBe(404);
    const drawer = page.locator(".ant-drawer:visible");
    await expect(drawer.getByRole("alert")).toContainText("资源不存在");
    await expect(drawer.getByTestId("write-result")).toHaveCount(0);
    await drawer.getByRole("button", { name: "错误日志", exact: true }).click();
    const raw = JSON.parse(
      await page.locator(".ant-drawer:visible pre.json").innerText(),
    );
    expect(raw.code).toBe("HTTP_404");
    expect(raw.detail.detail).toBeTruthy();
  }
});
test("C-DS-03 读取真实问题并提交明确回答，保存记录并恢复运行", async ({
  page,
  request,
}) => {
  const id = await fixture(request, "confirmed-answer", {
    missingMedication: true,
  });
  const runResponse = await request.post(BASE + `/patients/${id}/agent/runs`, {
    data: { message: "请核实我的记录缺项，缺失信息先问我" },
  });
  expect(runResponse.status()).toBe(200);
  const questions = (await json(request, `/patients/${id}/questions`)).items;
  const q = questions.find(
    (q: { status: string; target_field: string }) =>
      q.status === "waiting" && q.target_field === "medication_taken",
  );
  expect(q).toBeTruthy();
  expect(q.options).toContain("已按时完成");
  const read = page.waitForResponse(
    (r) => r.url() === BASE + `/patients/${id}/questions`,
  );
  await visit(page, `/followups?question=${q.id}`, id);
  expect((await read).status()).toBe(200);
  const card = page.locator(`[id="${q.id}"]`);
  await expect(card.getByLabel("模拟患者答复", { exact: true })).toBeFocused();
  await card.getByRole("button", { name: "已按时完成", exact: true }).click();
  await card.getByRole("checkbox", { name: "这是合成患者的模拟答复" }).check();
  const answer = page.waitForResponse(
    (r) =>
      r.url() === BASE + `/questions/${q.id}/answer` &&
      r.request().method() === "POST",
  );
  await card.getByRole("button", { name: "提交模拟答复并恢复 Agent" }).click();
  const response = await answer;
  expect(response.status()).toBe(200);
  const body = await response.json();
  expect(body.question.status).toBe("answered");
  expect(body.resume.uncertain).toBe(false);
  expect(body.resume.recorded).toMatchObject({
    patient_id: id,
    kind: "medication_taken",
    value: 1,
  });
  expect(body.resume.run.patient_id).toBe(id);
  expect(body.resume.run.run_id).toMatch(/^RUN-/);
  await expect(page.getByTestId("write-result")).toContainText(
    "回答已保存为健康记录",
  );
  const records = (await json(request, `/patients/${id}/records`)).items;
  expect(
    records.filter((r: { kind: string }) => r.kind === "medication_taken"),
  ).toHaveLength(1);
  await fs.writeFile(
    ".runtime/v021/confirmed-answer-result.json",
    JSON.stringify(body, null, 2),
  );
});
