"""コマンドライン入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from compose_to_docker.plan import build_plan, render_script
from compose_to_docker.render_md import commands_markdown, guide_markdown
from compose_to_docker.render_xlsx import write_workbook
from compose_to_docker.shellutil import bash_sanity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="compose_to_docker",
        description="Compose ファイルを、Docker Engine のコマンドと解説へ変換します。",
    )
    parser.add_argument("compose", type=Path, help="compose.yml / compose.yaml / docker-compose.yml")
    parser.add_argument("-o", "--output", type=Path, help="出力ディレクトリ。既定は output/<プロジェクト名>")
    parser.add_argument("--profile", action="append", default=[], help="含める Compose プロファイル。繰り返せます。")
    parser.add_argument("--env-file", action="append", default=[], type=Path, help="補間に使う env ファイル。繰り返せます。")
    parser.add_argument("--use-shell-env", action="store_true", help="今のシェルの環境変数でも ${VAR} を埋めます。")
    parser.add_argument("--selinux", choices=["z", "Z", "none"], default="z", help="バインドマウントの SELinux ラベル。RHEL 9.8 の既定は z。")
    args = parser.parse_args(argv)
    plan = build_plan(
        args.compose,
        profiles=set(args.profile),
        selinux="" if args.selinux == "none" else args.selinux,
        use_shell_env=args.use_shell_env,
        env_files=args.env_file,
    )
    script = render_script(plan)
    errors = bash_sanity(script)
    if errors:
        print("生成したスクリプトが検査を通りません。", file=sys.stderr)
        for error in errors:
            print(error, file=sys.stderr)
        return 2
    output = args.output or Path("output") / plan.project_name
    output.mkdir(parents=True, exist_ok=True)
    files = {
        output / "docker-commands.txt": script,
        output / "docker-commands.md": commands_markdown(plan, script),
        output / "command-guide.md": guide_markdown(plan),
    }
    for path, text in files.items():
        path.write_text(text, encoding="utf-8", newline="\n")
    write_workbook(plan, output / "command-guide.xlsx")
    print(f"プロジェクト: {plan.project_name}")
    print(f"サービス: {len(plan.services)}")
    print(f"出力: {output}")
    for path in [*files, output / "command-guide.xlsx"]:
        print(f"  {path}")
    for warning in plan.warnings:
        print(f"注意: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
