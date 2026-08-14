import { describe, expect, it } from 'vitest';
import { initialWorkbenchState, workbenchReducer, type WorkbenchState } from './workbench';

const tailPage = { firstSequence: 501, lastSequence: 750, hasOlder: true };
const olderPage = { firstSequence: 1, lastSequence: 500, hasOlder: false };

describe('workbenchReducer', () => {
  it('starts in business view and retains selection across page prepend', () => {
    const selected: WorkbenchState = {
      ...initialWorkbenchState,
      selectedRunId: 'analysis-test',
      selectedNodeId: 'business:42',
      pages: { ...initialWorkbenchState.pages, business: [tailPage] },
    };

    const next = workbenchReducer(selected, {
      type: 'page/prepended', view: 'business', page: olderPage,
    });

    expect(next.activeView).toBe('business');
    expect(next.selectedNodeId).toBe('business:42');
    expect(next.pages.business.map((page) => page.firstSequence)).toEqual([1, 501]);
  });
});
