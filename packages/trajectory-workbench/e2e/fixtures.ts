import type { Page } from '@playwright/test';
import type { BusinessNode, BusinessProblemSummary } from '../src/api/types';

export type Scenario = 'ready' | 'loading' | 'empty' | 'partial' | 'corrupt' | 'unsupported' | 'network-error';

const run = {
  analysis_id: 'analysis-test', status: 'completed', source_kind: 'native',
  started_at: '2026-08-14T08:18:22Z', turn_count: 9, last_sequence: 100_000,
  replay_trusted_through: 100_000, diagnostic: null,
};

const claimSequence = 99_997;
const newestBusinessCursor = 'b3BhcXVlLWJ1c2luZXNzLWJlZm9yZS05OTUwMQ';
const olderBusinessCursor = 'b3BhcXVlLWJ1c2luZXNzLWJlZm9yZS05OTAwMQ';

function node(sequence: number): BusinessNode {
  const isClaim = sequence === claimSequence;
  return {
    id: isClaim ? 'claim:7' : `business:${sequence}`, source: sequence % 3 === 0 ? 'agent-declared' : 'observed', source_sequences: [sequence], rule_id: null,
    status: 'completed', unavailable_reason: null, source_sequence: sequence, kind: isClaim ? 'claim' : 'tool',
    title: isClaim ? 'N-1 conclusion for line 17' : `Recorded business event ${sequence}`,
    detail: 'Recorded deterministic projection detail.', refs: isClaim ? ['evidence:line-17'] : [],
  };
}

export function businessPage(count = 1) {
  const nodes = Array.from({ length: count }, (_, offset) => node(100_000 - count + offset + 1));
  const hasOlder = count === 500;
  const problem: BusinessProblemSummary = {
    id: 'business:7', source: 'derived', rule_id: 'business/v1',
    status: 'completed', unavailable_reason: null,
    turn_id: 'analysis-test-t007', title: 'Q7 · Line 17 N-1',
    first_sequence: hasOlder ? 1 : nodes[0]?.source_sequence ?? 1,
    last_sequence: nodes.at(-1)?.source_sequence ?? 1,
    node_count: hasOlder ? 100_000 : nodes.length,
  };
  const items = nodes.map((item) => causalRow(problem, item));
  return {
    analysis_id: 'analysis-test',
    items,
    older_cursor: hasOlder ? newestBusinessCursor : null, newer_cursor: null,
    first_sequence: nodes[0]?.source_sequence ?? null, last_sequence: nodes.at(-1)?.source_sequence ?? null,
    has_older: hasOlder, encoded_bytes: encodedBytes(items),
  };
}

function olderBusinessPage() {
  const nodes = Array.from({ length: 500 }, (_, offset) => node(99_001 + offset));
  const problem: BusinessProblemSummary = {
    id: 'business:7', source: 'derived', rule_id: 'business/v1',
    status: 'completed', unavailable_reason: null,
    turn_id: 'analysis-test-t007', title: 'Q7 · Line 17 N-1',
    first_sequence: 1, last_sequence: 100_000, node_count: 100_000,
  };
  const items = nodes.map((item) => causalRow(problem, item));
  return {
    analysis_id: 'analysis-test',
    items,
    newer_cursor: null,
    first_sequence: 99_001,
    last_sequence: 99_500,
    encoded_bytes: encodedBytes(items),
    older_cursor: olderBusinessCursor,
    has_older: true,
  };
}

function causalRow(problem: BusinessProblemSummary, item: BusinessNode) {
  const { source_sequence, ...causalNode } = item;
  return {
    id: `${problem.id}:sequence:${source_sequence}`,
    source_sequence,
    problem,
    nodes: [causalNode],
  };
}

function encodedBytes(items: unknown[]) {
  return items.reduce((total, item) => total + new TextEncoder().encode(JSON.stringify(item)).length + 1, 0);
}

