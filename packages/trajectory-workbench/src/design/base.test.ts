import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const stylesheet = readFileSync(resolve(process.cwd(), 'src/design/base.css'), 'utf8');

describe('workbench responsive layout', () => {
  it('ends the run rail before the bottom inspector at medium widths', () => {
    expect(stylesheet).toMatch(
      /@media \(max-width: 1100px\) \{[\s\S]*?\.run-rail \{ grid-row: 2 \/ 4; \}/,
    );
  });
});
