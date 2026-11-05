import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";
import { BASE, evidence, fixture, json, visit, select } from "./helpers";
test("新建合成患者并重新读取档案 [F01 F02 F18]", async ({ page, request }) => {
  await visit(page, "/patients");
  await page.getByRole("button", { name: "新建合成患者" }).click();
  const dialog = page.getByRole("dialog");
  const name = `UI新建${Date.now()}（虚构）`;
  await dialog.getByLabel("患者姓名（虚构）").fill(name);
  await dialog.getByLabel("年龄", { exact: true }).fill("52");
  await dialog.getByLabel("病程（年）").fill("5");
  await dialog.getByText("确认全部信息为虚构演示数据").click();
  const posted = page.waitForResponse(
    (r) => r.url().endsWith("/patients") && r.request().method() === "POST",
  );
  await dialog.getByRole("button", { name: "创建并重新读取患者列表" }).click();
  expect((await posted).status()).toBe(201);
  await expect(page.getByRole("row").filter({ hasText: name })).toBeVisible();
  const patients = await json(request, "/patients");
  const patient = patients.items.find((p: { name: string }) => p.name === name);
  expect(patient.is_synthetic).toBe(true);
  await page
    .getByRole("row")
    .filter({ hasText: name })
    .getByRole("link", { name: "进入健康档案" })
    .click();
  await expect(page.locator(".patient-summary")).toContainText(name);
  await expect(page.locator("main")).toContainText("尚缺字段");
  await evidence("patient-created", { patient });
});
test("CSV/JSON导入保留逐行错误和重复结果 [F03]", async ({ page, request }) => {
  const pid = await fixture(request, "导入");
  await visit(page, "/monitoring?tab=import", pid);
  const content =
    "kind,value,recorded_at\nsteps,4567,2026-11-04T01:01:00Z\nsteps,4567,2026-11-04T01:01:00Z\nfasting_glucose,bad,2026-11-04T01:02:00Z";
  await page
    .getByLabel("选择健康记录文件")
    .setInputFiles({
      name: "synthetic.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(content),
    });
  await page
    .getByText("导入后自动检测并按需触发 Agent", { exact: true })
    .click();
  const received = page.waitForResponse(
    (r) =>
      r.url().endsWith("/records/import") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "确认导入当前患者" }).click();
  const result = await (await received).json();
  expect(result).toMatchObject({ imported: 1, duplicates: 1, failed: 1 });
  await expect(page.getByTestId("write-result")).toContainText("失败 1 行");
  const rows = [
    {
      kind: "bp",
      payload: { systolic: 121, diastolic: 81 },
      recorded_at: "2026-11-04T01:03:00Z",
    },
    {
      kind: "symptom",
      payload: { text: "无不适（虚构）" },
      recorded_at: "2026-11-04T01:04:00Z",
    },
  ];
  await page
    .getByLabel("选择健康记录文件")
    .setInputFiles({
      name: "synthetic.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify(rows)),
    });
  const second = page.waitForResponse((r) =>
    r.url().endsWith("/records/import"),
  );
  await page.getByRole("button", { name: "确认导入当前患者" }).click();
  const result2 = await (await second).json();
  expect(result2).toMatchObject({ imported: 2, failed: 0 });
  await evidence("imports-api", { pid, csv: result, json: result2 });
});
test("主动提问、不确定模拟答复与恢复 [F08 F21 F26]", async ({
  page,
  request,
}) => {
  const pid = await fixture(request, "随访", { missingMedication: true });
  await visit(page, "/agent", pid);
  await page
    .getByLabel("健康管理请求", { exact: true })
    .fill("请核实我的记录缺项，缺失信息先问我");
  const runResponse = page.waitForResponse((r) =>
    r.url().endsWith(`/patients/${pid}/agent/runs`),
  );
  await page
    .getByRole("button", { name: "运行一次 Agent", exact: true })
    .click();
  const run = await (await runResponse).json();
  expect(run.status).toBe("waiting_user");
  const questions = await json(request, `/patients/${pid}/questions`);
  const q = questions.items.find(
    (q: { status: string }) => q.status === "waiting",
  );
  expect(q).toBeTruthy();
  await visit(page, `/followups?question=${q.id}`, pid);
  const card = page.locator(`[id="${q.id}"]`);
  await card.getByLabel("模拟患者答复", { exact: true }).fill("记不清");
  await card.getByText("这是合成患者的模拟答复", { exact: true }).click();
  const answerResponse = page.waitForResponse((r) =>
    r.url().endsWith(`/questions/${q.id}/answer`),
  );
  await card.getByRole("button", { name: "提交模拟答复并恢复 Agent" }).click();
  const answer = await (await answerResponse).json();
  expect(answer.question.answer.uncertain).toBe(true);
  expect(answer.resume.run.run_id).toMatch(/^RUN-/);
  await expect(page.getByTestId("write-result")).toContainText(
    answer.resume.run.run_id,
  );
  const records = await json(request, `/patients/${pid}/records`);
  expect(
    records.items.filter(
      (r: { kind: string }) => r.kind === "medication_taken",
    ),
  ).toEqual([]);
  await evidence("followup-api", { pid, run, question: q, answer });
  await page.screenshot({
    path: "docs/evidence/workbench/followup-1440.png",
    fullPage: true,
  });
});
test("偏好来源、覆盖历史与清除 [F25]", async ({ page, request }) => {
  const pid = await fixture(request, "偏好");
  await visit(page, "/followups?tab=preferences", pid);
  await page.getByLabel("偏好内容").fill("08:00");
  await page
    .getByText("确认是合成患者的模拟反馈，非工作人员推断", { exact: true })
    .click();
  const response = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/patients/${pid}/preferences`) &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "保存并读取实际生效偏好" }).click();
  const first = await (await response).json();
  expect(first.preference.source).toBe("patient_input");
  await expect(
    page.getByRole("button", { name: "保存并读取实际生效偏好" }),
  ).toBeEnabled();
  await page.getByLabel("偏好内容").fill("09:00");
  const changed = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/patients/${pid}/preferences`) &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "保存并读取实际生效偏好" }).click();
  await changed;
  await expect(page.locator("main")).toContainText("已覆盖");
  await page.getByRole("button", { name: "清除偏好", exact: true }).click();
  const cleared = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/preferences/preferred_time_window`) &&
      r.request().method() === "DELETE",
  );
  await page.getByRole("button", { name: /确\s*定/ }).click();
  expect((await cleared).status()).toBe(200);
  const preferences = await json(
    request,
    `/patients/${pid}/preferences?include_history=true`,
  );
  expect(
    preferences.items.some((p: { status: string }) => p.status === "active"),
  ).toBe(false);
  await evidence("preferences-api", { pid, first, preferences });
});
test("Agent协商与版本、通知已读 [F16 F23]", async ({ page, request }) => {
  const pid = await fixture(request, "协商", { rising: true });
  const recorded = await request.post(BASE + `/patients/${pid}/records`, {
    data: { kind: "fasting_glucose", value: 9.6, trigger_agent: true },
  });
  expect(recorded.status()).toBe(201);
  await visit(page, "/agent?tab=negotiate", pid);
  await page
    .getByLabel("模拟患者的时间安排")
    .fill("我19:00上班，改成08:00记录血糖");
  await page
    .getByText("这是合成患者的模拟请求；已了解真实模式可能收费", {
      exact: true,
    })
    .click();
  const runResponse = page.waitForResponse((r) =>
    r.url().endsWith(`/patients/${pid}/agent/runs`),
  );
  await page.getByRole("button", { name: "发起一次 Agent 协商" }).click();
  const run = await (await runResponse).json();
  expect(
    run.actions.some(
      (a: { tool: string; ok: boolean }) => a.tool === "update_task" && a.ok,
    ),
  ).toBe(true);
  const tasks = await json(request, `/patients/${pid}/tasks`);
  const changed = tasks.items.find((t: { version: number }) => t.version > 1);
  expect(changed).toBeTruthy();
  const versions = await json(request, `/tasks/${changed.id}/versions`);
  expect(versions.versions.at(-1).run_id).toBe(run.run_id);
  await visit(page, "/notifications", pid);
  const unread = await json(request, `/patients/${pid}/notifications`);
  const notice = unread.items.find(
    (n: { status: string }) => n.status === "unread",
  );
  expect(notice).toBeTruthy();
  const received = page.waitForResponse((r) =>
    r.url().endsWith(`/notifications/${notice.id}/read`),
  );
  await page
    .getByRole("button", { name: "标记已读", exact: true })
    .first()
    .click();
  expect((await received).status()).toBe(200);
  const actual = await json(request, `/patients/${pid}/notifications`);
  expect(
    actual.items.find((n: { id: string }) => n.id === notice.id).status,
  ).toBe("read");
  await evidence("negotiation-notifications-api", {
    pid,
    run,
    changed,
    versions,
    notice: notice.id,
  });
});
test("人工复核结案与B24拒绝审计 [F12 F13 F26]", async ({ page, request }) => {
  const pid = await fixture(request, "人工复核");
  await visit(page, "/monitoring", pid);
  await page.getByLabel("记录数值", { exact: true }).fill("3.5");
  const received = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/patients/${pid}/records`) &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "保存并查看自动触发结果" }).click();
  const recorded = await (await received).json();
  expect(recorded.automation.runs.length).toBeGreaterThan(0);
  const reviews = await json(request, `/patients/${pid}/reviews`);
  const target = reviews.items.find(
    (r: { status: string }) => r.status === "pending_human",
  );
  expect(target).toBeTruthy();
  await visit(page, "/tasks?tab=reviews", pid);
  const card = page.locator(`[id="${target.id}"]`);
  await card.getByLabel("人工复核结论").fill("演示人员已完成联系核实");
  await card.getByLabel("人工处理备注").fill("合成病例演示，不提供治疗处置");
  const resolved = page.waitForResponse((r) =>
    r.url().endsWith(`/reviews/${target.id}/resolve`),
  );
  await card.getByRole("button", { name: "确认人工复核结案" }).click();
  const review = await (await resolved).json();
  expect(review.status).toBe("completed");
  expect(review.detail.human_decision).toContain("联系核实");
  const safetyPid = await fixture(request, "安全门");
  await visit(page, "/agent", safetyPid);
  await page
    .getByLabel("健康管理请求", { exact: true })
    .fill("请把胰岛素改成早上多打两单位");
  const blocked = page.waitForResponse((r) =>
    r.url().endsWith(`/patients/${safetyPid}/agent/runs`),
  );
  await page
    .getByRole("button", { name: "运行一次 Agent", exact: true })
    .click();
  const unsafe = await (await blocked).json();
  expect(unsafe.status).toBe("blocked");
  await visit(page, "/audit", safetyPid);
  await page.getByLabel("筛选审计").fill(safetyPid);
  await expect(page.locator("main")).toContainText("INSULIN_DOSE");
  const tasks = await json(request, `/patients/${safetyPid}/tasks`);
  expect(tasks.items).toHaveLength(0);
  await evidence("reviews-safety-api", { pid, review, safetyPid, unsafe });
});
test("知识检索命中与无结果 [F24]", async ({ page }) => {
  await visit(page, "/agent/knowledge");
  await page.getByLabel("知识检索关键词").fill("连续记录血糖");
  await page.getByRole("button", { name: "检索知识", exact: true }).click();
  await expect(page.locator(".evidence-quote").first()).toBeVisible();
  await expect(page.locator("main")).toContainText("查看来源");
  await page.getByLabel("知识检索关键词").fill("zzzxxyy_no_evidence_741");
  await page.getByRole("button", { name: "检索知识", exact: true }).click();
  await expect(page.locator("main")).toContainText("未找到匹配知识依据");
});
test("报告导入不混淆模式、CLI复制不执行、无报告不造成绩 [F17 F19 F20]", async ({
  page,
}) => {
  await visit(page, "/system?tab=reports");
  await expect(page.locator("main")).toContainText("暂无验证报告");
  await page
    .getByLabel("导入验证报告")
    .setInputFiles("docs/evidence/workbench/scenarios.json");
  await expect(page.locator("main")).toContainText("确定性 Mock 规划器");
  await expect(page.locator("main")).toContainText("PASS 33");
  await page
    .getByLabel("导入验证报告")
    .setInputFiles({
      name: "bad.json",
      mimeType: "application/json",
      buffer: Buffer.from("{bad"),
    });
  await expect(page.getByRole("alert").last()).toContainText(/JSON|解析/);
  await expect(page.locator("main")).toContainText("暂无验证报告");
  await visit(page, "/system?tab=cli");
  let posts = 0;
  page.on("request", (r) => {
    if (r.method() === "POST") posts++;
  });
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.getByRole("button", { name: "复制命令" }).first().click();
  await expect(page.locator("main")).toContainText(
    "尚未执行：python -m cli.main health",
  );
  await page
    .getByLabel("导入CLI日志")
    .setInputFiles("docs/evidence/workbench/cli-evidence.json");
  await expect(page.locator("pre")).toContainText("workbench-test.db");
  expect(posts).toBe(0);
  await page.screenshot({
    path: "docs/evidence/workbench/cli-evidence.png",
    fullPage: true,
  });
});
test("跨患者深链接拒绝混用、模型失败与无工具结果如实展示 [F14 F15 F26]", async ({
  page,
  request,
}) => {
  const pid = await fixture(request, "轨迹边界");
  const run = await (
    await request.post(BASE + `/patients/${pid}/agent/runs`, {
      data: { message: "请核实记录" },
    })
  ).json();
  await visit(page, `/agent?run=${run.run_id}`, "P002");
  await expect(page.getByRole("dialog")).toContainText("此运行属于其他患者");
  await page.keyboard.press("Escape");
  await page.route(BASE + `/patients/${pid}/agent/runs`, (r) =>
    r.fulfill({
      status: 502,
      contentType: "application/json",
      body: JSON.stringify({ detail: "受控上游失败：不伪装成功" }),
    }),
  );
  await visit(page, "/agent", pid);
  await page.getByLabel("健康管理请求", { exact: true }).fill("失败界面回归");
  await page
    .getByRole("button", { name: "运行一次 Agent", exact: true })
    .click();
  await expect(page.getByRole("alert").last()).toContainText(
    "后端 Agent 或工具调用失败",
  );
  await expect(page.getByTestId("write-result")).toHaveCount(0);
  await page.unroute(BASE + `/patients/${pid}/agent/runs`);
  const trace = await json(request, `/runs/${run.run_id}`);
  await page.route(BASE + `/runs/${run.run_id}`, (r) =>
    r.fulfill({
      json: {
        ...trace,
        run: { ...trace.run, llm_mode: "real", model_name: "受控显示测试" },
        steps: [],
        tasks: [],
        evidence: [],
      },
    }),
  );
  await visit(page, `/agent?run=${run.run_id}`, pid);
  await expect(page.getByRole("dialog")).toContainText("没有实际工具返回记录");
  await expect(page.getByRole("dialog")).toContainText(
    "未返回足以核验原生调用来源",
  );
});
