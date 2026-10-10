"""Compose 仕様の補間。${VAR}、${VAR:-default}、$$ を扱う。"""

from __future__ import annotations

import re
from collections.abc import Mapping

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class InterpolationError(ValueError):
    pass


def interpolate(text: str, env: Mapping[str, str], *, origin: str = "value") -> str:
    return _interp(text, env, origin, 0)


def _interp(text: str, env: Mapping[str, str], origin: str, depth: int) -> str:
    if depth > 30:
        raise InterpolationError(f"変数の展開が深すぎます: {origin}")
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "$":
            out.append(text[i])
            i += 1
            continue
        if i + 1 < n and text[i + 1] == "$":
            out.append("$")
            i += 2
            continue
        if i + 1 < n and text[i + 1] == "{":
            expr, nxt = _read_braced(text, i + 2, origin)
            out.append(_expand_expr(expr, env, origin, depth))
            i = nxt
            continue
        matched = _NAME.match(text, i + 1)
        if not matched:
            out.append("$")
            i += 1
            continue
        name = matched.group(0)
        out.append(env.get(name, ""))
        i = matched.end()
    return "".join(out)


def _read_braced(text: str, start: int, origin: str) -> tuple[str, int]:
    depth = 1
    buf: list[str] = []
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                return "".join(buf), i + 1
            buf.append(ch)
            i += 1
            continue
        buf.append(ch)
        i += 1
    raise InterpolationError(f"変数の閉じ括弧がありません: {origin}")


def _expand_expr(expr: str, env: Mapping[str, str], origin: str, depth: int) -> str:
    matched = _NAME.match(expr)
    if not matched:
        raise InterpolationError(f"変数名が不正です: ${{{expr}}} ({origin})")
    name = matched.group(0)
    rest = expr[matched.end() :]
    present = name in env
    value = env.get(name, "")
    if rest == "":
        return value if present else ""
    if rest.startswith(":-"):
        if (not present) or value == "":
            return _interp(rest[2:], env, origin, depth + 1)
        return value
    if rest.startswith(":+"):
        if present and value != "":
            return _interp(rest[2:], env, origin, depth + 1)
        return ""
    if rest.startswith(":?"):
        if (not present) or value == "":
            message = _interp(rest[2:], env, origin, depth + 1) or f"{name} が空です"
            raise InterpolationError(message)
        return value
    if rest.startswith("?"):
        if not present:
            message = _interp(rest[1:], env, origin, depth + 1) or f"{name} が未設定です"
            raise InterpolationError(message)
        return value
    if rest.startswith("-"):
        if not present:
            return _interp(rest[1:], env, origin, depth + 1)
        return value
    if rest.startswith("+"):
        if present:
            return _interp(rest[1:], env, origin, depth + 1)
        return ""
    raise InterpolationError(f"変数の書き方が不正です: ${{{expr}}} ({origin})")


def interpolate_obj(value, env: Mapping[str, str], origin: str = "compose"):
    if isinstance(value, str):
        return interpolate(value, env, origin=origin)
    if isinstance(value, list):
        return [interpolate_obj(item, env, origin) for item in value]
    if isinstance(value, dict):
        return {key: interpolate_obj(item, env, f"{origin}.{key}") for key, item in value.items()}
    return value
