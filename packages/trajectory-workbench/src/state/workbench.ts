export type WorkbenchView = 'business' | 'agent' | 'context' | 'evidence';
export type Theme = 'dark' | 'light' | 'system';
export type AsyncStatus = 'idle' | 'loading' | 'ready' | 'failed';

export interface LoadedPage {
  firstSequence: number | null;
  lastSequence: number | null;
  hasOlder: boolean;
}

export interface WorkbenchState {
  selectedRunId: string | null;
  activeView: WorkbenchView;
  selectedNodeId: string | null;
  pages: Record<WorkbenchView, LoadedPage[]>;
  pageStatus: Record<WorkbenchView, AsyncStatus>;
  pageError: Record<WorkbenchView, string | null>;
  foldedNodeIds: string[];
  search: string;
  timelineRange: { startSequence: number; endSequence: number } | null;
  inspectorOpen: boolean;
  theme: Theme;
  prependAnchor: { nodeId: string; offset: number } | null;
}

const emptyPages = (): Record<WorkbenchView, LoadedPage[]> => ({ business: [], agent: [], context: [], evidence: [] });
const emptyStatus = (): Record<WorkbenchView, AsyncStatus> => ({ business: 'idle', agent: 'idle', context: 'idle', evidence: 'idle' });
const emptyErrors = (): Record<WorkbenchView, string | null> => ({ business: null, agent: null, context: null, evidence: null });

export const initialWorkbenchState: WorkbenchState = {
  selectedRunId: null,
  activeView: 'business',
  selectedNodeId: null,
  pages: emptyPages(),
  pageStatus: emptyStatus(),
  pageError: emptyErrors(),
  foldedNodeIds: [],
  search: '',
  timelineRange: null,
  inspectorOpen: true,
  theme: 'system',
  prependAnchor: null,
};

export type WorkbenchAction =
  | { type: 'run/selected'; runId: string | null }
  | { type: 'view/selected'; view: WorkbenchView }
  | { type: 'page/requested'; view: WorkbenchView }
  | { type: 'page/loaded'; view: WorkbenchView; page: LoadedPage }
  | { type: 'page/prepended'; view: WorkbenchView; page: LoadedPage }
  | { type: 'page/failed'; view: WorkbenchView; message: string }
  | { type: 'node/selected'; nodeId: string | null }
  | { type: 'node/foldToggled'; nodeId: string }
  | { type: 'search/changed'; search: string }
  | { type: 'timeline/focused'; range: WorkbenchState['timelineRange'] }
  | { type: 'inspector/opened' }
  | { type: 'inspector/closed' }
  | { type: 'theme/changed'; theme: Theme }
  | { type: 'prependAnchor/set'; anchor: WorkbenchState['prependAnchor'] };

export function workbenchReducer(state: WorkbenchState, action: WorkbenchAction): WorkbenchState {
  switch (action.type) {
    case 'run/selected': return { ...state, selectedRunId: action.runId, selectedNodeId: null, pages: emptyPages(), pageStatus: emptyStatus(), pageError: emptyErrors() };
    case 'view/selected': return { ...state, activeView: action.view };
    case 'page/requested': return { ...state, pageStatus: { ...state.pageStatus, [action.view]: 'loading' }, pageError: { ...state.pageError, [action.view]: null } };
    case 'page/loaded': return { ...state, pages: { ...state.pages, [action.view]: [action.page] }, pageStatus: { ...state.pageStatus, [action.view]: 'ready' } };
    case 'page/prepended': return { ...state, pages: { ...state.pages, [action.view]: [action.page, ...state.pages[action.view]] }, pageStatus: { ...state.pageStatus, [action.view]: 'ready' } };
    case 'page/failed': return { ...state, pageStatus: { ...state.pageStatus, [action.view]: 'failed' }, pageError: { ...state.pageError, [action.view]: action.message } };
    case 'node/selected': return { ...state, selectedNodeId: action.nodeId, inspectorOpen: action.nodeId !== null ? true : state.inspectorOpen };
    case 'node/foldToggled': return { ...state, foldedNodeIds: state.foldedNodeIds.includes(action.nodeId) ? state.foldedNodeIds.filter((id) => id !== action.nodeId) : [...state.foldedNodeIds, action.nodeId] };
    case 'search/changed': return { ...state, search: action.search };
    case 'timeline/focused': return { ...state, timelineRange: action.range };
    case 'inspector/opened': return { ...state, inspectorOpen: true };
    case 'inspector/closed': return { ...state, inspectorOpen: false };
    case 'theme/changed': return { ...state, theme: action.theme };
    case 'prependAnchor/set': return { ...state, prependAnchor: action.anchor };
  }
}
