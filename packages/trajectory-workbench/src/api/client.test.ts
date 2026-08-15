import { describe, expect, it, vi } from 'vitest';
import { ApiError, TrajectoryApiClient } from './client';

describe('TrajectoryApiClient', () => {
  it('uses only same-origin GET requests', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 }));
    const client = new TrajectoryApiClient(fetcher);

    await client.listRuns();

    expect(fetcher).toHaveBeenCalledWith('/api/runs', expect.objectContaining({ method: 'GET' }));
    expect(fetcher.mock.calls[0][1].credentials).toBe('same-origin');
  });

  it('calls the default browser fetch with the global receiver', async () => {
    const fetcher = vi.fn(function (this: typeof globalThis) {
      expect(this).toBe(globalThis);
      return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 }));
    });
    vi.stubGlobal('fetch', fetcher);

    try {
      await new TrajectoryApiClient().listRuns();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('exposes the public API error payload on unsuccessful responses', async () => {
    const client = new TrajectoryApiClient(vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ code: 'run_not_found', message: 'trajectory run not found' }),
      { status: 404 },
    )));

    await expect(client.listRuns()).rejects.toMatchObject({
      status: 404, code: 'run_not_found', message: 'trajectory run not found',
    });
  });
});
