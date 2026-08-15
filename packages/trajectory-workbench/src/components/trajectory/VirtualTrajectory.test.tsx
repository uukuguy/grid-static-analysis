import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { VirtualTrajectory, type TrajectoryItem } from './VirtualTrajectory';

const items: TrajectoryItem[] = Array.from({ length: 100_000 }, (_, index) => ({
  id: `business:${index + 1}`,
  source_sequence: index + 1,
}));

describe('VirtualTrajectory', () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, top: 0, left: 0, right: 900, bottom: 700, width: 900, height: 700, toJSON: () => ({}),
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });
  it('mounts a bounded window for 100000 business nodes', async () => {
    render(<VirtualTrajectory
      items={items}
      label="Business trajectory"
      onRequestOlder={vi.fn()}
      renderRow={(item) => <span>{item.id}</span>}
    />);

    const list = await screen.findByRole('list', { name: 'Business trajectory' });
    const mountedItems = screen.getAllByRole('listitem');
    expect(list).toBeVisible();
    expect(mountedItems[0]).toHaveAttribute('aria-setsize', '100000');
    expect(mountedItems.length).toBeLessThanOrEqual(120);
  });

  it('uses semantic item IDs as row test identifiers', async () => {
    render(<VirtualTrajectory
      items={items.slice(0, 10)}
      label="Business trajectory"
      onRequestOlder={vi.fn()}
      renderRow={(item) => <span>{item.id}</span>}
    />);

    expect(await screen.findByTestId('business:1')).toHaveAttribute('data-index', '0');
  });

  it('scrolls to an off-window focused item and focuses it after mount', async () => {
    render(<VirtualTrajectory
      items={items.slice(0, 80)}
      label="Business trajectory"
      onRequestOlder={vi.fn()}
      focusItemId="business:61"
      focusElementId="focus-business:61"
      renderRow={(item) => <button id={`focus-${item.id}`} type="button">{item.id}</button>}
    />);

    const focused = await screen.findByRole('button', { name: 'business:61' });
    expect(focused).toHaveFocus();
  });
});
