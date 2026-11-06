import { expect, type APIRequestContext, type Page } from "@playwright/test";
import fs from "node:fs/promises";
export const BASE =
  process.env.WORKBENCH_API_BASE || "http://127.0.0.1:8020/api";
export async function json(request: APIRequestContext, path: string) {
  const r = await request.get(BASE + path);
  expect(r.ok(), path).toBeTruthy();
  return r.json();
}
export async function fixture(
  request: APIRequestContext,
  tag: string,
  options: {
    rising?: boolean;
    missingMedication?: boolean;
    missingSteps?: boolean;
  } = {},
) {
  const id = `WB-${tag.replace(/[^a-zA-Z0-9-]/g, "") || "case"}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
  const created = await request.post(BASE + "/patients", {
    data: {
      id,
      name: `工作台${tag}（虚构）`,
      age: 52,
      duration_years: 5,
      goals: ["保持记录"],
      is_synthetic: true,
    },
  });
  expect(created.status()).toBe(201);
  const health = await json(request, "/health");
  const now = Date.parse(health.time);
  const values = options.rising ? [7, 7.7, 8.3, 8.9] : [7, 7];
  for (let i = 0; i < values.length; i++) {
    const r = await request.post(BASE + `/patients/${id}/records`, {
      data: {
        kind: "fasting_glucose",
        value: values[i],
        recorded_at: new Date(
          now - (values.length - i) * 86400000,
        ).toISOString(),
        trigger_agent: false,
      },
    });
    expect(r.status()).toBe(201);
  }
  for (const [kind, value] of [
    ...(options.missingSteps ? [] : [["steps", 6000]]),
    ...(options.missingMedication ? [] : [["medication_taken", 1]]),
  ]) {
    expect(
      (
        await request.post(BASE + `/patients/${id}/records`, {
          data: { kind, value, trigger_agent: false },
        })
      ).status(),
    ).toBe(201);
  }
  return id;
}
export async function visit(page: Page, path: string, patient?: string) {
  await page.goto(
    path +
      (patient
        ? (path.includes("?") ? "&" : "?") +
          "patient=" +
          encodeURIComponent(patient)
        : ""),
  );
  await expect(page.locator("header")).toContainText("后端已连接");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.locator("main .ant-spin-spinning")).toHaveCount(0, { timeout: 30000 });
}
export async function evidence(name: string, data: unknown) {
  await fs.mkdir("docs/evidence/workbench", { recursive: true });
  await fs.writeFile(
    `docs/evidence/workbench/${name}.json`,
    JSON.stringify(data, null, 2),
  );
}
export async function select(page: Page, label: string, value: string) {
  await page.getByLabel(label, { exact: true }).click();
  await page
    .locator(".ant-select-dropdown:visible")
    .getByText(value, { exact: true })
    .click();
}
