import { expect, test } from '@playwright/test';
import { mockWorkbenchApi } from './fixtures';

async function ready(page: Parameters<typeof mockWorkbenchApi>[0], width: number, colorScheme: 'dark' | 'light' = 'dark') {
  await mockWorkbenchApi(page);
  await page.setViewportSize({ width, height: 1000 });
  await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' });
  await page.goto('/');
  await expect(page.getByRole('tab', { name: 'Business' })).toBeVisible();
}

test('approved wide dark business workbench', async ({ page }) => {
  await ready(page, 1600);
  await page.getByRole('button', { name: /Q7.*overview segment/i }).click();
  await expect(page).toHaveScreenshot('business-q7-dark-wide.png', { animations: 'disabled', fullPage: true });
});

test('approved wide light business workbench', async ({ page }) => {
  await ready(page, 1600, 'light');
  await expect(page).toHaveScreenshot('business-light-wide.png', { animations: 'disabled', fullPage: true });
});

test('dark medium layout preserves the inspector', async ({ page }) => {
  await ready(page, 1024);
  await expect(page.getByRole('complementary', { name: 'Trajectory inspector' })).toBeVisible();
  await expect(page).toHaveScreenshot('business-dark-medium.png', { animations: 'disabled', fullPage: true });
});

test('narrow workbench exposes the inspector without horizontal overflow', async ({ page }) => {
  await ready(page, 768);
  await expect(page.getByRole('complementary', { name: 'Trajectory inspector' })).toBeVisible();
  await expect(page).toHaveScreenshot('business-dark-narrow.png', { animations: 'disabled', fullPage: true });
});

test('agent retry, context delta, and evidence tree preserve drill-down density', async ({ page }) => {
  await ready(page, 1600);
  await page.getByRole('tab', { name: 'Agent' }).click();
  await expect(page.getByText('Retry 1 of 2')).toBeVisible();
  await expect(page).toHaveScreenshot('agent-retry.png', { animations: 'disabled', fullPage: true });
  await page.getByRole('tab', { name: 'Context', exact: true }).click();
  await expect(page.getByText('scenario')).toBeVisible();
  await expect(page).toHaveScreenshot('context-delta.png', { animations: 'disabled', fullPage: true });
  await page.getByRole('tab', { name: 'Evidence' }).click();
  await expect(page.getByRole('treegrid', { name: 'Evidence artifacts' })).toBeVisible();
  await expect(page).toHaveScreenshot('evidence-tree.png', { animations: 'disabled', fullPage: true });
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
