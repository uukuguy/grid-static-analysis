import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { mockWorkbenchApi } from './fixtures';

test('all trajectory states remain useful and non-destructive', async ({ page }) => {
  for (const state of ['loading', 'empty', 'partial', 'corrupt', 'unsupported', 'network-error'] as const) {
    await mockWorkbenchApi(page, state);
    await page.goto('/');
    await expect(page.getByTestId(`state-${state}`)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Delete run' })).toHaveCount(0);
  }
});

test('all four workbench views have no serious accessibility violations', async ({ page }) => {
  await mockWorkbenchApi(page);
  await page.goto('/');
  await expect(page.getByRole('tab', { name: 'Business' })).toBeVisible();
  for (const view of ['Business', 'Agent', 'Context', 'Evidence']) {
    await page.getByRole('tab', { name: view, exact: true }).click();
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations.filter((violation) => ['serious', 'critical'].includes(violation.impact ?? ''))).toEqual([]);
  }
});

test('keyboard-only tab and agent-tree navigation remain operable', async ({ page }) => {
  await mockWorkbenchApi(page);
  await page.goto('/');
  await page.getByRole('tab', { name: 'Business' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab', { name: 'Agent' })).toBeFocused();
  await page.keyboard.press('Enter');
  const treeItem = page.getByRole('treeitem').first();
  await treeItem.focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('treeitem').nth(1)).toBeFocused();
});
