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
      lineage: null,
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
      lineage: {
        business_node_ids: [], artifact_refs: [],
        agent_node_ids: ['agent:analysis-test:t007'], turn_ids: ['analysis-test-t007'],
        step_ids: [], request_ids: [], tool_call_ids: [], result_ids: [],
      },
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

  it('encodes typed operational page cursors and filters without null query values', async () => {
    const fetcher = vi.fn().mockImplementation(async () => new Response(JSON.stringify({
      analysis_id: 'analysis/test', items: [], older_cursor: null, newer_cursor: null,
      first_sequence: null, last_sequence: null, has_older: false, encoded_bytes: 0,
    }), { status: 200 }));
    const client = new TrajectoryApiClient(fetcher);
    const controller = new AbortController();

    await client.getAgentPage('analysis/test', {
      cursor: 'agent/cursor', filters: { kind: 'tool', status: null, q: 'voltage' },
    }, controller.signal);
    await client.getContextPage('analysis/test', {
      filters: { from_sequence: 7, changed: false },
    }, controller.signal);
    await client.getEvidencePage('analysis/test', {
      cursor: 'evidence/cursor', filters: { source: 'observed', sort: 'verification_status' },
    }, controller.signal);

    expect(fetcher.mock.calls.map(([path]) => path)).toEqual([
      '/api/runs/analysis%2Ftest/agent?cursor=agent%2Fcursor&kind=tool&q=voltage',
      '/api/runs/analysis%2Ftest/context?changed=false&from_sequence=7',
      '/api/runs/analysis%2Ftest/evidence?cursor=evidence%2Fcursor&sort=verification_status&source=observed',
    ]);
    expect(fetcher.mock.calls.every(([, init]) => init.signal === controller.signal)).toBe(true);
  });
});
