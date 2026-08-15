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

  it('keeps the selected node when search results or a folded problem hide it', () => {
    const selected: WorkbenchState = {
      ...initialWorkbenchState,
      selectedNodeId: 'business:q7:claim',
    };

    const searched = workbenchReducer(selected, { type: 'search/changed', search: 'contingency' });
    const folded = workbenchReducer(searched, { type: 'node/foldToggled', nodeId: 'q7' });

    expect(folded.selectedNodeId).toBe('business:q7:claim');
    expect(folded.search).toBe('contingency');
    expect(folded.foldedNodeIds).toContain('q7');
  });

  it('focuses a problem group without replacing the selected node', () => {
    const selected: WorkbenchState = {
      ...initialWorkbenchState,
      activeView: 'agent',
      selectedNodeId: 'business:q7:claim',
    };

    const next = workbenchReducer(selected, {
      type: 'problem/focused',
      problemId: 'business:q7',
    });

    expect(next.activeView).toBe('business');
    expect(next.focusedProblemId).toBe('business:q7');
    expect(next.selectedNodeId).toBe('business:q7:claim');
  });

  it('resets only the filtered operational view page metadata', () => {
    const loaded: WorkbenchState = {
      ...initialWorkbenchState,
      pages: {
        ...initialWorkbenchState.pages,
        agent: [tailPage],
        context: [olderPage],
      },
      pageStatus: { ...initialWorkbenchState.pageStatus, agent: 'ready', context: 'ready' },
    };

    const next = workbenchReducer(loaded, {
      type: 'page/filtersChanged', view: 'agent', filters: { kind: 'tool', q: 'voltage' },
    });

    expect(next.pageFilters.agent).toEqual({ kind: 'tool', q: 'voltage' });
    expect(next.pages.agent).toEqual([]);
    expect(next.pageStatus.agent).toBe('idle');
    expect(next.pages.context).toEqual([olderPage]);
    expect(next.pageStatus.context).toBe('ready');
  });
});
