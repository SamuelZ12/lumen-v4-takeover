"""Default human rendering: every field of the JSON result, indented, nothing hidden."""

from typing import Any


def _scalar(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _lines(value: Any, indent: int) -> list[str]:
    pad = "  " * indent
    if isinstance(value, dict):
        out = []
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                out.append(f"{pad}{key}:")
                out.extend(_lines(item, indent + 1))
            else:
                out.append(f"{pad}{key}: {_scalar(item) if not isinstance(item, (dict, list)) else '(none)'}")
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict) and item:
                nested = _lines(item, indent + 1)
                out.append(f"{pad}- {nested[0].strip()}")
                out.extend(nested[1:])
            else:
                out.append(f"{pad}- {_scalar(item)}")
        return out
    return [f"{pad}{_scalar(value)}"]


def render_default(result: Any) -> str:
    return "\n".join(_lines(result, 0))
