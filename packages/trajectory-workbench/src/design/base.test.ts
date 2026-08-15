import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const stylesheet = readFileSync(resolve(process.cwd(), 'src/design/base.css'), 'utf8');

describe('workbench responsive layout', () => {
  it('keeps the inspector as a resizable right panel from 800px through 1199px', () => {
    expect(stylesheet).toMatch(
      /@media \(min-width: 800px\) and \(max-width: 1199px\) \{[\s\S]*?grid-template-columns: 190px minmax\(0, 1fr\) var\(--inspector-width, clamp\([\s\S]*?\.inspector \{ grid-column: 3; grid-row: 2 \/ -1;[\s\S]*?\.inspector-resize-handle \{ display: block;/,
    );
  });

  it('reserves the modal bottom sheet for viewports below 800px', () => {
    expect(stylesheet).toMatch(/@media \(max-width: 799px\) \{[\s\S]*?\.inspector-backdrop \{ position: fixed;/);
  });
});
