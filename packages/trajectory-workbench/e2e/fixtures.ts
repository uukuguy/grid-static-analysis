import type { Page } from '@playwright/test';

export type Scenario = 'ready' | 'loading' | 'empty' | 'partial' | 'corrupt' | 'unsupported' | 'network-error';

const run = {
  analysis_id: 'analysis-test', status: 'completed', source_kind: 'native',
  started_at: '2026-08-14T08:18:22Z', turn_count: 9, last_sequence: 100_000,
  replay_trusted_through: 100_000, diagnostic: null,
};

function node(sequence: number) {
  return {
    id: `business:${sequence}`, source: sequence % 3 === 0 ? 'agent-declared' : 'observed', source_sequences: [sequence], rule_id: null,
    status: 'completed', unavailable_reason: null, source_sequence: sequence, kind: sequence === 99_750 ? 'claim' : 'tool',
    title: sequence === 99_750 ? 'N-1 conclusion for line 17' : `Recorded business event ${sequence}`,
    detail: 'Recorded deterministic projection detail.', refs: sequence === 99_750 ? ['evidence:line-17'] : [],
  };
}

export function businessPage(count = 1) {
  const nodes = Array.from({ length: count }, (_, offset) => node(100_000 - count + offset + 1));
  return {
    items: [{
      id: 'business:7', source: 'derived', source_sequences: nodes.map((item) => item.source_sequence), rule_id: 'business/v1',
      status: 'completed', unavailable_reason: null, source_sequence: nodes[0]?.source_sequence ?? 100_000,
      turn_id: 'analysis-test-t007', title: 'Q7 · Line 17 N-1', nodes,
    }],
    older_cursor: count >= 500 ? 'before:99501' : null, newer_cursor: null,
    first_sequence: nodes[0]?.source_sequence ?? null, last_sequence: nodes.at(-1)?.source_sequence ?? null,
    has_older: count >= 500, encoded_bytes: JSON.stringify(nodes).length,
  };
}

const agentPage = {
  items: [{
    id: 'turn:7', source: 'observed', source_sequences: [99_700, 100_000], rule_id: null, status: 'completed', unavailable_reason: null,
    source_sequence: 99_700, turn_id: 'analysis-test-t007', ordinal: 7, steps: [{
      id: 'step:7:1', source: 'observed', source_sequences: [99_701], rule_id: null, status: 'completed', unavailable_reason: null,
      step_id: 'analysis-test-t007-s001', request: {
        id: 'request:7', source: 'observed', source_sequences: [99_702], rule_id: null, status: 'completed', unavailable_reason: null,
        request_id: 'request:7', artifact_ref: 'artifact:request-input', retries: [{
          id: 'retry:7:1', source: 'observed', source_sequences: [99_703], rule_id: null, status: 'completed', unavailable_reason: null,
          attempt: 1, max_attempts: 2, delay_seconds: 0.5, message: 'Retry after timeout',
        }], tools: [], response: null,
      },
    }],
  }], older_cursor: null, newer_cursor: null, first_sequence: 99_700, last_sequence: 100_000, has_older: false, encoded_bytes: 100,
};

const contextFrame = {
  id: 'context:100000', source: 'observed', source_sequences: [100_000], rule_id: null, status: 'completed', unavailable_reason: null,
  source_sequence: 100_000, before_revision: 59, after_revision: 78, before_state_hash: 'before', after_state_hash: 'after',
  before_state: { scenario: 'base' }, delta: { scenario: 'line-17-out' }, after_state: { scenario: 'line-17-out' },
  max_sequence: 100_000, request_artifact_ref: 'artifact:request-input',
};

const evidenceIndex = { analysis_id: 'analysis-test', records: {
  'evidence:line-17': {
    id: 'evidence:line-17', source: 'observed', source_sequences: [99_750], rule_id: null, status: 'completed', unavailable_reason: null,
    reference: 'evidence:line-17', kind: 'gridctl result', relative_path: 'evidence/line-17.json', sha256: 'a'.repeat(64), verification_status: 'verified',
    producing_sequence: 99_750, consuming_sequences: [100_000], turn_id: 'analysis-test-t007', step_id: null, request_id: null,
    tool_call_id: 'call:17', result_id: 'result:17', evidence_id: 'evidence:line-17', claim_id: 'claim:17',
  },
} };

export async function mockWorkbenchApi(page: Page, scenario: Scenario = 'ready', count = 1) {
  // Match the API root, not source modules such as `/src/api/client.ts`.
  await page.route((url) => url.pathname.startsWith('/api/runs'), async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (scenario === 'network-error') return route.abort('failed');
    if (path === '/api/runs') {
      if (scenario === 'loading') {
        await new Promise((resolve) => setTimeout(resolve, 10_000));
        return route.fulfill({ json: { items: [run] } });
      }
      if (scenario === 'unsupported') return route.fulfill({ status: 501, json: { code: 'unsupported', message: 'This trajectory cannot be rendered.' } });
      const status = scenario === 'partial' || scenario === 'corrupt' ? scenario : run.status;
      return route.fulfill({ json: { items: scenario === 'empty' ? [] : [{ ...run, status }] } });
    }
    if (path.endsWith('/business')) return route.fulfill({ json: scenario === 'empty' ? { ...businessPage(0), items: [] } : businessPage(count) });
    if (path.endsWith('/agent')) return route.fulfill({ json: agentPage });
    if (path.includes('/context')) return route.fulfill({ json: contextFrame });
    if (path.endsWith('/evidence')) return route.fulfill({ json: evidenceIndex });
    return route.fulfill({ status: 404, json: { code: 'not_found', message: 'not found' } });
  });
}
