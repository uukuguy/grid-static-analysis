# Mobile Inspector Fix Report

## Scope

- At viewport widths of 720px or less, the inspector is available through an explicit `Open inspector` trigger and opens as a modal bottom sheet.
- The sheet focuses its close control on open, traps Tab/Shift+Tab, closes with Escape, close control, or backdrop, and restores focus to the trigger.
- Desktop and tablet continue to render the inspector as the existing complementary shell region. Node selection remains owned by the application state and does not open or reset the sheet.
- Mobile layout removes the static inspector grid row and prevents horizontal page overflow.

## TDD evidence

`WorkbenchShell.test.tsx` was written first and failed because the open trigger and dialog did not exist. It now passes its open/focus and focus-trap/return-focus cases.

## Verification

- `npm test -- --run src/components/layout/WorkbenchShell.test.tsx src/design/base.test.ts` — 3 passing tests
- `npm test` — 46 passing tests
- `npm run check` — passed
- `npm run build` — passed
