import { expect, test } from '@playwright/test';
import { mockWorkbenchApi } from './fixtures';

test('desktop audit density shows ten causal rows and all three audit regions at 1440px', async ({ page }) => {
  await mockWorkbenchApi(page, 'ready', 10);
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');

  await expect(page.getByTestId('audit-rail')).toBeVisible();
  await expect(page.locator('[data-testid^="causal-node-"]')).toHaveCount(10);
  await expect(page.getByTestId('audit-inspector')).toBeVisible();
});

test('claim investigation reaches evidence, context, and execution without a route reload', async ({ page }) => {
  await mockWorkbenchApi(page, 'ready', 10);
  await page.goto('/');
  const initialNavigationEntries = await page.evaluate(() => performance.getEntriesByType('navigation').length);

  await page.getByTestId('causal-node-claim:7').click();
  for (const panel of ['Evidence', 'Context', 'Execution']) {
    await page.getByTestId('audit-inspector').getByRole('tab', { name: panel }).click();
    await expect(page.getByTestId(`audit-panel-${panel.toLowerCase()}`)).toBeVisible();
    await expect.poll(() => page.evaluate(() => performance.getEntriesByType('navigation').length)).toBe(initialNavigationEntries);
  }
});

test('100k trajectory remains cursor-paginated and mounts a bounded row window', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', (request) => { if (new URL(request.url()).pathname.startsWith('/api/')) requests.push(request.url()); });
  await mockWorkbenchApi(page, 'ready', 500);
  await page.goto('/');
  await page.waitForTimeout(500);
  const browserResources = await page.evaluate(() => ({
    pageUrl: location.href,
    resources: performance.getEntriesByType('resource').map((entry) => entry.name).filter((name) => name.includes('/api/')),
  }));
  expect(browserResources.resources).toContain('http://127.0.0.1:4174/api/runs');
  await expect(page.getByRole('list', { name: 'Business trajectory' })).toBeVisible();
  expect(requests.filter((url) => new URL(url).pathname.endsWith('/business'))).toHaveLength(1);
  expect(requests.some((url) => new URL(url).pathname.includes('run-events'))).toBeFalsy();
  expect(await page.getByRole('listitem').count()).toBeLessThanOrEqual(120);
  await page.getByRole('button', { name: 'Load older history' }).click();
  await expect(page.getByText('older cursor unavailable')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry older history' })).toBeVisible();

  await page.getByRole('button', { name: 'Retry older history' }).click();

  await expect(page.getByText('1001 matching events')).toBeVisible();
  expect(requests.filter((url) => new URL(url).searchParams.get('cursor') === 'b3BhcXVlLWJ1c2luZXNzLWJlZm9yZS05OTUwMQ')).toHaveLength(2);
  expect(await page.getByRole('listitem').count()).toBeLessThanOrEqual(120);
});

test('API-only e2e never requests a mutating endpoint', async ({ page }) => {
  const methods: string[] = [];
  page.on('request', (request) => { if (new URL(request.url()).pathname.startsWith('/api/')) methods.push(request.method()); });
  await mockWorkbenchApi(page);
  await page.goto('/');
  await page.getByLabel('Trajectory views').getByRole('tab', { name: 'Evidence' }).click();
  await expect(page.getByRole('treegrid', { name: 'Evidence artifacts' })).toBeVisible();
  expect(methods).not.toContain('POST');
  expect(methods).not.toContain('PUT');
  expect(methods).not.toContain('PATCH');
  expect(methods).not.toContain('DELETE');
});
