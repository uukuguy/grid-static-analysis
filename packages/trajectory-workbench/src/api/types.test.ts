import { describe, expectTypeOf, it } from 'vitest';
import type { ContextFrame, ContextState } from './types';

describe('ContextFrame API contract', () => {
  it('models recursive JSON state and the legacy missing-request invariant', () => {
    const native: ContextFrame = {
      id: 'context:analysis-test:12',
      source: 'derived',
      source_sequences: [12],
      rule_id: 'context-frame/v1',
      status: 'completed',
      unavailable_reason: null,
      source_sequence: 12,
      before_revision: 3,
      after_revision: 4,
      before_state_hash: 'sha256:before',
      after_state_hash: 'sha256:after',
      before_state: { domain_state: { calculations: ['result:1'] } },
      delta: { domain_state: { calculations: { added: ['result:2'] } } },
      after_state: { domain_state: { calculations: ['result:1', 'result:2'] } },
      request_artifact_ref: 'artifact:request:13',
      max_sequence: 13,
    };
    const legacy: ContextFrame = {
      ...native,
      request_artifact_ref: null,
      unavailable_reason: 'legacy source did not capture model request input',
    };

    expectTypeOf(native.before_state).toEqualTypeOf<ContextState>();
    expectTypeOf(legacy.unavailable_reason).toEqualTypeOf<string>();
  });
});
