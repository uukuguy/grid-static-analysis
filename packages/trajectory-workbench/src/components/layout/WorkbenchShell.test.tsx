import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WorkbenchShell } from './WorkbenchShell';

const mobileQuery = '(max-width: 720px)';

function renderMobileShell() {
  vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
    matches: query === mobileQuery,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })));
  render(<WorkbenchShell explorer={<p>Runs</p>} header={<p>Header</p>} timeline={<p>Timeline</p>} content={<button type="button">Content action</button>} inspector={<><button type="button">Identity</button><button type="button">Artifacts</button></>} />);
}

describe('WorkbenchShell mobile inspector', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('opens the mobile inspector as a modal bottom sheet and focuses its close control', async () => {
    renderMobileShell();

    const trigger = screen.getByRole('button', { name: 'Open inspector' });
    expect(screen.queryByRole('dialog', { name: 'Trajectory inspector' })).not.toBeInTheDocument();

    fireEvent.click(trigger);

    const sheet = screen.getByRole('dialog', { name: 'Trajectory inspector' });
    expect(sheet).toHaveAttribute('aria-modal', 'true');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Close inspector' })).toHaveFocus());
  });

  it('traps focus in the mobile sheet and restores it to its trigger when closed', async () => {
    renderMobileShell();
    const trigger = screen.getByRole('button', { name: 'Open inspector' });
    fireEvent.click(trigger);

    const close = await screen.findByRole('button', { name: 'Close inspector' });
    const lastControl = screen.getByRole('button', { name: 'Artifacts' });
    lastControl.focus();
    fireEvent.keyDown(lastControl, { key: 'Tab' });
    expect(close).toHaveFocus();

    fireEvent.keyDown(close, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Trajectory inspector' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
