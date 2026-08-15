import { defineConfig } from '@playwright/test';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const packageRoot = dirname(fileURLToPath(import.meta.url));
const browserChannel = process.env.TRAJECTORY_WORKBENCH_BROWSER_CHANNEL === 'chrome' ? 'chrome' : undefined;
const reuseExistingServer = process.env.TRAJECTORY_WORKBENCH_REUSE_SERVER === '1';

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
    // Default to Playwright's pinned Chromium. Operators may opt into the
    // system Chrome channel only with TRAJECTORY_WORKBENCH_BROWSER_CHANNEL=chrome.
    ...(browserChannel ? { channel: browserChannel } : {}),
    launchOptions: { args: ['--no-proxy-server'] },
    viewport: { width: 1440, height: 960 },
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `node ./node_modules/vite/bin/vite.js "${packageRoot}" --host 127.0.0.1 --port 4174 --strictPort`,
    url: 'http://127.0.0.1:4174',
    // Reuse only when explicitly requested so CI and release validation stay hermetic.
    reuseExistingServer,
    timeout: 30_000,
    cwd: packageRoot,
  },
});
