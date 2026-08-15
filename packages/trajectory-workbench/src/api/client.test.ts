import { describe, expect, it, vi } from 'vitest';
import type { ExecutionSlice } from './types';
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

  it('requests exact execution slices by encoded run id and sequence with abort support', async () => {
    const controller = new AbortController();
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      analysis_id: 'analysis/test',
      source_sequence: 48,
      turn: null,
      unavailable_reason: 'no durable execution linkage is recorded',
    }), { status: 200 }));
    const client = new TrajectoryApiClient(fetcher);

    await client.getExecutionSlice('analysis/test', 48, controller.signal);

    expect(fetcher).toHaveBeenCalledWith(
      '/api/runs/analysis%2Ftest/execution?at_sequence=48',
      expect.objectContaining({
        method: 'GET',
        credentials: 'same-origin',
        signal: controller.signal,
      }),
    );
  });

  it('accepts execution turns without the paged agent source_sequence scalar', async () => {
    const responseBody: ExecutionSlice = {
      analysis_id: 'analysis-test',
      source_sequence: 48,
      unavailable_reason: null,
      turn: {
        id: 'agent:analysis-test:t007',
        source: 'observed',
        source_sequences: [45],
        rule_id: null,
        status: 'completed',
        unavailable_reason: null,
        turn_id: 'analysis-test-t007',
        ordinal: 7,
        steps: [],
      },
    };
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(responseBody), { status: 200 }));
    const client = new TrajectoryApiClient(fetcher);

    const slice = await client.getExecutionSlice('analysis-test', 48);

    expect(slice.turn?.turn_id).toBe('analysis-test-t007');
    expect(slice.turn?.source_sequences).toEqual([45]);
    expect(slice.turn?.source_sequence).toBeUndefined();
  });
});
