import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AsyncState } from './AsyncState';

describe('AsyncState', () => {
  it('renders a retryable network error as an alert', () => {
    const onRetry = vi.fn();
    render(<AsyncState state="network-error" onRetry={onRetry} />);

    expect(screen.getByTestId('state-network-error')).toHaveAttribute('role', 'alert');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
