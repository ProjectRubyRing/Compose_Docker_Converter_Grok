"""コマンド集と、詳しい解説の Markdown を作る。"""

from __future__ import annotations

from compose_to_docker.model import Plan
from compose_to_docker.plan import render_script


def commands_markdown(plan: Plan, script: str | None = None) -> str:
    script = script if script is not None else render_script(plan)
    lines = [
        f"# {plan.project_name} を Docker コマンドだけで起動する",
        "",
        plan.overview,
        "",
        "## 実行の仕方",
        "",
        "対象は RHEL 9.8 で、Docker Engine が入っているマシンです。",
        "このファイルのコマンドは、下のコードブロックと同じ内容が `docker-commands.txt` に入っています。",
        "改行は LF です。Windows のメモ帳で保存し直すと CRLF になり、行末の `\\` が壊れます。",
        "",
        "```bash",
        "cd /path/to/project",
        "bash docker-commands.txt",
        "```",
        "",
        "別のディレクトリから実行するときは、プロジェクトの場所を指定します。",
        "",
        "```bash",
        "PROJECT_ROOT=/path/to/project bash docker-commands.txt",
        "```",
        "",
        "## 起動コマンド",
        "",
        "```bash",
        script.rstrip(),
        "```",
        "",
        "## 各段階",
        "",
    ]
    for number, step in enumerate(plan.steps, start=1):
        lines.extend(
            [
                f"### {number}. {step.title}",
                "",
                step.summary,
                "",
                f"実行の仕方: {step.how_to}",
                "",
                f"成功すると: {step.success}",
                "",
                f"失敗すると: {step.failure}",
                "",
                "```bash",
                step.script.rstrip(),
                "```",
                "",
            ]
        )
    lines.extend(["## 停止", "", "コンテナとネットワークを消し、ボリュームとイメージは残します。", "", "```bash", plan.down_script.rstrip(), "```", ""])
    return "\n".join(lines)


def guide_markdown(plan: Plan) -> str:
    lines = [
        f"# {plan.project_name} の Docker コマンド解説",
        "",
        "この文書は、Compose がやっていることを Docker Engine のコマンドへ戻し、",
        "その一行が何をしているか、なぜその仕組みが必要になったか、どんな絵で考えればよいかを説明します。",
        "2026年10月時点の Docker Engine 29 系と、2026年5月19日に一般提供が始まった RHEL 9.8 を前提にしています。",
        "",
        "## この文書の読み方",
        "",
        "最初に全体のたとえを読み、次に RHEL での実行手順、そのあと実行順を上から読みます。",
        "旗（フラグ）の意味は、実行順のあとにまとめています。",
        "歴史が長くなっている用語は『動作原理と歴史』にまとめてあり、各コマンドからはそこへ戻れるようにしてあります。",
        "",
        "## 全体像",
        "",
        plan.overview,
        "",
        "## 文化祭の模擬店にたとえると",
        "",
        plan.story,
        "",
        "## RHEL 9.8 で実行する手順",
        "",
    ]
    for title, body in procedure_blocks(plan):
        lines.extend([f"### {title}", "", body, ""])
    lines.extend(["## 実行順", ""])
    for number, step in enumerate(plan.steps, start=1):
        lines.extend(
            [
                f"### {number}. {step.title}",
                "",
                step.summary,
                "",
                f"**どう実行するか。** {step.how_to}",
                "",
                f"**成功すると見えるもの。** {step.success}",
                "",
                f"**失敗すると見えるもの。** {step.failure}",
                "",
                f"**動作原理。** {step.principle}",
                "",
                f"**頭の中の絵。** {step.analogy}",
                "",
                f"**歴史と背景。** {step.history}",
                "",
                f"**なぜ必要になったか。** {step.why}",
                "",
                "```bash",
                step.script.rstrip(),
                "```",
                "",
            ]
        )
        if step.flags:
            lines.append("| フラグ | 値 | 意味 |")
            lines.append("| --- | --- | --- |")
            for flag in step.flags:
                value = flag.value.replace("|", "\\|") or "（なし）"
                meaning = flag.meaning.replace("|", "\\|").replace("\n", " ")
                lines.append(f"| `{flag.flag}` | {value} | {meaning} |")
            lines.append("")
    lines.extend(["## 動作原理と歴史", ""])
    for concept in plan.concepts:
        lines.extend(
            [
                f"### {concept.title}",
                "",
                f"**小学生向けのたとえ。** {concept.analogy}",
                "",
                f"**動作原理。** {concept.principle}",
                "",
                f"**頭の中の絵。** {concept.picture}",
                "",
                f"**歴史と背景。** {concept.history}",
                "",
                f"**必要になった経緯。** {concept.why}",
                "",
            ]
        )
    lines.extend(["## 環境変数", "", "| サービス | 変数 | 値 | 意味 |", "| --- | --- | --- | --- |"])
    for row in plan.env_rows:
        value = row.value.replace("|", "\\|").replace("\n", " ")
        meaning = row.meaning.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {row.service} | `{row.key}` | `{value}` | {meaning} |")
    lines.extend(["", "## ビルドコンテキストで確認したこと", ""])
    for row in plan.build_rows:
        lines.extend([f"### {row.target}", "", f"場所: `{row.path}`", "", row.fact, ""])
    lines.extend(["## Compose の項目と Docker のフラグ", "", "| Compose | Docker | 意味 |", "| --- | --- | --- |"])
    for row in plan.mapping_rows:
        lines.append(
            f"| {row.compose.replace('|', '\\|')} | {row.docker.replace('|', '\\|')} | {row.meaning.replace('|', '\\|')} |"
        )
    lines.extend(
        [
            "",
            "## 停止",
            "",
            "お店を閉めて看板を外しても、冷蔵庫のロッカーは残します。",
            "次のコマンドはコンテナとネットワークだけを消します。",
            "",
            "```bash",
            plan.down_script.rstrip(),
            "```",
            "",
            "## うまくいかないとき",
            "",
            "- `permission denied` でバインドしたファイルを読めないときは、SELinux です。`getenforce` が Enforcing なら、マウントの `z` が付いているか、`ausearch -m avc -ts recent` で拒否を見ます。",
            "- イメージの取得が名前解決や接続で失敗するときは、そのマシンからレジストリへ 443 番で届くかを見ます。社内プロキシがあるときは `HTTPS_PROXY` を設定して、同じ `docker pull` だけを再実行します。",
            "- `bind source path does not exist` は、PROJECT_ROOT の場所が違うか、材料ファイルがまだ置かれていません。",
            "- 公開ポートが使用中なら、`ss -lptn` でその番号を使っているプロセスを見ます。",
            "- `unhealthy` のときは、そのコンテナの `docker logs --tail 100 名前` を見ます。起動直後の `starting` は失敗ではありません。猶予時間のあいだは正常です。",
            "- 行が途中で別の命令として動くときは、`\\` の後ろに空白か CR が入っています。`sed -i 's/\\r$//' docker-commands.txt` で CR を消せます。",
            "",
        ]
    )
    return "\n".join(lines)


