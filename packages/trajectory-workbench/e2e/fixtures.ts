import type { Page } from '@playwright/test';
import type { AgentEventRow, BusinessNode, BusinessProblemSummary } from '../src/api/types';

export type Scenario = 'ready' | 'loading' | 'empty' | 'partial' | 'corrupt' | 'unsupported' | 'network-error';

const run = {
  analysis_id: 'analysis-test', status: 'completed', source_kind: 'native',
  started_at: '2026-08-14T08:18:22Z', turn_count: 9, last_sequence: 100_000,
  replay_trusted_through: 100_000, diagnostic: null,
};

const claimSequence = 99_997;
const newestBusinessCursor = 'b3BhcXVlLWJ1c2luZXNzLWJlZm9yZS05OTUwMQ';
const olderBusinessCursor = 'b3BhcXVlLWJ1c2luZXNzLWJlZm9yZS05OTAwMQ';
const newestAgentCursor = 'b3BhcXVlLWFnZW50LWJlZm9yZS05OTUwMQ';
const newestEvidenceCursor = 'b3BhcXVlLWV2aWRlbmNlLWJlZm9yZS05OTUwMQ';

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

function agentRow(
  id: string,
  sequence: number,
  overrides: Partial<AgentEventRow> = {},
): AgentEventRow {
  return {
    id,
    parent_id: 'request:7',
    turn_id: 'analysis-test-t007',
    kind: 'tool',
    level: 4,
    source_sequence: sequence,
    source: 'observed',
    status: 'completed',
    title: 'gridctl',
    detail: null,
    ...overrides,
  };
}

function agentPage() {
  const hierarchy = [
    agentRow('turn:7', 99_501, { parent_id: null, kind: 'turn', level: 1, title: 'Turn 7' }),
    agentRow('step:7', 99_502, { parent_id: 'turn:7', kind: 'step', level: 2, title: 'Step 7.1' }),
    agentRow('request:7', 99_503, { parent_id: 'step:7', kind: 'request', level: 3, title: 'Request 7.1' }),
    agentRow('retry:7', 99_504, { kind: 'retry', title: 'Retry 1 of 2', detail: 'Delay 0.5 seconds' }),
    agentRow('tool:7', 99_505, { title: 'analysis.contingency.n_minus_one.run' }),
  ];
  const items = [
    ...hierarchy,
    ...Array.from({ length: 495 }, (_, index) => agentRow(`tool:paged:${index}`, 99_506 + index)),
  ];
  return {
    analysis_id: 'analysis-test', items,
    older_cursor: newestAgentCursor, newer_cursor: null,
    first_sequence: 99_501, last_sequence: 100_000,
    has_older: true, encoded_bytes: encodedBytes(items),
  };
}

function olderAgentPage() {
  const items = Array.from({ length: 500 }, (_, index) => agentRow(`tool:older:${index}`, 99_001 + index));
  return {
    analysis_id: 'analysis-test', items,
    older_cursor: null, newer_cursor: null,
    first_sequence: 99_001, last_sequence: 99_500,
    has_older: false, encoded_bytes: encodedBytes(items),
  };
}

const contextFrame = {
  id: 'context:100000', source: 'observed', source_sequences: [100_000], rule_id: null, status: 'completed', unavailable_reason: null,
  source_sequence: 100_000, before_revision: 59, after_revision: 78, before_state_hash: 'before', after_state_hash: 'after',
  before_state: { scenario: 'base', limits: { x: 1 } }, delta: { scenario: 'line-17-out', mode: 'n1' }, after_state: { scenario: 'line-17-out', limits: { x: 2 }, mode: 'n1' },
  max_sequence: 100_000, request_artifact_ref: 'artifact:request-input',
};

function contextFrameAt(sequence: number) {
  if (sequence === 99_999) return {
    ...contextFrame,
    id: `context:${sequence}`,
    source_sequences: [sequence],
    source_sequence: sequence,
    before_revision: 58,
    after_revision: 59,
    before_state: { scenario: 'initial', limits: { x: 1 } },
    delta: { scenario: 'base' },
    after_state: { scenario: 'base', limits: { x: 1 } },
  };
  return { ...contextFrame, id: `context:${sequence}`, source_sequences: [sequence], source_sequence: sequence };
}

function evidenceRecord(reference: string, sequence: number) {
  return {
    id: `artifact:${reference}`, source: 'observed' as const, source_sequences: [sequence], rule_id: null, status: 'completed' as const, unavailable_reason: null,
    reference, kind: 'gridctl result', relative_path: `evidence/${reference.replaceAll(':', '-')}.json`, sha256: 'a'.repeat(64), verification_status: 'verified',
    producing_sequence: sequence, consuming_sequences: sequence === claimSequence ? [100_000] : [], turn_id: 'analysis-test-t007', step_id: null, request_id: null,
    tool_call_id: sequence === claimSequence ? 'call:17' : null, result_id: sequence === claimSequence ? 'result:17' : null, evidence_id: reference, claim_id: sequence === claimSequence ? 'claim:17' : null,
  };
}

