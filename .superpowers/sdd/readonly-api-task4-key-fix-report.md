# Read-only API Task 4 Key Hardening Report

## Scope

Hardened `CursorCodec.load_or_create` when a cursor key already exists.
Existing keys are accepted only when they are a private regular 32-byte file.

## TDD evidence

RED:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_cursor.py -q
3 failed, 6 passed
```

The prior implementation followed a symlink, attempted to read a directory,
and accepted a world-readable 32-byte key.

GREEN:

```text
uv run --project . pytest tests/trajectory/api/test_cursor.py -q
9 passed
```

## Safety controls

- Existing paths are inspected with `lstat` and must be regular files.
- The key is opened through an `O_NOFOLLOW` descriptor, then `fstat`-checked.
- `lstat` and descriptor device/inode identities must match, preventing a
  replacement between path inspection and opening from being trusted.
- Group or other permission bits, sizes other than 32 bytes, symlinks, and
  non-regular files fail closed with `ValueError`.
- New keys retain the existing exclusive-create, `0600`, write/fsync path.

## Verification

```text
uv run --project . pytest tests/trajectory/api/test_cursor.py -q
9 passed

uv run --project . ruff check src/grid_agent/trajectory/api/cursor.py tests/trajectory/api/test_cursor.py
All checks passed!

uv run --project . pyright src/grid_agent/trajectory/api/cursor.py tests/trajectory/api/test_cursor.py
0 errors, 0 warnings, 0 informations

git diff --check
passed
```

## Review follow-up: descriptor owner validation

Existing cursor keys now also require that the opened descriptor's `st_uid`
matches `os.geteuid()`. The check is made alongside the existing descriptor
regular-file, inode/device, private-mode, and size checks, so it retains the
no-follow and replacement protections.

TDD evidence:

```text
RED: uv run --project packages/grid-agent pytest \
     packages/grid-agent/tests/trajectory/api/test_cursor.py -q
     1 failed, 9 passed

GREEN: uv run --project packages/grid-agent pytest \
       packages/grid-agent/tests/trajectory/api/test_cursor.py -q
       10 passed

uv run --project packages/grid-agent ruff check \
  packages/grid-agent/src/grid_agent/trajectory/api/cursor.py \
  packages/grid-agent/tests/trajectory/api/test_cursor.py
All checks passed!

uv run --project packages/grid-agent pyright \
  packages/grid-agent/src/grid_agent/trajectory/api/cursor.py \
  packages/grid-agent/tests/trajectory/api/test_cursor.py
0 errors, 0 warnings, 0 informations

git diff --check
passed
```

The regression test mocks `fstat` with a foreign `st_uid`, allowing portable
coverage even where the test process cannot `chown` a key file.
