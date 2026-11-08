import { defineConfig } from "@playwright/test";
import base from "./playwright.config";
export default defineConfig({
  ...base,
  testIgnore: [],
  testMatch: "**/contract-v021.spec.ts",
  outputDir: ".runtime/v021/test-results",
  reporter: [
    ["list"],
    ["json", { outputFile: ".runtime/v021/browser-results.json" }],
  ],
  use: {
    ...base.use,
    baseURL: process.env.CONTRACT_UI_BASE || "http://127.0.0.1:5187",
  },
  webServer: undefined,
});
