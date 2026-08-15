import { describe, expect, it } from 'vitest';
import { compareContextStates } from './compare';

describe('compareContextStates', () => {
  it('reports structural keys from two authoritative frame states', () => {
    expect(compareContextStates(
      { limits: { x: 1 } },
      { limits: { x: 2 }, mode: 'n1' },
    )).toEqual({ added: ['mode'], removed: [], changed: ['limits.x'] });
  });

  it('compares arrays by recorded index without inventing missing values', () => {
    expect(compareContextStates(
      { buses: [{ vm: 1 }, { vm: 0.99 }], stale: true },
      { buses: [{ vm: 0.98 }, { vm: 0.99 }, { vm: 1.01 }] },
    )).toEqual({
      added: ['buses[2]'],
      removed: ['stale'],
      changed: ['buses[0].vm'],
    });
  });
});
