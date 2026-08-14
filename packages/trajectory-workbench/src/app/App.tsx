import { useEffect, useReducer } from 'react';
import { TrajectoryApiClient } from '../api/client';
import { initialWorkbenchState, workbenchReducer } from '../state/workbench';

const api = new TrajectoryApiClient();

/** Data ownership begins here; the Task 2 shell supplies the visual regions. */
export function App() {
  const [state, dispatch] = useReducer(workbenchReducer, initialWorkbenchState);

  useEffect(() => {
    const controller = new AbortController();
    void api.listRuns(controller.signal).then(({ items }) => {
      dispatch({ type: 'run/selected', runId: items[0]?.analysis_id ?? null });
    }).catch(() => undefined);
    return () => controller.abort();
  }, []);

  return <main className="workbench-bootstrap" aria-label="Trajectory workbench" data-view={state.activeView} />;
}
