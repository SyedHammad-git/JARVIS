import { defineConfig, devices } from "@playwright/test";

const baseURL = "http://localhost:3188";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  reporter: "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL,
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev -- --hostname localhost --port 3188",
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      NEXT_PUBLIC_BACKEND_URL: "http://127.0.0.1:9199",
      NEXT_PUBLIC_SITE_URL: baseURL,
      NEXT_PUBLIC_DOWNLOAD_URL: "",
      NEXT_PUBLIC_DOWNLOAD_SHA256: "",
    },
  },
});