def procedure_blocks(plan: Plan) -> list[tuple[str, str]]:
    missing = [row.fact for row in plan.build_rows if "未配置" in row.fact]
    missing_text = "\n".join(missing) if missing else "変換時点で、ビルドの COPY が指す未配置ファイルは検出されませんでした。"
    return [
        (
            "1. マシンを確認する",
            "RHEL 9.8 は 2026年5月19日に一般提供が始まり、カーネルは 5.14.0-687.5.1.el9_8 です。"
            "確認コマンドは `cat /etc/redhat-release` と `uname -r` です。"
            "cgroup は v2、SELinux は通常 Enforcing、ファイアウォールは firewalld、サービス管理は systemd です。",
        ),
        (
            "2. Docker Engine であることを確認する",
            "`docker version` の Client と Server に Podman と出ないことを見ます。"
            "Red Hat が公式にサポートするコンテナエンジンは Podman です。"
            "`dnf install docker` だけだと、中身が Podman の互換コマンドになることがあります。"
            "この手順が想定するのは、Docker 社のリポジトリから入れた docker-ce です。"
            "2026年10月8日時点の公開版は Docker Engine 29.9.0 です。RHEL 9 用の docker-ce リポジトリに 29 系が出ています。"
            "デーモンが止まっているときは `systemctl status docker` を見ます。この手順ではインストール自体はしません。",
        ),
        (
            "3. プロジェクトを置く",
            f"変換元のファイル名は {plan.compose_filename} です。"
            "RHEL 上に、ビルドコンテキストごと同じ並びで置きます。コマンドだけをコピーしても、Dockerfile と設定ファイルが無いとビルドとマウントは失敗します。"
            "置いたディレクトリで `bash docker-commands.txt` を実行すると、その場所が PROJECT_ROOT になります。",
        ),
        (
            "4. 改行を壊さない",
            "行末の \\ は『まだ命令が続く』というしるしです。後ろに空白や CR があると、その行で命令が終わります。"
            "ファイルは LF で書いてあります。`file docker-commands.txt` が CRLF と言ったら、CR を消してから実行します。",
        ),
        (
            "5. そのまま実行する",
            "スクリプトは、確認、橋、ロッカー、公開イメージの取得、ビルド、依存順の起動、状態の表示、の順です。"
            "既にあるネットワーク、ボリューム、イメージ、動いているコンテナは作り直しません。"
            "最後に exit 0 があるので、ファイル全体を実行しても停止コマンドには入りません。",
        ),
        (
            "6. 材料が無いときの意味",
            "ビルドコンテキストを読んだ結果、次のファイルが未配置なら、そのイメージを焼く段階で止まります。"
            "イメージを既に持っているときは、そのビルドは飛ばします。\n" + missing_text,
        ),
        (
            "7. 止める",
            "docker-commands.txt の exit 0 より下、または command-guide の停止節を実行します。"
            "コンテナとネットワークは消えます。名前付きボリュームは残るので、データベースの中身は残ります。",
        ),
    ]
