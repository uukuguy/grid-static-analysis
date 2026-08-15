import { describe, expect, it } from 'vitest';
import { pageRequestKey, prependOperationalPage } from './operational-page';

describe('operational page state', () => {
  it('retains loaded rows while merging an older page by stable id', () => {
    expect(prependOperationalPage(
      [{ id: 'tool:1' }],
      [{ id: 'tool:1' }, { id: 'tool:2' }],
    )).toEqual([{ id: 'tool:1' }, { id: 'tool:2' }]);
  });

  it('binds request identity to run, view, opaque cursor, and canonical filters', () => {
    const first = pageRequestKey('analysis-a', 'context', {
      cursor: 'opaque/cursor',
      filters: { changed: true, from_sequence: 12 },
    });
    const reordered = pageRequestKey('analysis-a', 'context', {
      cursor: 'opaque/cursor',
      filters: { from_sequence: 12, changed: true },
    });

    expect(reordered).toBe(first);
    expect(pageRequestKey('analysis-b', 'context', {
      cursor: 'opaque/cursor', filters: { changed: true, from_sequence: 12 },
    })).not.toBe(first);
    expect(pageRequestKey('analysis-a', 'context', {
      cursor: 'new-cursor', filters: { changed: true, from_sequence: 12 },
    })).not.toBe(first);
    expect(pageRequestKey('analysis-a', 'evidence', {
      cursor: 'opaque/cursor', filters: { changed: true, from_sequence: 12 },
    })).not.toBe(first);
  });

  it('treats omitted and null filters as the same request identity', () => {
    expect(pageRequestKey('analysis-a', 'evidence', {
      filters: { kind: null },
    })).toBe(pageRequestKey('analysis-a', 'evidence', {
      filters: {},
    }));
  });
});
