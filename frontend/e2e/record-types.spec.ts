import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";

test("真实录入步数和服药确认，切换类型不沿用数值或单位", async ({ page }) => {
  await page.goto("/records");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("张伟");
  await page.getByLabel("当前演示患者").click();
  await page.getByText(/ · P003$/, { exact: false }).click();
  await expect(page.getByRole("heading", { level: 1 })).not.toContainText(
    "张伟",
  );
  await expect(page.locator(".ant-spin-spinning")).toHaveCount(0);
  await page.getByLabel("记录数值", { exact: true }).fill("9.6");
  await page.getByLabel("单位（留空使用后端默认单位）").fill("mmol/L");
  await page.getByLabel("记录类型").click();
  await page
    .locator(".ant-select-dropdown:visible")
    .getByText("活动步数", { exact: true })
    .click();
  await expect(page.getByLabel("记录数值", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("单位（留空使用后端默认单位）")).toHaveValue("");
  await page.getByLabel("记录数值", { exact: true }).fill("4000");
  const results: unknown[] = [];
  async function save(kind: string, value: number) {
    const received = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url().endsWith("/patients/P003/records"),
    );
    await page.getByRole("button", { name: "保存并查看自动触发结果" }).click();
    const response = await received;
    expect(response.status()).toBe(201);
    const body = await response.json();
    expect(body.record).toMatchObject({ patient_id: "P003", kind, value });
    results.push(body);
    await expect(
      page.getByRole("button", { name: "保存并查看自动触发结果" }),
    ).toBeEnabled();
  }
  await save("steps", 4000);
  await page.getByLabel("记录类型").click();
  await page
    .locator(".ant-select-dropdown:visible")
    .getByText("服药确认", { exact: true })
    .click();
  await page.getByLabel("服药确认（按原处方）", { exact: true }).click();
  await page.getByText("已按原处方服药", { exact: true }).click();
  await save("medication_taken", 1);
  await fs.writeFile(
    "docs/evidence/record-types-api.json",
    JSON.stringify(results, null, 2),
  );
});