const lineEvidence = { ...evidenceRecord('evidence:line-17', claimSequence), id: 'evidence:line-17', relative_path: 'evidence/line-17.json' };
const unavailableEvidence = {
  ...evidenceRecord('evidence:legacy-unverified', 99_996),
  source: 'derived' as const,
  relative_path: '',
  sha256: '',
  verification_status: 'unavailable',
  unavailable_reason: 'legacy source did not record a verified artifact',
};
const evidenceIndex = { analysis_id: 'analysis-test', records: { 'evidence:line-17': lineEvidence } };

const contextPage = {
  analysis_id: 'analysis-test',
  items: [contextFrameAt(99_999), contextFrameAt(100_000)].map((frame) => ({
    id: frame.id,
    source_sequence: frame.source_sequence,
    before_revision: frame.before_revision,
    after_revision: frame.after_revision,
    changed: true,
    request_input_available: true,
    event_kind: frame.source_sequence === 99_999 ? 'tool-result' : 'model-request',
  })),
  older_cursor: null, newer_cursor: null,
  first_sequence: 99_999,
  last_sequence: contextFrame.source_sequence,
  has_older: false, encoded_bytes: 100,
};

function currentEvidencePage(verificationStatus: string | null = null) {
  const items = [
    lineEvidence,
    unavailableEvidence,
    ...Array.from({ length: 498 }, (_, index) => evidenceRecord(`evidence:current:${index}`, 99_501 + index)),
  ].filter((record) => !verificationStatus || record.verification_status === verificationStatus);
  return {
    analysis_id: 'analysis-test', items,
    older_cursor: newestEvidenceCursor, newer_cursor: null,
    first_sequence: 99_501, last_sequence: 100_000,
    has_older: true, encoded_bytes: encodedBytes(items),
  };
}

function olderEvidencePage() {
  const items = Array.from({ length: 500 }, (_, index) => evidenceRecord(`evidence:older:${index}`, 99_001 + index));
  return {
    analysis_id: 'analysis-test', items,
    older_cursor: null, newer_cursor: null,
    first_sequence: 99_001, last_sequence: 99_500,
    has_older: false, encoded_bytes: encodedBytes(items),
  };
}

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
  let olderAgentAttempts = 0;
  let olderEvidenceAttempts = 0;
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
    if (path.endsWith('/agent')) {
      if (url.searchParams.has('cursor')) {
        olderAgentAttempts += 1;
        if (olderAgentAttempts === 1) return route.fulfill({ status: 503, json: { code: 'cursor_failed', message: 'older agent cursor unavailable' } });
        return route.fulfill({ json: olderAgentPage() });
      }
      return route.fulfill({ json: agentPage() });
    }
    if (path.includes('/context')) return route.fulfill({ json: url.searchParams.has('at_sequence')
      ? contextFrameAt(Number(url.searchParams.get('at_sequence')))
      : contextPage });
    if (path.endsWith('/execution')) return route.fulfill({ json: executionSliceAt(Number(url.searchParams.get('at_sequence') ?? run.last_sequence)) });
    if (path.includes('/artifacts/')) {
      const reference = decodeURIComponent(path.split('/').at(-1) ?? '');
      const content = JSON.stringify({ reference, result: 'x'.repeat(140_000) });
      const range = route.request().headers().range;
      if (range) {
        const match = range.match(/^bytes=0-(\d+)$/);
        const end = Math.min(Number(match?.[1] ?? content.length - 1), content.length - 1);
        return route.fulfill({
          status: 206,
          body: content.slice(0, end + 1),
          headers: {
            'Content-Type': 'application/json; charset=utf-8',
            'Content-Range': `bytes 0-${end}/${content.length}`,
            'Content-Disposition': `attachment; filename="${reference.replaceAll(':', '-')}.json"`,
          },
        });
      }
      return route.fulfill({ body: content, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Content-Disposition': 'attachment; filename="evidence.json"' } });
    }
    if (path.endsWith('/evidence')) {
      const relevantRef = url.searchParams.get('relevant_ref');
      if (relevantRef) {
        const item = relevantRef === lineEvidence.reference ? lineEvidence : evidenceRecord(relevantRef, claimSequence);
        return route.fulfill({ json: { ...currentEvidencePage(), items: [item], older_cursor: null, has_older: false, first_sequence: item.producing_sequence, last_sequence: item.producing_sequence } });
      }
      if (url.searchParams.has('cursor')) {
        olderEvidenceAttempts += 1;
        if (olderEvidenceAttempts === 1) return route.fulfill({ status: 503, json: { code: 'cursor_failed', message: 'older evidence cursor unavailable' } });
        return route.fulfill({ json: olderEvidencePage() });
      }
      return route.fulfill({ json: currentEvidencePage(url.searchParams.get('verification_status')) });
    }
    return route.fulfill({ status: 404, json: { code: 'not_found', message: 'not found' } });
  });
}
