import type { BusinessProblem } from '../../api/types';

interface OverviewTimelineProps {
  problems: BusinessProblem[];
  selectedTurnId: string | null;
  onFocusRange: (range: { startSequence: number; endSequence: number }) => void;
  onSelectTurn: (turnId: string) => void;
}

export function OverviewTimeline({ problems, selectedTurnId, onFocusRange, onSelectTurn }: OverviewTimelineProps) {
  const selected = problems.find((problem) => problem.turn_id === selectedTurnId);
  const activate = (problem: BusinessProblem) => {
    onSelectTurn(problem.turn_id);
    onFocusRange({ startSequence: Math.min(...problem.source_sequences), endSequence: Math.max(...problem.source_sequences) });
  };
  return <div className="overview-timeline">
    <svg viewBox={`0 0 ${Math.max(problems.length, 1) * 120} 54`} role="img" aria-label="Run turn overview">
      {problems.map((problem, index) => {
        const x = index * 120 + 4;
        const active = problem.turn_id === selectedTurnId;
        return <g key={problem.id}>
          <rect x={x} y="8" width="108" height="34" rx="6" role="button" tabIndex={0}
            aria-label={`${problem.title} overview segment`}
            className={active ? 'timeline-turn active' : 'timeline-turn'} onClick={() => activate(problem)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                activate(problem);
              }
            }} />
          <text x={x + 10} y="29">{problem.title.split('·')[0].trim()}</text>
        </g>;
      })}
    </svg>
    <p>{selected ? `${selected.title} · sequences ${selected.source_sequences.join('–')}` : 'Select a turn to focus its durable sequence range.'}</p>
  </div>;
}
