"""Dockerfile / Containerfile を読み、実行に必要な事実だけを取り出す。"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

from compose_to_docker.model import DockerfileFacts


def parse_dockerignore(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def dockerignore_excludes(relative: str, lines: list[str]) -> bool:
    rel = relative.replace("\\", "/").lstrip("./")
    excluded = False
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negate = line.startswith("!")
        if negate:
            line = line[1:].strip()
        pattern = line.rstrip("/")
        if not pattern:
            continue
        matched = rel == pattern or rel.startswith(pattern + "/")
        if not matched:
            matched = _fnmatch_path(rel, pattern) or _fnmatch_path(rel, pattern + "/*")
        if matched:
            excluded = not negate
    return excluded


def _fnmatch_path(rel: str, pattern: str) -> bool:
    import fnmatch

    return fnmatch.fnmatch(rel, pattern)


def inspect_dockerfile(
    dockerfile: Path,
    context: Path,
    build_args: dict[str, str],
) -> DockerfileFacts:
    facts = DockerfileFacts(path=str(dockerfile))
    if not dockerfile.is_file():
        facts.notes.append(f"Dockerfile がありません: {dockerfile}")
        return facts
    text = dockerfile.read_text(encoding="utf-8", errors="replace")
    lines = _join_continuations(text)
    args = dict(build_args)
    ignore_lines = parse_dockerignore(context / ".dockerignore")
    seen_from = False
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head, _, rest = line.partition(" ")
        word = head.upper()
        if word == "ARG":
            key, default = _parse_arg(rest)
            if key and key not in args:
                args[key] = default
            if key and not seen_from:
                facts.arg_defaults[key] = args.get(key, default)
            continue
        if word == "FROM":
            seen_from = True
            image, stage = _parse_from(_expand(rest, args))
            if image:
                facts.from_images.append(image)
            if stage:
                facts.stages.append(stage)
            continue
        if word == "EXPOSE":
            facts.exposes.extend(shlex.split(_expand(rest, args)))
            continue
        if word == "WORKDIR":
            facts.workdir = _expand(rest.strip(), args)
            continue
        if word == "USER":
            facts.user = _expand(rest.strip(), args)
            continue
        if word == "ENTRYPOINT":
            facts.entrypoint = _expand(rest.strip(), args)
            continue
        if word == "CMD":
            facts.cmd = _expand(rest.strip(), args)
            continue
        if word == "HEALTHCHECK":
            facts.healthcheck = _expand(line, args)
            continue
        if word in {"COPY", "ADD"}:
            _note_copy(word, rest, args, context, ignore_lines, facts)
    facts.arg_defaults.update({key: value for key, value in args.items() if key not in facts.arg_defaults})
    return facts


def _join_continuations(text: str) -> list[str]:
    logical: list[str] = []
    buf = ""
    for line in text.splitlines():
        if line.rstrip().endswith("\\"):
            buf += line.rstrip()[:-1] + " "
            continue
        buf += line
        logical.append(buf)
        buf = ""
    if buf:
        logical.append(buf)
    return logical


def _parse_arg(rest: str) -> tuple[str, str]:
    body = rest.strip()
    if "=" not in body:
        return body, ""
    key, value = body.split("=", 1)
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return key.strip(), value


def _parse_from(rest: str) -> tuple[str, str]:
    tokens = shlex.split(rest)
    image = ""
    stage = ""
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("--"):
            i += 1
            continue
        if image == "":
            image = token
            i += 1
            continue
        if token.upper() == "AS" and i + 1 < len(tokens):
            stage = tokens[i + 1]
            break
        i += 1
    return image, stage


def _expand(text: str, args: dict[str, str]) -> str:
    def braced(match: re.Match[str]) -> str:
        return args.get(match.group(1), match.group(0))

    def bare(match: re.Match[str]) -> str:
        return args.get(match.group(1), match.group(0))

    text = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", braced, text)
    text = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", bare, text)
    return text


def _note_copy(
    word: str,
    rest: str,
    args: dict[str, str],
    context: Path,
    ignore_lines: list[str],
    facts: DockerfileFacts,
) -> None:
    expanded = _expand(rest.strip(), args)
    from_stage = False
    sources: list[str] = []
    if expanded.startswith("["):
        try:
            items = json.loads(expanded)
        except json.JSONDecodeError:
            facts.notes.append(f"{word} の JSON を読めませんでした: {expanded}")
            return
        if isinstance(items, list) and items:
            sources = [str(item) for item in items[:-1]]
    else:
        try:
            tokens = shlex.split(expanded)
        except ValueError:
            facts.notes.append(f"{word} の行を分解できませんでした: {expanded}")
            return
        kept: list[str] = []
        for token in tokens:
            if token.startswith("--"):
                if token.startswith("--from"):
                    from_stage = True
                continue
            kept.append(token)
        if kept:
            sources = kept[:-1]
    if from_stage or word == "ADD" and any(src.startswith(("http://", "https://")) for src in sources):
        return
    for src in sources:
        if src.startswith(("http://", "https://")):
            continue
        facts.copy_sources.append(src)
        if any(ch in src for ch in "*?["):
            matches = list(context.glob(src))
            if not matches:
                facts.missing_sources.append(src)
            continue
        path = Path(src)
        host = path if path.is_absolute() else context / path
        if not host.exists():
            facts.missing_sources.append(src)
        if ignore_lines and dockerignore_excludes(src, ignore_lines):
            facts.ignored_sources.append(src)
