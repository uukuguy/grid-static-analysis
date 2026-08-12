from __future__ import annotations

import re
from collections.abc import Mapping, Sequence


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


def branch_endpoints(answer: str, arguments: Mapping[str, object]) -> bool:
    names = arguments.get("bus_names", [])
    bus_tokens = set(re.findall(r"母线\s*(\d+)|\bbus(?:es)?\b\s*(\d+)", answer, flags=re.IGNORECASE))
    bus_names = {token for match in bus_tokens for token in match if token}
    return (
        isinstance(names, Sequence)
        and not isinstance(names, (str, bytes, bytearray))
        and all(str(name) in bus_names for name in names)
    )


ORACLES = {
    "contains_all": contains_all,
    "truthful_limitation": truthful_limitation,
    "branch_endpoints": branch_endpoints,
}
