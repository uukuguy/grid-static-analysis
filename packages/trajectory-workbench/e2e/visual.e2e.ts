import { expect, test } from '@playwright/test';
import { mockWorkbenchApi } from './fixtures';

async function ready(page: Parameters<typeof mockWorkbenchApi>[0], width: number, colorScheme: 'dark' | 'light' = 'dark', count = 1) {
  await mockWorkbenchApi(page, 'ready', count);
  await page.setViewportSize({ width, height: 1000 });
  await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' });
  await page.goto('/');
  await expect(page.getByLabel('Trajectory views').getByRole('tab', { name: 'Business' })).toBeVisible();
}

test('approved wide dark business workbench', async ({ page }) => {
  await ready(page, 1600);
  await page.getByRole('button', { name: /Q7.*overview segment/i }).click();
  await expect(page).toHaveScreenshot('business-q7-dark-wide.png', { animations: 'disabled', fullPage: true });
});

test('approved wide light business workbench', async ({ page }) => {
  await ready(page, 1600, 'light');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  expect(await page.locator('html').evaluate((element) => getComputedStyle(element).backgroundColor))
    .toBe('rgb(247, 249, 252)');
  await expect(page).toHaveScreenshot('business-light-wide.png', { animations: 'disabled', fullPage: true });
});

test('all four audit inspector panels have reviewed wide baselines', async ({ page }) => {
  await ready(page, 1600, 'dark', 10);
  await page.getByTestId('causal-node-claim:7').click();
  const inspector = page.getByTestId('audit-inspector');
  for (const panel of ['Overview', 'Evidence', 'Context', 'Execution']) {
    await inspector.getByRole('tab', { name: panel }).click();
    await expect(page.getByTestId(`audit-panel-${panel.toLowerCase()}`)).toBeVisible();
    await expect(page).toHaveScreenshot(`audit-inspector-${panel.toLowerCase()}.png`, { animations: 'disabled', fullPage: true });
  }
});

test('dark medium layout keeps a resizable right inspector without page overflow', async ({ page }) => {
  await ready(page, 1024);
  await expect(page.getByRole('complementary', { name: 'Trajectory inspector' })).toBeVisible();
  await expect(page.getByRole('separator', { name: 'Resize trajectory inspector' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(page).toHaveScreenshot('business-dark-medium.png', { animations: 'disabled', fullPage: true });
  const inspector = page.getByRole('complementary', { name: 'Trajectory inspector' });
  const handle = page.getByRole('separator', { name: 'Resize trajectory inspector' });
  const initialWidth = await inspector.evaluate((element) => element.getBoundingClientRect().width);
  await handle.press('ArrowLeft');
  await expect(page.locator('.workbench-shell')).toHaveCSS('--inspector-width', '372px');
  await expect.poll(() => inspector.evaluate((element) => element.getBoundingClientRect().width)).toBeGreaterThan(initialWidth);
  const handleBox = await handle.boundingBox();
  if (!handleBox) throw new Error('Inspector resize handle has no bounding box');
  const keyboardWidth = await inspector.evaluate((element) => element.getBoundingClientRect().width);
  await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + handleBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(handleBox.x - 24, handleBox.y + handleBox.height / 2);
  await page.mouse.up();
  await expect.poll(() => inspector.evaluate((element) => element.getBoundingClientRect().width)).toBeGreaterThan(keyboardWidth);
});

test('narrow workbench opens the inspector as a bottom sheet without horizontal overflow', async ({ page }) => {
  await ready(page, 768);
  await expect(page.getByRole('button', { name: 'Open inspector' })).toBeVisible();
  await expect(page.getByRole('complementary', { name: 'Trajectory inspector' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Open inspector' }).click();
  await expect(page.getByRole('dialog', { name: 'Trajectory inspector' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(page).toHaveScreenshot('business-dark-narrow.png', { animations: 'disabled', fullPage: true });
});

test('agent retry, context delta, and evidence tree preserve drill-down density', async ({ page }) => {
  await ready(page, 1600);
  const viewTabs = page.getByLabel('Trajectory views');
  await viewTabs.getByRole('tab', { name: 'Agent' }).click();
  await expect(page.getByText('Retry 1 of 2')).toBeVisible();
  await expect(page).toHaveScreenshot('agent-retry.png', { animations: 'disabled', fullPage: true });
  await viewTabs.getByRole('tab', { name: 'Context', exact: true }).click();
  await page.getByRole('button', { name: /Sequence 100000.*model-request/i }).click();
  await expect(page.getByText('scenario')).toBeVisible();
  await expect(page).toHaveScreenshot('context-delta.png', { animations: 'disabled', fullPage: true });
  await viewTabs.getByRole('tab', { name: 'Evidence' }).click();
  await expect(page.getByRole('treegrid', { name: 'Evidence artifacts' })).toBeVisible();
  await expect(page).toHaveScreenshot('evidence-tree.png', { animations: 'disabled', fullPage: true });
  await page.getByRole('button', { name: 'Preview evidence:line-17' }).click();
  await expect(page.getByRole('complementary', { name: 'Artifact preview' })).toContainText('truncated at 131072 bytes');
  await expect(page).toHaveScreenshot('evidence-preview.png', { animations: 'disabled', fullPage: true });
});

for (const state of ['loading', 'empty', 'partial', 'corrupt', 'unsupported'] as const) {
  test(`state ${state} has a reviewed visual baseline`, async ({ page }) => {
    await mockWorkbenchApi(page, state);
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.goto('/');
    await expect(page.getByTestId(`state-${state}`)).toBeVisible();
    await expect(page).toHaveScreenshot(`state-${state}.png`, { animations: 'disabled', fullPage: true });
  });
}
