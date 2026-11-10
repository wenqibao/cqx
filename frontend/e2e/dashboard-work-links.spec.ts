import { expect, test } from "@playwright/test";
import { BASE, visit } from "./helpers";

test("总览待办按实际归属切换患者并打开对应页面", async ({ page }) => {
  const current = { id: "WB-NO-WORK", name: "陈景明" };
  const followup = { id: "WB-FOLLOWUP", name: "沈婉宁" };
  const reviewer = { id: "WB-REVIEW", name: "周承安" };
  const patients = [current, followup, reviewer].map((patient) => ({
    ...patient,
    age: null,
    duration_years: null,
    goals: [],
    constraints: [],
    is_synthetic: true,
  }));
  const question = {
    id: "Q-dashboard",
    patient_id: followup.id,
    question: "最近是否按时服药？",
    status: "waiting",
    options: ["记不清"],
    target_field: "medication_taken",
    run_id: null,
    answer: null,
    answer_text: null,
    created_at: "2026-11-10T01:00:00Z",
  };
  const review = {
    id: "REV-dashboard",
    patient_id: reviewer.id,
    task_id: null,
    run_id: null,
    branch: "HUMAN_REVIEW",
    status: "pending_human",
    reason: "低血糖记录需要人工核查",
    detail: {},
    scheduled_for: null,
    resolved_at: null,
  };
  const tasks = [followup.id, reviewer.id, reviewer.id].map(
    (patient_id, index) => ({
      id: `TSK-dashboard-${index}`,
      patient_id,
      title: `待完成管理任务 ${index + 1}`,
      status: "pending",
      priority: 1,
      due_at: null,
      source_run_id: null,
      event_id: null,
    }),
  );
  await page.route(`${BASE}/**`, async (route) => {
    const path = route.request().url().slice(BASE.length).split("?")[0];
    if (path === "/patients") return route.fulfill({ json: { items: patients } });
    const [, , id, resource] = path.split("/");
    const patient = patients.find((p) => p.id === id);
    if (!patient) return route.continue();
    const pendingQuestions = id === followup.id ? [question] : [];
    const openTasks = tasks.filter((task) => task.patient_id === id);
    const reviews = id === reviewer.id ? [review] : [];
    const data =
      resource === "state"
        ? {
            patient,
            latest: {},
            missing_fields: [],
            open_tasks: openTasks,
            open_events: [],
            pending_questions: pendingQuestions,
            trend: {},
            generated_at: question.created_at,
          }
        : {
            items:
              resource === "questions" ? pendingQuestions
              : resource === "tasks" ? openTasks
              : resource === "reviews" ? reviews
              : [],
          };
    return route.fulfill({ json: data });
  });

  const work = page.locator(".work-links");
  await visit(page, "/", current.id);
  await expect(page.locator("header")).toContainText(current.name);
  await work.getByRole("link", { name: /1 待回答问题/ }).click();
  await expect(page.locator("header")).toContainText(followup.name);
  expect(new URL(page.url()).searchParams.get("patient")).toBe(followup.id);
  expect(new URL(page.url()).searchParams.get("question")).toBe(question.id);
  const card = page.locator(`[id="${question.id}"]`);
  await expect(card.getByText(question.question)).toBeVisible();
  await expect(card.getByRole("textbox")).toBeFocused();

  await visit(page, "/", current.id);
  await work.getByRole("button", { name: /3 未完成任务/ }).click();
  await expect(page.getByRole("menuitem", { name: `${followup.name} · 1 项` })).toBeVisible();
  await page.getByRole("menuitem", { name: `${reviewer.name} · 2 项` }).click();
  await expect(page.locator("header")).toContainText(reviewer.name);
  await expect(page.getByText(tasks[1].title, { exact: true })).toBeVisible();
  await expect(page.getByText(tasks[0].title, { exact: true })).toHaveCount(0);

  await visit(page, "/", current.id);
  await work.getByRole("link", { name: /1 人工复核事项/ }).click();
  await expect(page.locator("header")).toContainText(reviewer.name);
  await expect(page.getByRole("tab", { name: "动态复评与人工复核" }))
    .toHaveAttribute("aria-selected", "true");
  await expect(page.getByText(review.reason, { exact: false })).toBeVisible();
});