const agentPage = {
  analysis_id: 'analysis-test',
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

function contextFrameAt(sequence: number) {
  return { ...contextFrame, id: `context:${sequence}`, source_sequences: [sequence], source_sequence: sequence, max_sequence: sequence };
}

const evidenceIndex = { analysis_id: 'analysis-test', records: {
  'evidence:line-17': {
    id: 'evidence:line-17', source: 'observed', source_sequences: [claimSequence], rule_id: null, status: 'completed', unavailable_reason: null,
    reference: 'evidence:line-17', kind: 'gridctl result', relative_path: 'evidence/line-17.json', sha256: 'a'.repeat(64), verification_status: 'verified',
    producing_sequence: claimSequence, consuming_sequences: [100_000], turn_id: 'analysis-test-t007', step_id: null, request_id: null,
    tool_call_id: 'call:17', result_id: 'result:17', evidence_id: 'evidence:line-17', claim_id: 'claim:17',
  },
} };

function executionSliceAt(sequence: number) {
  return {
    analysis_id: 'analysis-test', source_sequence: sequence, unavailable_reason: null,
    lineage: {
      business_node_ids: sequence === claimSequence ? ['claim:7'] : [`business:${sequence}`],
      artifact_refs: sequence === claimSequence ? ['evidence:line-17'] : [],
      agent_node_ids: ['turn:7', 'step:7:claim', 'request:7:claim', 'tool:line-17'],
      turn_ids: ['analysis-test-t007'], step_ids: ['analysis-test-t007-s002'],
      request_ids: ['request:7:claim'], tool_call_ids: ['call:17'], result_ids: ['result:17'],
    },
    turn: {
      id: 'turn:7', source: 'observed', source_sequences: [sequence], rule_id: null, status: 'completed', unavailable_reason: null,
      turn_id: 'analysis-test-t007', ordinal: 7, steps: [{
        id: 'step:7:claim', source: 'observed', source_sequences: [sequence], rule_id: null, status: 'completed', unavailable_reason: null,
        step_id: 'analysis-test-t007-s002', request: {
          id: 'request:7:claim', source: 'observed', source_sequences: [sequence], rule_id: null, status: 'completed', unavailable_reason: null,
          request_id: 'request:7:claim', artifact_ref: 'artifact:request-input', retries: [], tools: [{
            id: 'tool:line-17', source: 'observed', source_sequences: [sequence], rule_id: null, status: 'completed', unavailable_reason: null,
            tool_call_id: 'call:17', capability: 'gridctl.contingency', start_sequence: sequence, end_sequence: sequence,
            ok: true, duration_seconds: 0.42, artifact_ref: 'evidence:line-17', result_id: 'result:17', evidence_ref: 'evidence:line-17',
          }], response: null,
        },
      }],
    },
  };
}

export async function mockWorkbenchApi(page: Page, scenario: Scenario = 'ready', count = 1) {
  let olderBusinessAttempts = 0;
  // Match the API root, not source modules such as `/src/api/client.ts`.
  await page.route((url) => url.pathname.startsWith('/api/runs'), async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
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
    if (path.endsWith('/business')) {
      if (url.searchParams.has('cursor')) {
        olderBusinessAttempts += 1;
        if (olderBusinessAttempts === 1) return route.fulfill({ status: 503, json: { code: 'cursor_failed', message: 'older cursor unavailable' } });
        return route.fulfill({ json: olderBusinessPage() });
      }
      return route.fulfill({ json: scenario === 'empty' ? { ...businessPage(0), items: [] } : businessPage(count) });
    }
    if (path.endsWith('/agent')) return route.fulfill({ json: agentPage });
    if (path.includes('/context')) return route.fulfill({ json: contextFrameAt(Number(url.searchParams.get('at_sequence') ?? run.last_sequence)) });
    if (path.endsWith('/execution')) return route.fulfill({ json: executionSliceAt(Number(url.searchParams.get('at_sequence') ?? run.last_sequence)) });
    if (path.endsWith('/evidence')) return route.fulfill({ json: evidenceIndex });
    return route.fulfill({ status: 404, json: { code: 'not_found', message: 'not found' } });
  });
}
