import { defineConfig } from '@playwright/test';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const packageRoot = dirname(fileURLToPath(import.meta.url));

// The operator environment may proxy HTTP generally; a test server must never
// leave the host, and Playwright's readiness probe must bypass that proxy too.
process.env.NO_PROXY = [process.env.NO_PROXY, '127.0.0.1', 'localhost'].filter(Boolean).join(',');
process.env.no_proxy = process.env.NO_PROXY;

/** The browser suite always exercises the Vite app through a loopback origin. */
export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.ts',
  fullyParallel: false,
  use: {
    baseURL: 'http://127.0.0.1:4174',
    // Local fallback while the Playwright Chromium archive is unavailable.
    // Clean environments still install the pinned Playwright Chromium first.
    channel: 'chrome',
    launchOptions: { args: ['--no-proxy-server'] },
    viewport: { width: 1440, height: 960 },
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `node ./node_modules/vite/bin/vite.js "${packageRoot}" --host 127.0.0.1 --port 4174 --strictPort`,
    url: 'http://127.0.0.1:4174',
    // Workbench validation is intentionally loopback-only; reusing an already
    // running local Vite instance keeps focused reruns deterministic as well.
    reuseExistingServer: true,
    timeout: 30_000,
    cwd: packageRoot,
  },
});
