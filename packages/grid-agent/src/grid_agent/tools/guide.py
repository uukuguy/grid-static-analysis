from __future__ import annotations

import re
import json
from dataclasses import dataclass
from pathlib import Path


_RESOURCE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]+$")
_ENCODED_SEPARATOR_PATTERN = re.compile(r"%(?:2f|5c)", re.IGNORECASE)


class GuideNotFound(KeyError):
    """Raised when a guide document is not published by the allowlist index."""


@dataclass(frozen=True)
class GuideDocument:
    resource_id: str
    title: str
    text: str
    path: Path


class GuideIndex:
    def __init__(self, skill_root: Path, resources: dict[str, Path]) -> None:
        self._skill_root = skill_root
        self._resources = dict(resources)

    @classmethod
    def load(cls, skill_root: Path) -> GuideIndex:
        root = Path(skill_root).resolve()
        resources: dict[str, Path] = {}

        overview = root / "SKILL.md"
        if overview.is_file():
            resources["overview"] = overview.resolve()

        references = root / "references"
        if references.is_dir():
            for path in sorted(references.iterdir(), key=lambda item: item.name):
                if path.is_file() and path.suffix == ".md":
                    resources[path.stem] = path.resolve()

        return cls(root, resources)

    def open(self, resource_id: str) -> GuideDocument:
        if (
            not _RESOURCE_ID_PATTERN.fullmatch(resource_id)
            or _ENCODED_SEPARATOR_PATTERN.search(resource_id)
        ):
            raise GuideNotFound(resource_id)

        path = self._resources.get(resource_id)
        if path is None or not path.is_relative_to(self._skill_root):
            raise GuideNotFound(resource_id)

        text = path.read_text(encoding="utf-8")
        return GuideDocument(
            resource_id=resource_id,
            title=_extract_title(text, fallback=resource_id),
            text=text,
            path=path,
        )

    def materialize(self, path: Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "protocol": "grid-guide-index",
            "version": "1.0",
            "root": str(self._skill_root),
            "resources": {
                resource_id: str(resource_path)
                for resource_id, resource_path in sorted(self._resources.items())
            },
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        return target


def _extract_title(text: str, *, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback
