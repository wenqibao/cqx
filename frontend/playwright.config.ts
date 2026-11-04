import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "e2e",
  workers: 1,
  retries: 0,
  reporter: [
    ["list"],
    ["json", { outputFile: "docs/evidence/browser-results.json" }],
  ],
  use: {
    channel: "chrome",
    baseURL: "http://127.0.0.1:5180",
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev -- --port 5180 --strictPort",
    url: "http://127.0.0.1:5180",
    reuseExistingServer: true,
  },
});
