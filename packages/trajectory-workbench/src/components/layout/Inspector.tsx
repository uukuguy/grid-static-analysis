import type { AuditInspectorModel, AuditPanel } from '../../audit/inspector-model';
import { AuditInspector } from '../audit/AuditInspector';
import type { AsyncStateName } from '../common/AsyncState';

export function Inspector(props: {
  model: AuditInspectorModel | null;
  artifactUrl: (ref: string) => string;
  onSelectSequence?: (sequence: number) => void;
  panelStates?: Partial<Record<AuditPanel, AsyncStateName>>;
  panelDiagnostics?: Partial<Record<AuditPanel, string | null>>;
  onRetryPanel?: (panel: AuditPanel) => void;
  runStatus?: string | null;
  runDiagnostic?: string | null;
}) {
  return <AuditInspector {...props} />;
}
