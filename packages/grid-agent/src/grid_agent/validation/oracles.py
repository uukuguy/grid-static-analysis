from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

_BUS_MARKER = re.compile(r"母线|\bbus(?:es)?\b", flags=re.IGNORECASE)
_ENDPOINT_SEPARATOR = re.compile(
    r"\s*(?:与|和|及|到|至|、|/|,|，|\band\b|\bto\b)\s*",
    flags=re.IGNORECASE,
)
_NUMBER = re.compile(r"\s*(\d+)")


def contains_all(answer: str, arguments: Mapping[str, object]) -> bool:
    values = arguments.get("values", [])
    return (
        isinstance(values, Sequence)
        and not isinstance(values, (str, bytes, bytearray))
        and all(str(value).casefold() in answer.casefold() for value in values)
    )


def truthful_limitation(answer: str, arguments: Mapping[str, object]) -> bool:
    lowered = answer.casefold()
    return any(term in lowered for term in ("不存在", "未找到", "不支持", "limitation", "not found"))


def _bus_endpoint_phrases(answer: str) -> tuple[set[str], ...]:
    phrases = []
    for marker in _BUS_MARKER.finditer(answer):
        position = marker.end()
        first_number = _NUMBER.match(answer, position)
        if first_number is None:
            continue

        phrase = {first_number.group(1)}
        position = first_number.end()
        while True:
            separator = _ENDPOINT_SEPARATOR.match(answer, position)
            if separator is None:
                break

            next_position = separator.end()
            repeated_marker = _BUS_MARKER.match(answer, next_position)
            if repeated_marker is not None:
                next_position = repeated_marker.end()

            next_number = _NUMBER.match(answer, next_position)
            if next_number is None:
                break

            phrase.add(next_number.group(1))
            position = next_number.end()

        phrases.append(phrase)

    return tuple(phrases)


def branch_endpoints(answer: str, arguments: Mapping[str, object]) -> bool:
    names = arguments.get("bus_names", [])
    if not isinstance(names, Sequence) or isinstance(names, (str, bytes, bytearray)):
        return False
    expected_names = {str(name) for name in names}
    return bool(expected_names) and any(
        expected_names.issubset(phrase) for phrase in _bus_endpoint_phrases(answer)
    )


ORACLES = {
    "contains_all": contains_all,
    "truthful_limitation": truthful_limitation,
    "branch_endpoints": branch_endpoints,
}
