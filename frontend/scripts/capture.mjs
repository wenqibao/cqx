import { chromium, expect } from "@playwright/test";
import fs from "node:fs/promises";
const { runId } = JSON.parse(
  await fs.readFile("docs/evidence/real-api.json", "utf8"),
);
const b = await chromium.launch({ channel: "chrome" });
try {
  const p = await b.newPage({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: "reduce",
  });
  for (const [path, name] of [
    ["/", "overview"],
    ["/records", "records"],
    ["/tasks", "tasks"],
    ["/runs", "runs"],
    [`/runs?run=${runId}`, "trace"],
  ]) {
    await p.goto("http://127.0.0.1:5180" + path);
    await expect(p.getByRole("heading", { level: 1 })).toContainText("张伟");
    await expect(p.locator(".ant-spin-spinning")).toHaveCount(0);
    if (name === "trace") {
      await expect(p.getByRole("dialog")).toContainText("tool_call");
      // Wait for the drawer's actual transform to settle before collecting evidence.
      await expect
        .poll(() =>
          p
            .locator(".ant-drawer-content-wrapper")
            .evaluate((el) => Math.round(el.getBoundingClientRect().x)),
        )
        .toBe(704);
    }
    await p.screenshot({
      path: `docs/evidence/${name}-1440.png`,
      fullPage: true,
      animations: "disabled",
    });
  }
} finally {
  await b.close();
}
