import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "e2e",
  testIgnore: "**/contract-v021.spec.ts",
  globalSetup: './e2e/guard.ts',
  timeout: 60000,
  workers: 1,
  retries: 0,
  reporter: [
    ["list"],
    ["json", { outputFile: "docs/evidence/workbench/browser-results.json" }],
  ],
  use: {
    actionTimeout:15000,
    navigationTimeout:20000,
    channel: "chrome",
    baseURL: "http://127.0.0.1:5180",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev -- --port 5180 --strictPort",
    url: "http://127.0.0.1:5180",
    reuseExistingServer: true,
    env: {VITE_API_MODE:'http',VITE_API_BASE_URL:process.env.WORKBENCH_API_BASE||'http://127.0.0.1:8020/api'},
  },
});
