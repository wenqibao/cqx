import { test, expect } from "@playwright/test";
import { BASE, evidence, fixture, select, visit } from "./helpers";
test("八种真实记录类型、重复处理和类型切换不残留数值 [F03 F06]", async ({
  page,
  request,
}) => {
  const pid = await fixture(request, "八种记录");
  await visit(page, "/monitoring", pid);
  await page
    .getByText("保存后由后端自动检测并按需触发 Agent", { exact: true })
    .click();
  await page
    .getByLabel("记录时间（本地时间，留空使用后端演示时钟）")
    .fill(new Date().toISOString().slice(0, 16));
  const results: unknown[] = [];
  for (const [kind, title, value] of [
    ["fasting_glucose", "空腹血糖", "7.1"],
    ["postprandial_glucose", "餐后血糖", "8.2"],
    ["steps", "活动步数", "4000"],
    ["weight", "体重", "72.5"],
    ["medication_taken", "是否按时服药", "1"],
    ["symptom", "症状记录", "无明显不适（合成）"],
    ["meal", "饮食记录", "合成早餐记录"],
    ["bp", "血压", "120"],
  ] as const) {
    await select(page, "记录类型", title);
    if (["symptom", "meal"].includes(kind))
      await page
        .getByLabel(kind === "symptom" ? "症状描述" : "饮食描述")
        .fill(value);
    else if (kind === "bp") {
      await page.getByLabel("收缩压（mmHg）").fill("120");
      await page.getByLabel("舒张压（mmHg）").fill("80");
    } else if (kind === "medication_taken")
      await page.getByText("模拟确认已服药", { exact: true }).click();
    else {
      await expect(page.getByLabel("记录数值", { exact: true })).toHaveValue(
        "",
      );
      await page.getByLabel("记录数值", { exact: true }).fill(value);
    }
    const received = page.waitForResponse(
      (r) =>
        r.url().endsWith(`/patients/${pid}/records`) &&
        r.request().method() === "POST",
    );
    await page.getByRole("button", { name: "保存并查看自动触发结果" }).click();
    const response = await received;
    expect(response.status()).toBe(201);
    const saved = await response.json();
    expect(saved.record).toMatchObject({ patient_id: pid, kind });
    expect(saved.automation).toBeNull();
    results.push(saved);
    await expect(
      page.getByRole("button", { name: "保存并查看自动触发结果" }),
    ).toBeEnabled();
  }
  const duplicate = page.waitForResponse(
    (r) =>
      r.url().endsWith(`/patients/${pid}/records`) &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "保存并查看自动触发结果" }).click();
  const same = await (await duplicate).json();
  expect(same.record.duplicate).toBe(true);
  await expect(page.getByTestId("write-result")).toContainText(
    "后端判定为重复记录",
  );
  await expect(page.getByTestId("write-result")).not.toContainText("RUN-");
  await evidence("record-types-api", { pid, results, duplicate: same });
});
