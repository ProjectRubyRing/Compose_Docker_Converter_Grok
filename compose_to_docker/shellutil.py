"""Bash 向けのクォートと、生成スクリプトの静的検査。"""

from __future__ import annotations


def shell_quote(value: str) -> str:
    """単一引用符で囲む。値の中の単一引用符も安全に通す。"""
    return "'" + value.replace("'", "'\"'\"'") + "'"


def bash_sanity(script: str) -> list[str]:
    """実行前に分かる崩れを返す。空なら問題なし。"""
    errors: list[str] = []
    if "\r" in script:
        errors.append("改行が CRLF です。バックスラッシュの行継続が壊れます。LF にしてください。")
    if not script.startswith("#!/bin/bash\n"):
        errors.append("先頭が #!/bin/bash ではありません。")

    # code: none / single / double。$(...) の入れ子は深さを数える。
    state = "none"
    depth = 0
    escaped = False
    for lineno, raw in enumerate(script.split("\n"), start=1):
        if raw.rstrip() != raw and raw.rstrip().endswith("\\"):
            errors.append(f"{lineno} 行目: 行継続の \\ の後ろに空白があります。")
        i = 0
        while i < len(raw):
            ch = raw[i]
            nxt = raw[i + 1] if i + 1 < len(raw) else ""
            if state == "single":
                if ch == "'":
                    state = "none"
                i += 1
                continue
            if state == "double":
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    state = "none"
                elif ch == "$" and nxt == "(":
                    depth += 1
                    i += 2
                    continue
                i += 1
                continue
            if ch == "'":
                state = "single"
            elif ch == '"':
                state = "double"
            elif ch == "$" and nxt == "(":
                depth += 1
                i += 2
                continue
            elif ch == ")" and depth:
                depth -= 1
            elif ch == "#":
                break
            i += 1
        if state != "none" and depth == 0:
            errors.append(f"{lineno} 行目: 引用符が閉じていません。")
            state = "none"
            escaped = False

    for lineno, line in enumerate(script.split("\n"), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "docker compose" in stripped or "docker-compose" in stripped:
            errors.append(f"{lineno} 行目: Compose コマンドを呼んでいます。")
    return errors
