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
  const viewTabs = page.getByLabel('Trajectory views');
  await expect(viewTabs.getByRole('tab', { name: 'Business' })).toBeVisible();
  for (const view of ['Business', 'Agent', 'Context', 'Evidence']) {
    await viewTabs.getByRole('tab', { name: view, exact: true }).click();
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations.filter((violation) => ['serious', 'critical'].includes(violation.impact ?? ''))).toEqual([]);
  }
});

test('all four audit inspector panels have no serious accessibility violations', async ({ page }) => {
  await mockWorkbenchApi(page, 'ready', 10);
  await page.goto('/');
  await page.getByTestId('causal-node-claim:7').click();
  const inspector = page.getByTestId('audit-inspector');
  for (const panel of ['Overview', 'Evidence', 'Context', 'Execution']) {
    await inspector.getByRole('tab', { name: panel }).click();
    await expect(page.getByTestId(`audit-panel-${panel.toLowerCase()}`)).toBeVisible();
    const results = await new AxeBuilder({ page }).include('[data-testid="audit-inspector"]').analyze();
    expect(results.violations.filter((violation) => ['serious', 'critical'].includes(violation.impact ?? ''))).toEqual([]);
  }
});

test('keyboard-only tab and agent-tree navigation remain operable', async ({ page }) => {
  await mockWorkbenchApi(page);
  await page.goto('/');
  const viewTabs = page.getByLabel('Trajectory views');
  await viewTabs.getByRole('tab', { name: 'Business' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(viewTabs.getByRole('tab', { name: 'Agent' })).toBeFocused();
  await page.keyboard.press('Enter');
  const turn = page.getByRole('row', { name: /Turn 7/ });
  await turn.focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('row', { name: /Step 7.1/ })).toBeFocused();
});

test('context replay selects only loaded authoritative frames without accessibility violations', async ({ page }) => {
  await mockWorkbenchApi(page);
  await page.goto('/');
  await page.getByLabel('Trajectory views').getByRole('tab', { name: 'Context' }).click();

  const older = page.getByRole('button', { name: /Sequence 99999.*tool-result/i });
  await expect(older).toBeVisible();
  await older.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Authoritative state at sequence 99999' })).toBeVisible();
  await page.getByRole('button', { name: 'Next loaded frame' }).click();
  await expect(page.getByRole('heading', { name: 'Authoritative state at sequence 100000' })).toBeVisible();

  const results = await new AxeBuilder({ page }).include('[aria-label="Context time travel"]').analyze();
  expect(results.violations.filter((violation) => ['serious', 'critical'].includes(violation.impact ?? ''))).toEqual([]);
});

test('context comparison pins two exact recorded frames without accessibility violations', async ({ page }) => {
  await mockWorkbenchApi(page);
  await page.goto('/');
  await page.getByLabel('Trajectory views').getByRole('tab', { name: 'Context' }).click();

  await page.getByRole('button', { name: /Sequence 99999.*tool-result/i }).click();
  await page.getByRole('button', { name: 'Pin sequence 99999 as frame A' }).click();
  await page.getByRole('button', { name: /Sequence 100000.*model-request/i }).click();
  await page.getByRole('button', { name: 'Pin sequence 100000 as frame B' }).click();

  const comparison = page.getByRole('region', { name: 'Pinned frame comparison' });
  await expect(comparison).toContainText('A · sequence 99999');
  await expect(comparison).toContainText('B · sequence 100000');
  await expect(comparison).toContainText('mode');
  await expect(comparison).toContainText('limits.x');
  const results = await new AxeBuilder({ page }).include('[aria-label="Pinned frame comparison"]').analyze();
  expect(results.violations.filter((violation) => ['serious', 'critical'].includes(violation.impact ?? ''))).toEqual([]);
});
