import type { KeyboardEvent } from 'react';
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
  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>, problem: BusinessProblem) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      activate(problem);
    }
  };
  return <div className="overview-timeline">
    <div className="timeline-visual">
    <svg viewBox={`0 0 ${Math.max(problems.length, 1) * 120} 54`} aria-hidden="true" focusable="false">
      {problems.map((problem, index) => {
        const x = index * 120 + 4;
        const active = problem.turn_id === selectedTurnId;
        return <g key={problem.id}>
          <rect x={x} y="8" width="108" height="34" rx="6"
            className={active ? 'timeline-turn active' : 'timeline-turn'} />
          <text x={x + 10} y="29">{problem.title.split('·')[0].trim()}</text>
        </g>;
      })}
    </svg>
    <div className="timeline-controls" style={{ gridTemplateColumns: `repeat(${Math.max(problems.length, 1)}, minmax(0, 1fr))` }}>
      {problems.map((problem) => {
        const active = problem.turn_id === selectedTurnId;
        return <button key={problem.id} type="button" className="timeline-control"
          aria-label={`${problem.title} overview segment`} aria-pressed={active}
          onClick={() => activate(problem)} onKeyDown={(event) => handleKeyDown(event, problem)} />;
      })}
    </div>
    </div>
    <p>{selected ? `${selected.title} · sequences ${selected.source_sequences.join('–')}` : 'Select a turn to focus its durable sequence range.'}</p>
  </div>;
}
