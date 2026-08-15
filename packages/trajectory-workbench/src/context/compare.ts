import type { JsonValue } from '../api/types';

export interface ContextComparison {
  added: string[];
  removed: string[];
  changed: string[];
}

function isRecord(value: JsonValue): value is Record<string, JsonValue> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function childPath(prefix: string, key: string | number, array = false): string {
  if (array) return `${prefix}[${key}]`;
  return prefix ? `${prefix}.${key}` : String(key);
}

/** Compare exactly two recorded JSON states without materializing synthetic state. */
export function compareContextStates(
  left: JsonValue,
  right: JsonValue,
  prefix = '',
): ContextComparison {
  const comparison: ContextComparison = { added: [], removed: [], changed: [] };

  const visit = (before: JsonValue, after: JsonValue, path: string) => {
    if (Object.is(before, after)) return;
    if (Array.isArray(before) && Array.isArray(after)) {
      const shared = Math.min(before.length, after.length);
      for (let index = 0; index < shared; index += 1) {
        visit(before[index], after[index], childPath(path, index, true));
      }
      for (let index = shared; index < after.length; index += 1) {
        comparison.added.push(childPath(path, index, true));
      }
      for (let index = shared; index < before.length; index += 1) {
        comparison.removed.push(childPath(path, index, true));
      }
      return;
    }
    if (isRecord(before) && isRecord(after)) {
      const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].sort();
      for (const key of keys) {
        const pathForKey = childPath(path, key);
        if (!Object.hasOwn(before, key)) comparison.added.push(pathForKey);
        else if (!Object.hasOwn(after, key)) comparison.removed.push(pathForKey);
        else visit(before[key], after[key], pathForKey);
      }
      return;
    }
    comparison.changed.push(path || '$');
  };

  visit(left, right, prefix);
  return comparison;
}
