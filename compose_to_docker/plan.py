"""正規化した Compose から、実行順の Docker コマンドと解説を組み立てる。"""

from __future__ import annotations

import re
from pathlib import Path

from compose_to_docker import explain_ja
from compose_to_docker.dockerfile import inspect_dockerfile, parse_dockerignore
from compose_to_docker.load import load_compose
from compose_to_docker.model import (
    BuildSpec,
    DockerfileFacts,
    FlagRow,
    Healthcheck,
    NamedNetwork,
    NamedVolume,
    Plan,
    Service,
    Step,
)
from compose_to_docker.shellutil import shell_quote


def build_plan(
    path: Path,
    *,
    profiles: set[str] | None = None,
    selinux: str = "z",
    use_shell_env: bool = False,
    env_files: list[Path] | None = None,
) -> Plan:
    path = path.resolve()
    project, services, networks, volumes, warnings, env_notes, _service_notes = load_compose(
        path,
        env_files=list(env_files or []),
        use_shell_env=use_shell_env,
        profiles=profiles or set(),
        selinux=selinux,
    )
    project_dir = path.parent
    _sync_implicit(services, networks, volumes, project)
    ordered = _order(services)
    steps: list[Step] = []
    steps.append(_prelude(path, project, selinux, warnings))
    for net in networks:
        if _network_used(net.key, services) or not net.external:
            if any(att.name == net.key for svc in services for att in svc.networks) or net.key == "default":
                steps.append(_network_step(net))
    for vol in volumes:
        if any(mnt.kind == "volume" and mnt.source == vol.docker_name for svc in services for mnt in svc.volumes):
            steps.append(_volume_step(vol))
    pulls = [svc for svc in ordered if not svc.build and svc.pull_policy != "never"]
    if pulls:
        steps.append(_pull_step(pulls))
    extras = _prerequisite_images(ordered, project_dir)
    built: set[tuple] = set()
    for image, dockerfile, context, facts, reason in extras:
        steps.append(
            _build_step(
                title=f"前提イメージを作る: {image}",
                tag=image,
                extra_tags=[],
                context=context,
                dockerfile=dockerfile,
                project_dir=project_dir,
                args={},
                secrets=[],
                target="",
                network="",
                platforms=[],
                cache_from=[],
                facts=facts,
                reason=reason,
            )
        )
    groups = _group_builds(ordered)
    for group in groups:
        primary = group[0]
        assert primary.build is not None
        tags = [svc.image for svc in group]
        steps.append(
            _build_step(
                title=f"イメージを作る: {', '.join(svc.name for svc in group)}",
                tag=tags[0],
                extra_tags=tags[1:],
                context=Path(primary.build.context),
                dockerfile=Path(primary.build.dockerfile),
                project_dir=project_dir,
                args=primary.build.args,
                secrets=primary.build.secrets,
                target=primary.build.target,
                network=primary.build.network,
                platforms=primary.build.platforms,
                cache_from=primary.build.cache_from,
                facts=primary.facts,
                reason=f"サービス {', '.join(svc.name for svc in group)} の build です。",
                spec=primary.build,
            )
        )
        built.add(id(primary))
    by_name = {svc.name: svc for svc in ordered}
    for svc in ordered:
        steps.append(_run_step(svc, by_name, project_dir, selinux))
    steps.append(_verify_step(ordered))
    _attach_histories(steps)
    down = _down_script(list(reversed(ordered)), networks)
    story = _story(ordered)
    overview = _overview(project, path, ordered, warnings, selinux)
    used = _used_concepts(steps, ordered)
    return Plan(
        project_name=project,
        compose_path=str(path),
        compose_filename=path.name,
        project_dir_name=project_dir.name,
        services=ordered,
        steps=steps,
        down_script=down,
        env_rows=_env_rows(ordered, env_notes),
        build_rows=_build_rows(ordered, extras, project_dir),
        mapping_rows=_mappings(project, ordered, networks, volumes, selinux),
        warnings=_dedupe(warnings),
        concepts=explain_ja.concepts_for(used),
        overview=overview,
        story=story,
        selinux=selinux,
        skipped_profiles=[item for item in warnings if item.startswith("通常の起動")],
    )


def render_script(plan: Plan) -> str:
    parts = [step.script.rstrip() for step in plan.steps if step.script.strip()]
    body = "\n\n".join(parts)
    tail = (
        "\n\necho \"\"\n"
        "echo \"起動手順はここまでです。\"\n"
        "echo \"止めるときは、このファイルの exit 0 より下だけを実行してください。\"\n"
        "exit 0\n\n"
        f"{plan.down_script.rstrip()}\n"
    )
    return body + tail


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _sync_implicit(services: list[Service], networks: list[NamedNetwork], volumes: list[NamedVolume], project: str) -> None:
    known_net = {item.key for item in networks}
    for svc in services:
        for att in svc.networks:
            if att.name not in known_net:
                networks.append(NamedNetwork(key=att.name, docker_name=att.docker_name, driver="bridge"))
                known_net.add(att.name)
    known_vol = {item.docker_name for item in volumes}
    for svc in services:
        for mnt in svc.volumes:
            if mnt.kind == "volume" and not mnt.anonymous and mnt.source not in known_vol:
                volumes.append(NamedVolume(key=mnt.source, docker_name=mnt.source))
                known_vol.add(mnt.source)


def _order(services: list[Service]) -> list[Service]:
    index = {svc.name: pos for pos, svc in enumerate(services)}
    names = set(index)
    deps = {svc.name: [item.name for item in svc.depends_on if item.name in names] for svc in services}
    depth: dict[str, int] = {}

    def walk(name: str, stack: set[str]) -> int:
        if name in depth:
            return depth[name]
        if name in stack:
            raise RuntimeError(f"depends_on が循環しています: {name}")
        stack.add(name)
        depth[name] = 0 if not deps[name] else 1 + max(walk(item, stack) for item in deps[name])
        stack.remove(name)
        return depth[name]

    for svc in services:
        walk(svc.name, set())
    return sorted(services, key=lambda svc: (depth[svc.name], index[svc.name]))


def _network_used(key: str, services: list[Service]) -> bool:
    return any(att.name == key for svc in services for att in svc.networks)


def _prelude(path: Path, project: str, selinux: str, warnings: list[str]) -> Step:
    warn_lines = "\n".join(f"echo {shell_quote('注意: ' + item)}" for item in _dedupe(warnings)[:12])
    selinux_note = (
        'echo "バインドマウントには SELinux の共有ラベル z を付けます。対象ファイルのラベルは container_file_t に変わり、ホストに残ります。"'
        if selinux == "z"
        else 'echo "バインドマウントに SELinux ラベルは付けません。Enforcing だと読み取りを拒否されることがあります。"'
        if selinux == "none"
        else f'echo "バインドマウントの SELinux ラベルは {selinux} です。Z は対象を非共有にします。広いディレクトリには使わないでください。"'
    )
    script = f"""#!/bin/bash
# {path.name} を Docker Engine のコマンドだけで起動します。
# プロジェクト名: {project}
# 改行は LF です。\\ の後ろに空白を置かないでください。
set -euo pipefail

if [ -z "${{LANG:-}}" ]; then
  export LANG=C.UTF-8
fi

say() {{
  echo ""
  echo "==== $* ===="
}}

wait_running() {{
  local name="$1"
  local timeout="${{2:-60}}"
  local elapsed=0
  local running
  echo "起動を待っています: ${{name}} （最大 ${{timeout}} 秒）"
  while [ "$elapsed" -lt "$timeout" ]; do
    running=$(docker inspect --format '{{{{.State.Running}}}}' "$name" 2>/dev/null || true)
    if [ "$running" = "true" ]; then
      echo "${{name}} は動いています。"
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  echo "${{name}} が起動する前に時間切れです。" >&2
  docker logs --tail 80 "$name" >&2 || true
  return 1
}}

wait_healthy() {{
  local name="$1"
  local timeout="${{2:-180}}"
  local elapsed=0
  local status
  echo "healthy になるのを待っています: ${{name}} （最大 ${{timeout}} 秒）"
  while [ "$elapsed" -lt "$timeout" ]; do
    status=$(docker inspect --format '{{{{if .State.Health}}}}{{{{.State.Health.Status}}}}{{{{else}}}}nohealth{{{{end}}}}' "$name" 2>/dev/null || true)
    echo "  ${{elapsed}}秒時点: ${{name}} は ${{status:-不明}}"
    if [ "$status" = "healthy" ]; then
      echo "${{name}} は healthy です。"
      return 0
    fi
    if [ "$status" = "unhealthy" ]; then
      echo "${{name}} は unhealthy です。ログの末尾を表示します。" >&2
      docker logs --tail 80 "$name" >&2 || true
      return 1
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done
  echo "${{name}} が healthy になる前に時間切れです。" >&2
  docker logs --tail 80 "$name" >&2 || true
  return 1
}}

say "実行前の確認"
if ! command -v docker >/dev/null 2>&1; then
  echo "docker コマンドが見つかりません。Docker Engine が入っているか確認してください。" >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker デーモンに接続できません。systemctl status docker を確認してください。" >&2
  echo "権限が無いときは、docker グループへ入るか、管理者が許可した方法で実行してください。" >&2
  exit 1
fi
if docker version 2>/dev/null | grep -qi podman; then
  echo "この docker は Podman の互換コマンドに見えます。この手順は Docker Engine 向けです。" >&2
  exit 1
fi
if [ -z "${{PROJECT_ROOT:-}}" ]; then
  if [ -f "./{path.name}" ]; then
    PROJECT_ROOT="$(pwd)"
  else
    echo "PROJECT_ROOT が空で、今いる場所に {path.name} もありません。" >&2
    echo "プロジェクトのディレクトリで実行するか、PROJECT_ROOT を指定してください。" >&2
    exit 1
  fi
fi
if [ ! -f "${{PROJECT_ROOT}}/{path.name}" ]; then
  echo "プロジェクトの目印がありません: ${{PROJECT_ROOT}}/{path.name}" >&2
  exit 1
fi
echo "プロジェクトディレクトリ: ${{PROJECT_ROOT}}"
docker version --format 'クライアント {{{{.Client.Version}}}} / サーバ {{{{.Server.Version}}}}'
if command -v getenforce >/dev/null 2>&1; then
  echo "SELinux: $(getenforce)"
fi
{selinux_note}
{warn_lines}
"""
    return Step(
        phase="準備",
        title="実行前の確認",
        script=script,
        summary=(
            "Docker Engine に接続できること、プロジェクトの場所、SELinux の状態を確認します。"
            "このあとで使う待ち関数も、ここで定義します。"
        ),
        how_to=(
            "RHEL 上で、プロジェクトのディレクトリに入って bash docker-commands.txt と実行します。"
            "別の場所からなら PROJECT_ROOT=/実際のパス bash docker-commands.txt です。"
        ),
        success="クライアントとサーバの版、SELinux の状態が表示され、次の段階へ進みます。",
        failure="docker が無い、デーモンが止まっている、Podman 互換である、PROJECT_ROOT が違う、のいずれかです。",
        principle="窓口が本当に Docker Engine か、材料の置いてあるディレクトリはどこか、を最初に固定します。",
        analogy="文化祭の朝に、本部の窓口が開いているか、模擬店の段ボールはどの教室か、を確認する段階です。",
        history="",
        why="途中で失敗したときに、原因が準備不足なのか命令の中身なのかを分けられるようにするためです。",
        concept_ids=["why", "client", "selinux", "linebreak"],
        flags=[
            FlagRow("準備", "シェル", "set -euo pipefail", "", "失敗したらすぐ止まり、未設定の変数もエラーにします。", "途中の失敗を見逃して次へ進みません。", "間違えたら手を止める約束です。", "手順を自動化するときに、成功したふりを防ぐための定番です。"),
            FlagRow("準備", "シェル", "wait_healthy", "名前と秒数", "docker inspect で健康状態を見て、healthy まで待つか unhealthy で止まります。", "5秒ごとに状態を表示します。", "先生がドアをノックして回る係です。", "depends_on は Engine の機能ではないので、状態を見るループで代用します。"),
            FlagRow("準備", "シェル", "wait_running", "名前と秒数", "コンテナのプロセスが動き始めたことを確認します。", "2秒ごとに見ます。健康であることは確認しません。", "看板が掛かったことだけを見ます。", "service_started は『健康』ではなく『プロセスが動いた』です。"),
        ],
    )


def _network_step(net: NamedNetwork) -> Step:
    if net.external:
        script = f"""say "外部ネットワークを確認する: {net.docker_name}"
if ! docker network inspect {shell_quote(net.docker_name)} >/dev/null 2>&1; then
  echo "外部ネットワークがありません: {net.docker_name}" >&2
  echo "Compose の external: true は、こちらで新規作成しません。" >&2
  exit 1
fi
echo "外部ネットワークを使います: {net.docker_name}"
"""
        pieces = [("docker network inspect", net.docker_name)]
    else:
        parts = []
        flags = []
        if net.driver:
            parts.append(f"--driver {shell_quote(net.driver)}")
            flags.append(("--driver", net.driver))
        if net.subnet:
            parts.append(f"--subnet {shell_quote(net.subnet)}")
            flags.append(("--subnet", net.subnet))
        if net.gateway:
            parts.append(f"--gateway {shell_quote(net.gateway)}")
            flags.append(("--gateway", net.gateway))
        if net.internal:
            parts.append("--internal")
            flags.append(("--internal", ""))
        if net.attachable:
            parts.append("--attachable")
            flags.append(("--attachable", ""))
        if net.enable_ipv6:
            parts.append("--ipv6")
            flags.append(("--ipv6", ""))
        for opt in net.driver_opts:
            parts.append(f"--opt {shell_quote(opt)}")
            flags.append(("--opt", opt))
        parts.append(shell_quote(net.docker_name))
        flags.append(("ネットワーク名", net.docker_name))
        create = _continued("docker network create", parts)
        script = f"""say "橋ネットワークを作る: {net.docker_name}"
if docker network inspect {shell_quote(net.docker_name)} >/dev/null 2>&1; then
  echo "ネットワークは既にあります: {net.docker_name}"
else
{_indent(create, 2)}
fi
"""
        pieces = flags
    flag_rows = []
    for flag, value in pieces:
        if flag == "ネットワーク名":
            meaning = (
                f"作成する橋の名前は {value} です。",
                "以降の docker run --network が、この名前を指定します。",
                "机に付ける名前です。",
                "Compose はプロジェクト名とネットワーク名をアンダースコアで結びます。コンテナ名のハイフンとは別の時代の規則です。",
            )
        else:
            meaning = explain_ja.flag_explainer(flag, value)
        flag_rows.append(FlagRow("ネットワーク", net.docker_name, flag, value, *meaning))
    return Step(
        phase="ネットワーク",
        title=f"ネットワーク {net.docker_name}",
        script=script,
        summary=(
            f"コンテナが名前で呼び合うための橋を用意します。Compose 上の名前は {net.key}、"
            f"Docker 上の名前は {net.docker_name} です。プロジェクト名とネットワーク名のあいだはアンダースコアです。"
        ),
        how_to="この段階だけを再実行しても、既にあれば作り直しません。消すときは停止手順のあとで docker network rm を使います。",
        success="docker network inspect が名前、ドライバ、サブネットを表示できる状態です。",
        failure="同名の別ドライバが残っている、権限が無い、指定サブネットが重なっている、のいずれかです。",
        principle="同じ橋にいるコンテナだけが、サービス名の名札で互いに届きます。外の世界とはまだつながっていません。",
        analogy="模擬店のあいだに、校舎の中だけの長い机を出す段階です。",
        history="",
        why="コンテナは最初、互いの名前を知りません。名前で呼べる範囲を先に作らないと、アプリが接続先を見つけられません。",
        concept_ids=["network"],
        flags=flag_rows,
    )


def _volume_step(vol: NamedVolume) -> Step:
    if vol.external:
        script = f"""say "外部ボリュームを確認する: {vol.docker_name}"
if ! docker volume inspect {shell_quote(vol.docker_name)} >/dev/null 2>&1; then
  echo "外部ボリュームがありません: {vol.docker_name}" >&2
  exit 1
fi
"""
    else:
        parts = []
        if vol.driver:
            parts.append(f"--driver {shell_quote(vol.driver)}")
        for opt in vol.driver_opts:
            parts.append(f"--opt {shell_quote(opt)}")
        parts.append(shell_quote(vol.docker_name))
        create = _continued("docker volume create", parts)
        script = f"""say "データを残すロッカーを作る: {vol.docker_name}"
if docker volume inspect {shell_quote(vol.docker_name)} >/dev/null 2>&1; then
  echo "ボリュームは既にあります: {vol.docker_name}"
else
{_indent(create, 2)}
fi
"""
    return Step(
        phase="ボリューム",
        title=f"ボリューム {vol.docker_name}",
        script=script,
        summary=(
            f"コンテナを消しても残る保存場所 {vol.docker_name} を作ります。"
            "中にデータベースのファイルが入ります。停止手順では、このロッカーは消しません。"
        ),
        how_to="中身を捨てるときだけ、コンテナを止めたあとに docker volume rm を別に実行します。",
        success="docker volume inspect に Name と Mountpoint が出ます。",
        failure="同名の壊れたボリュームがある、ディスクが足りない、権限が無い、のいずれかです。",
        principle="コンテナの書き込み層はコンテナと一緒に消えます。残したいデータは、最初から外のロッカーへ置きます。",
        analogy="冷蔵庫の中身を、お店の机ではなく校舎のロッカーへ置く段階です。",
        history="",
        why="コンテナを作り直すたびにデータベースが空になると、起動のたびに初期データからやり直しになるためです。",
        concept_ids=["volume"],
        flags=[
            FlagRow("ボリューム", vol.docker_name, "docker volume create", vol.docker_name, "Docker 管理下の名前付き保存場所を作ります。", "実体は Docker のデータディレクトリの中にできます。", "名前の付いたロッカーを1つ用意します。", "ホストの適当なディレクトリを直接使うと、権限と SELinux とバックアップがばらばらになるため、名前付きボリュームが分かれました。"),
        ],
    )


def _pull_step(services: list[Service]) -> Step:
    blocks = []
    flags = []
    seen = set()
    for svc in services:
        if svc.image in seen:
            continue
        seen.add(svc.image)
        flags.append(FlagRow("取得", svc.name, "docker pull", svc.image, f"{svc.name} が使う {svc.image} を、手元に無いときだけ取り寄せます。", "レジストリから層を受信し、ローカルのイメージ一覧に載ります。", "倉庫からレシピカードを取り寄せます。", "Compose の pull_policy の既定（手元に無いとき）に揃えています。毎回取り寄せると、同じタグの中身が変わることがあります。"))
        blocks.append(
            f"""if docker image inspect {shell_quote(svc.image)} >/dev/null 2>&1; then
  echo "イメージは手元にあります: {svc.image}"
else
  docker pull {shell_quote(svc.image)}
fi"""
        )
    script = "say \"手元に無い公開イメージを取り寄せる\"\n" + "\n".join(blocks) + "\n"
    return Step(
        phase="取得",
        title="公開イメージを取り寄せる",
        script=script,
        summary="ビルドせずに image だけが書いてあるサービスについて、同じタグが手元に無いときだけ docker pull します。",
        how_to="回線と、必要なら HTTPS_PROXY を用意してから実行します。既にあれば取り寄せません。",
        success="各イメージに対して『手元にあります』か、pull の完了メッセージが出ます。",
        failure="名前解決、プロキシ、認証、ディスク不足です。メッセージの画像名を見て、そのレジストリだけを確認します。",
        principle="完成済みのカードは倉庫から取り、このプロジェクトで焼くカードは次の段階で作ります。",
        analogy="既製品の冷蔵庫と掲示板を、カタログの番号で取り寄せる段階です。",
        history="",
        why="MySQL や Jaeger を毎回ソースから作ると、この環境の目的であるアプリの確認にたどり着けないためです。",
        concept_ids=["pull", "image"],
        flags=flags,
    )


def _build_step(
    *,
    title: str,
    tag: str,
    extra_tags: list[str],
    context: Path,
    dockerfile: Path,
    project_dir: Path,
    args: dict[str, str],
    secrets: list,
    target: str,
    network: str,
    platforms: list[str],
    cache_from: list[str],
    facts: DockerfileFacts | None,
    reason: str,
    spec: BuildSpec | None = None,
) -> Step:
    context_rel = _rel(context, project_dir)
    file_rel = _rel(dockerfile, project_dir)
    parts = [f"--file {_bash_project(file_rel)}", f"--tag {shell_quote(tag)}"]
    flag_rows = [
        FlagRow("ビルド", tag, "--file", file_rel, "段ボールの中の、どのレシピを読むかを指定します。", "Dockerfile という名前でなくてもビルドできます。", "段ボールに入っているレシピカードの指定です。", "ファイル名が Dockerfile でない Containerfile を使うプロジェクトがあるため、--file が必要です。"),
        FlagRow("ビルド", tag, "--tag", tag, "できたイメージに、この名前と付箋を付けます。", "docker image ls でこの名前が見えます。", "出来上がったカードへ付箋を貼ります。", "タグが無いと、次の docker run がどのカードを開けばよいか指定できません。"),
    ]
    for key, value in args.items():
        parts.append(f"--build-arg {shell_quote(f'{key}={value}')}")
        flag_rows.append(FlagRow("ビルド", tag, "--build-arg", f"{key}={value}", "レシピの ARG を、この値で上書きします。", "FROM や COPY の変数が、この値で展開されます。", "レシピの空欄を、焼く前に鉛筆で埋めます。", "同じレシピから、土台イメージや WAR の場所だけ違うカードを焼くために ARG があります。"))
    for secret in secrets:
        if secret.kind == "env":
            rendered = f"id={secret.ident},env={secret.value}"
            parts.append(f"--secret {shell_quote(rendered)}")
            flag_rows.append(
                FlagRow(
                    "ビルド",
                    tag,
                    "--secret",
                    rendered,
                    "ビルド中だけ環境変数から秘密を渡します。イメージの層には残りません。",
                    "BuildKit が /run/secrets へ一時的に見せます。変数自体はこのコマンド行には出しません。",
                    "厨房の中だけで見るメモで、完成品のカードには写しません。",
                    "環境変数や COPY で渡すと層の履歴に秘密が残るため、BuildKit の secret が後から必要になりました。",
                )
            )
            continue
        rel = None if secret.value.startswith("/") else _try_rel(secret.value, project_dir)
        if rel is None:
            rendered = f"id={secret.ident},src={secret.value}"
            parts.append(f"--secret {shell_quote(rendered)}")
        else:
            rendered = "id=" + secret.ident + ",src=${PROJECT_ROOT}/" + rel
            parts.append('--secret "' + rendered + '"')
        flag_rows.append(
            FlagRow(
                "ビルド",
                tag,
                "--secret",
                rendered.replace("${{PROJECT_ROOT}}", "${PROJECT_ROOT}"),
                "ビルド中だけファイルを秘密として渡します。",
                "ビルドの RUN --mount=type=secret から読めます。",
                "厨房の中だけで開く封筒です。",
                "証明書束のように、イメージへ残したくないファイルを渡すための指定です。",
            )
        )
    if target:
        parts.append(f"--target {shell_quote(target)}")
        flag_rows.append(FlagRow("ビルド", tag, "--target", target, "多段レシピの、どの段で止めるかを指定します。", "後ろの段は実行されません。", "レシピの途中の完成で止めます。", "最終段以外を配りたい多段ビルドのために --target があります。"))
    if network:
        parts.append(f"--network {shell_quote(network)}")
    for plat in platforms:
        parts.append(f"--platform {shell_quote(plat)}")
    for cache in cache_from:
        parts.append(f"--cache-from {shell_quote(cache)}")
    parts.append(_bash_project(context_rel))
    flag_rows.append(FlagRow("ビルド", tag, "コンテキスト", context_rel or ".", "ビルドに渡すファイルの範囲です。", "このディレクトリ以下だけが COPY の対象になります。", "厨房へ渡す段ボールです。", "レシピから親ディレクトリの外を読めないことで、意図しないファイルの混入を防ぎます。"))
    create = _continued("docker build", parts)
    checks = _missing_checks(facts, context_rel)
    hint = ""
    server_source = (facts.arg_defaults.get("SERVER_SOURCE") if facts else "") or ""
    if server_source:
        hint = (
            "  echo "
            + shell_quote(
                "このレシピの SERVER_SOURCE の既定は "
                + server_source
                + " です。切り替えるときは docker build に --build-arg SERVER_SOURCE=別の値 を足します。この手順は既定のままです。"
            )
            + "\n"
        )
    tag_block = ""
    for extra in extra_tags:
        tag_block += (
            f"\nif ! docker image inspect {shell_quote(extra)} >/dev/null 2>&1; then\n"
            f"  docker tag {shell_quote(tag)} {shell_quote(extra)}\n"
            f"fi"
        )
        flag_rows.append(FlagRow("ビルド", extra, "docker tag", f"{tag} -> {extra}", "同じカードに、別の付箋を付けます。中身のビルドは1回です。", "2つ目の名前でも docker run できます。", "同じ料理に、店ごとの品書き名を付けることです。", "ビルドコンテキストと引数が同じサービスを、二度焼かないためです。"))
    note = reason
    if facts and facts.from_images:
        public: list[str] = []
        for image in facts.from_images:
            if image in facts.stages or image in public:
                continue
            public.append(image)
        if public:
            note += " 外から取る土台は " + "、".join(public) + " です。"
    script = f"""say "{title}"
echo {shell_quote(note)}
if docker image inspect {shell_quote(tag)} >/dev/null 2>&1; then
  echo "イメージは既にあるのでビルドしません: {tag}"
  echo "材料を変えて作り直すときは、先に docker image rm {tag} を実行します。"
else
{hint}{checks}{_indent(create, 2)}
fi{tag_block}
"""
    summary = note
    if facts and facts.missing_sources:
        summary += " 今の作業ツリーでは次が未配置です: " + "、".join(facts.missing_sources) + "。イメージが既にある場合はビルドを飛ばします。"
    return Step(
        phase="ビルド",
        title=title,
        script=script,
        summary=summary,
        how_to="プロジェクトディレクトリの中身が、RHEL 上の PROJECT_ROOT と同じ配置になっている必要があります。カードが既にあれば、この段階は確認だけです。",
        success="docker image inspect が成功し、次の段階へ進みます。",
        failure="COPY の材料が無い、FROM の土台が無い、プロキシで倉庫へ届かない、ディスク不足、のいずれかです。",
        principle="レシピと段ボールから、読み取り専用のカードを焼きます。コンテナはこの時点ではまだ開きません。",
        analogy="材料を厨房へ渡し、レシピどおりにカードを焼く段階です。",
        history="",
        why="実行のたびに同じインストールを繰り返さず、焼いたカードを名前で開けるようにするためです。",
        concept_ids=["build", "image"],
        flags=flag_rows,
    )


def _run_step(svc: Service, by_name: dict[str, Service], project_dir: Path, selinux: str) -> Step:
    waits = []
    dep_sentences = []
    for dep in svc.depends_on:
        other = by_name.get(dep.name)
        if other is None:
            dep_sentences.append(f"{dep.name} は今回の起動対象に無いので待ちません")
            continue
        if dep.condition == "service_healthy":
            seconds = _health_budget(other.healthcheck)
            waits.append(f"wait_healthy {shell_quote(other.container_name)} {seconds}")
            dep_sentences.append(f"{other.container_name} が healthy（最大 {seconds} 秒）")
        elif dep.condition == "service_completed_successfully":
            waits.append(
                f"code=\"$(docker wait {shell_quote(other.container_name)})\"\n"
                f"if [ \"$code\" != \"0\" ]; then echo {shell_quote(other.container_name + ' が正常終了しませんでした')} >&2; exit 1; fi"
            )
            dep_sentences.append(f"{other.container_name} が終了コード 0")
        else:
            waits.append(f"wait_running {shell_quote(other.container_name)} 90")
            dep_sentences.append(f"{other.container_name} のプロセスが動いている")
    pieces, flag_rows, command_args = _run_pieces(svc, project_dir, selinux)
    run = _continued("docker run", pieces + [shell_quote(svc.image)] + [shell_quote(arg) for arg in command_args])
    connects = _connect_lines(svc)
    launched = _indent(run, 2)
    if connects:
        launched += "\n" + connects
    body = ""
    if waits:
        body += "\n".join(waits) + "\n"
    body += f"""if docker container inspect {shell_quote(svc.container_name)} >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{{{.State.Running}}}}' {shell_quote(svc.container_name)})" = "true" ]; then
    echo "既に動いています: {svc.container_name}"
  else
    echo "止まっているので起動します: {svc.container_name}"
    docker start {shell_quote(svc.container_name)}
  fi
else
{launched}
fi
"""
    script = f"say \"起動する: {svc.container_name}\"\n" + body
    summary_lines = [
        f"{svc.container_name} を起動します。{explain_ja.analogy_for(svc)}",
        f"イメージは {svc.image} です。",
    ]
    if svc.ports:
        summary_lines.append("ホストへ開く扉は " + "、".join(svc.ports) + " です。")
    if svc.read_only:
        summary_lines.append("ルートファイルシステムは読み取り専用です。")
    if svc.tmpfs:
        summary_lines.append("消える作業場所は " + "、".join(svc.tmpfs) + " です。")
    if dep_sentences:
        summary_lines.append("その前に確認すること: " + "。".join(dep_sentences) + "。")
    if svc.networks:
        summary_lines.append(
            "同じネットワークでは "
            + "、".join(svc.networks[0].aliases)
            + f" という名札で届きます。台帳の名前は {svc.container_name} です。"
        )
    if svc.command:
        summary_lines.append("イメージ名の後ろの引数で、起動コマンドを差し替えます。")
    if svc.comments:
        summary_lines.append("元の定義のメモ: " + svc.comments.splitlines()[0][:240])
    return Step(
        phase="起動",
        title=f"起動する: {svc.container_name}",
        script=script,
        summary="\n".join(summary_lines),
        how_to="依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。",
        success=f"docker ps に {svc.container_name} が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。",
        failure="同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。",
        principle="カードの上に書き込み層を足し、橋とロッカーと扉とポケットメモを取り付けて、プロセスを開始します。",
        analogy=explain_ja.analogy_for(svc),
        history="",
        why="イメージは静止したカードなので、名前と接続と環境を付けて、初めてプロセスとして動き始めます。",
        concept_ids=["container", "detach", "network", "env"],
        flags=flag_rows,
        service=svc.name,
    )


def _run_pieces(svc: Service, project_dir: Path, selinux: str) -> tuple[list[str], list[FlagRow], list[str]]:
    pieces: list[str] = ["--detach", f"--name {shell_quote(svc.container_name)}"]
    flags = [
        FlagRow("起動", svc.container_name, "--detach", "", *explain_ja.flag_explainer("--detach", "")),
        FlagRow("起動", svc.container_name, "--name", svc.container_name, *explain_ja.flag_explainer("--name", svc.container_name)),
    ]
    if svc.hostname:
        pieces.append(f"--hostname {shell_quote(svc.hostname)}")
        flags.append(FlagRow("起動", svc.container_name, "--hostname", svc.hostname, *explain_ja.flag_explainer("--hostname", svc.hostname)))
    if svc.network_mode:
        mode = svc.network_mode
        if mode.startswith("service:"):
            mode = "container:" + mode.split(":", 1)[1]
        pieces.append(f"--network {shell_quote(mode)}")
        flags.append(FlagRow("起動", svc.container_name, "--network", mode, *explain_ja.flag_explainer("--network", mode)))
    elif svc.networks:
        first = svc.networks[0]
        pieces.append(f"--network {shell_quote(first.docker_name)}")
        flags.append(FlagRow("起動", svc.container_name, "--network", first.docker_name, *explain_ja.flag_explainer("--network", first.docker_name)))
        for alias in first.aliases:
            pieces.append(f"--network-alias {shell_quote(alias)}")
            flags.append(FlagRow("起動", svc.container_name, "--network-alias", alias, *explain_ja.flag_explainer("--network-alias", alias)))
        if first.ipv4_address:
            pieces.append(f"--ip {shell_quote(first.ipv4_address)}")
            flags.append(FlagRow("起動", svc.container_name, "--ip", first.ipv4_address, *explain_ja.flag_explainer("--ip", first.ipv4_address)))
    if svc.restart:
        pieces.append(f"--restart {shell_quote(svc.restart)}")
        flags.append(FlagRow("起動", svc.container_name, "--restart", svc.restart, *explain_ja.flag_explainer("--restart", svc.restart)))
    if svc.read_only:
        pieces.append("--read-only")
        flags.append(FlagRow("起動", svc.container_name, "--read-only", "", *explain_ja.flag_explainer("--read-only", "")))
    if svc.user:
        pieces.append(f"--user {shell_quote(svc.user)}")
        flags.append(FlagRow("起動", svc.container_name, "--user", svc.user, *explain_ja.flag_explainer("--user", svc.user)))
    if svc.working_dir:
        pieces.append(f"--workdir {shell_quote(svc.working_dir)}")
        flags.append(FlagRow("起動", svc.container_name, "--workdir", svc.working_dir, *explain_ja.flag_explainer("--workdir", svc.working_dir)))
    if svc.init:
        pieces.append("--init")
        flags.append(FlagRow("起動", svc.container_name, "--init", "", *explain_ja.flag_explainer("--init", "")))
    if svc.privileged:
        pieces.append("--privileged")
        flags.append(FlagRow("起動", svc.container_name, "--privileged", "", *explain_ja.flag_explainer("--privileged", "")))
    if svc.platform:
        pieces.append(f"--platform {shell_quote(svc.platform)}")
        flags.append(FlagRow("起動", svc.container_name, "--platform", svc.platform, *explain_ja.flag_explainer("--platform", svc.platform)))
    if svc.stdin_open:
        pieces.append("--interactive")
    if svc.tty:
        pieces.append("--tty")
    for port in svc.ports:
        pieces.append(f"--publish {shell_quote(port)}")
        flags.append(FlagRow("起動", svc.container_name, "--publish", port, *explain_ja.flag_explainer("--publish", port)))
    for item in svc.expose:
        pieces.append(f"--expose {shell_quote(item)}")
        flags.append(FlagRow("起動", svc.container_name, "--expose", item, *explain_ja.flag_explainer("--expose", item)))
    for mnt in svc.volumes:
        rendered = _volume_arg(mnt, project_dir)
        pieces.append(f"--volume {rendered}")
        flags.append(FlagRow("起動", svc.container_name, "--volume", rendered.strip('"'), *explain_ja.flag_explainer("--volume", rendered.strip('"'))))
    for spec in svc.tmpfs:
        pieces.append(f"--tmpfs {shell_quote(spec)}")
        flags.append(FlagRow("起動", svc.container_name, "--tmpfs", spec, *explain_ja.flag_explainer("--tmpfs", spec)))
    env_count = 0
    for key, value in _last_env(svc.environment):
        env_count += 1
        if value is None:
            pieces.append(f"--env {shell_quote(key)}")
        else:
            pieces.append(f"--env {shell_quote(key + '=' + value)}")
    if env_count:
        flags.append(
            FlagRow(
                "起動",
                svc.container_name,
                "--env",
                f"{env_count} 個",
                "環境変数を1行に1つ渡します。各値の意味は『環境変数』シートです。",
                "プロセスの初期環境に入ります。シェルには展開させず、単一引用符で渡します。",
                "ポケットメモを枚数分、机へ置きます。",
                "接続先やパスワードをイメージに焼かないために、実行時の --env が残っています。",
            )
        )
    if svc.healthcheck and not svc.healthcheck.disable:
        cmd = _health_shell(svc.healthcheck)
        if cmd:
            pieces.append(f"--health-cmd {shell_quote(cmd)}")
            flags.append(FlagRow("起動", svc.container_name, "--health-cmd", cmd, *explain_ja.flag_explainer("--health-cmd", cmd)))
        for flag, raw in (
            ("--health-interval", svc.healthcheck.interval),
            ("--health-timeout", svc.healthcheck.timeout),
            ("--health-start-period", svc.healthcheck.start_period),
            ("--health-start-interval", svc.healthcheck.start_interval),
        ):
            if raw:
                pieces.append(f"{flag} {shell_quote(raw)}")
                flags.append(FlagRow("起動", svc.container_name, flag, raw, *explain_ja.flag_explainer(flag, raw)))
        if svc.healthcheck.retries is not None:
            pieces.append(f"--health-retries {svc.healthcheck.retries}")
            flags.append(FlagRow("起動", svc.container_name, "--health-retries", str(svc.healthcheck.retries), *explain_ja.flag_explainer("--health-retries", str(svc.healthcheck.retries))))
    elif svc.healthcheck and svc.healthcheck.disable:
        pieces.append("--no-healthcheck")
        flags.append(FlagRow("起動", svc.container_name, "--no-healthcheck", "", *explain_ja.flag_explainer("--no-healthcheck", "")))
    simple_pairs = [
        ("--add-host", svc.extra_hosts),
        ("--cap-add", svc.cap_add),
        ("--cap-drop", svc.cap_drop),
        ("--security-opt", svc.security_opt),
        ("--device", svc.devices),
        ("--sysctl", svc.sysctls),
        ("--ulimit", svc.ulimits),
        ("--dns", svc.dns),
        ("--dns-search", svc.dns_search),
        ("--group-add", svc.group_add),
        ("--label", svc.labels),
        ("--log-opt", svc.log_options),
        ("--volumes-from", svc.volumes_from),
    ]
    for flag, values in simple_pairs:
        for value in values:
            pieces.append(f"{flag} {shell_quote(value)}")
            flags.append(FlagRow("起動", svc.container_name, flag, value, *explain_ja.flag_explainer(flag, value)))
    single = [
        ("--log-driver", svc.log_driver),
        ("--memory", svc.memory),
        ("--memory-reservation", svc.memory_reservation),
        ("--cpus", svc.cpus),
        ("--pids-limit", svc.pids_limit),
        ("--shm-size", svc.shm_size),
        ("--stop-timeout", svc.stop_timeout),
        ("--stop-signal", svc.stop_signal),
        ("--pid", svc.pid_mode),
        ("--ipc", svc.ipc_mode),
        ("--gpus", svc.gpus),
    ]
    for flag, value in single:
        if value:
            pieces.append(f"{flag} {shell_quote(value)}")
            flags.append(FlagRow("起動", svc.container_name, flag, value, *explain_ja.flag_explainer(flag, value)))
    entry_args: list[str] = []
    if svc.entrypoint is not None:
        if svc.entrypoint:
            pieces.append(f"--entrypoint {shell_quote(svc.entrypoint[0])}")
            flags.append(FlagRow("起動", svc.container_name, "--entrypoint", svc.entrypoint[0], *explain_ja.flag_explainer("--entrypoint", svc.entrypoint[0])))
            entry_args.extend(svc.entrypoint[1:])
        else:
            pieces.append("--entrypoint \"\"")
    command_args = entry_args + (svc.command or [])
    return pieces, flags, command_args


def _connect_lines(svc: Service) -> str:
    if svc.network_mode or len(svc.networks) <= 1:
        return ""
    lines = []
    for att in svc.networks[1:]:
        alias_args = " ".join(f"--alias {shell_quote(alias)}" for alias in att.aliases)
        ip = f"--ip {shell_quote(att.ipv4_address)} " if att.ipv4_address else ""
        lines.append(
            f"  docker network connect {alias_args} {ip}{shell_quote(att.docker_name)} {shell_quote(svc.container_name)}"
        )
    return "\n".join(lines)


def _verify_step(services: list[Service]) -> Step:
    lines = [
        'say "起動結果を確認する"',
        "docker ps --format 'table {{.Names}}\\t{{.Status}}\\t{{.Ports}}'",
    ]
    flags = [FlagRow("確認", "全部", "docker ps", "", "今動いているコンテナの名前、状態、扉を表にします。", "Status に healthy や starting が出ます。", "開店した店の一覧を見ます。", "docker ps は初期からある、動いているコンテナの一覧です。")]
    for svc in services:
        if svc.healthcheck and not svc.healthcheck.disable:
            lines.append(
                "docker inspect --format '{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{else}}healthcheckなし{{end}}' "
                + shell_quote(svc.container_name)
            )
    lines.append('echo "ログを追うときは docker logs --tail 50 コンテナ名 を実行します。"')
    return Step(
        phase="確認",
        title="起動結果を確認する",
        script="\n".join(lines) + "\n",
        summary="一覧と、ヘルスチェックを持つコンテナの状態を表示します。ここで healthy でなくても、猶予時間のあいだは starting のことがあります。",
        how_to="失敗している名前だけ docker logs --tail 100 名前 で見ます。全部を一度に見たいときは docker ps の Status 列を上から見ます。",
        success="期待したコンテナ名が並び、依存の末端は healthy か、起動直後なら starting です。",
        failure="一覧に名前が無いときは、その起動段階のメッセージとログを見ます。unhealthy なら検査コマンドの失敗です。",
        principle="起動コマンドが戻ったことは、アプリが仕事を受けられることと同じではありません。状態を別に見ます。",
        analogy="全部の店を回って、看板と準備の札を確認する段階です。",
        history="",
        why="切り離して起動すると、その場にログが出ません。あとから同じ名前で状態を見る必要がありました。",
        concept_ids=["health", "detach"],
        flags=flags,
    )


def _down_script(reversed_services: list[Service], networks: list[NamedNetwork]) -> str:
    lines = [
        "#!/bin/bash",
        "# 停止用です。コンテナとネットワークを消し、名前付きボリュームとイメージは残します。",
        "set -euo pipefail",
        'echo "コンテナを止めて捨てます。ボリュームは残します。"',
    ]
    for svc in reversed_services:
        lines.append(f"docker rm --force {shell_quote(svc.container_name)} || true")
    lines.append('echo "ネットワークを消します。"')
    for net in networks:
        if not net.external:
            lines.append(f"docker network rm {shell_quote(net.docker_name)} || true")
    lines.append('echo "ボリュームは残しています。データも捨てるときだけ、次を手で実行します。"')
    lines.append('echo "  docker volume ls"')
    lines.append('echo "停止が終わりました。"')
    return "\n".join(lines) + "\n"


def _attach_histories(steps: list[Step]) -> None:
    seen: set[str] = set()
    texts = {
        "準備": "手順を小さな命令に分ける書き方は、Bourne shell の行継続と、失敗で止める set -e が土台です。Compose が隠していた確認を、先頭に戻しています。",
        "ネットワーク": "2015年11月の Docker 1.9 まで、コンテナ同士は --link で結んでいました。名前の付く橋が入って、Compose のサービス名が使えるようになりました。",
        "ボリューム": "コンテナの層は消えるため、2014年から2015年にかけて名前付きボリュームが整理されました。データベースを残す場所が、コンテナの寿命から独立しました。",
        "取得": "2014年の Docker Hub 以降、完成品のイメージを名前で取り寄せるのが普通になりました。タグは動き得るので、再現が必要ならダイジェストで固定します。",
        "ビルド": "Dockerfile は Docker の初期からあります。直列で遅かったビルドは、2017年の BuildKit と、2023年の Engine 23 で標準になった並列ビルドへ変わりました。",
        "起動": "docker run は『カードを開く』窓口です。2016年の HEALTHCHECK と、実行時の --health-* により、イメージの自己申告と運用の猶予を分けられるようになりました。",
        "確認": "切り離し起動では、その場にログが残りません。docker ps と docker inspect と docker logs の3つで、後から状態を見ます。",
    }
    short = "同じ種類の命令です。違うのは名前、対象、依存です。詳しい歴史は『動作原理と歴史』の同じ用語を読んでください。"
    for step in steps:
        if step.phase not in seen:
            step.history = texts.get(step.phase, short)
            seen.add(step.phase)
        else:
            step.history = short


def _story(services: list[Service]) -> str:
    lines = [
        "この環境を、学校の文化祭の模擬店として読むと次のようになります。",
        "校舎は1台の RHEL です。Docker は本部の窓口です。橋ネットワークは、店同士だけが通れる廊下です。",
    ]
    for svc in services:
        lines.append(f"{svc.container_name}: {explain_ja.analogy_for(svc)}")
    lines.append("お客さんが外から入るのは、--publish で開けた正門だけです。店同士の会話は、廊下の名札で足ります。")
    return "\n".join(lines)


def _overview(project: str, path: Path, services: list[Service], warnings: list[str], selinux: str) -> str:
    names = "、".join(svc.container_name for svc in services)
    text = (
        f"対象は {path.name}、プロジェクト名は {project} です。"
        f"起動するコンテナは {len(services)} 台で、名前は {names} です。"
        "Compose は呼ばず、docker network、docker volume、docker pull、docker build、docker run、docker inspect だけで同じ並びを作ります。"
        f"バインドマウントの SELinux 指定は {selinux or 'なし'} です。"
        "値は Compose ファイルの ${VAR:-既定} を、変換時に埋めた結果です。変換したマシンの環境変数は、指定しない限り使いません。"
    )
    if warnings:
        text += "\n変換時の注意: " + " / ".join(_dedupe(warnings)[:8])
    return text


def _used_concepts(steps: list[Step], services: list[Service]) -> set[str]:
    used = {"image", "container", "detach"}
    phases = {step.phase for step in steps}
    if "ビルド" in phases:
        used.add("build")
    if "ネットワーク" in phases:
        used.add("network")
    if "ボリューム" in phases or any(svc.volumes or svc.tmpfs for svc in services):
        used.add("volume")
    if any(svc.ports for svc in services):
        used.add("publish")
    if any(svc.environment for svc in services):
        used.add("env")
    if any(svc.healthcheck for svc in services):
        used.add("health")
    if any(svc.command or svc.entrypoint for svc in services):
        used.add("entrypoint")
    if "取得" in phases:
        used.add("pull")
    return used


def _env_rows(services: list[Service], notes: dict[str, str]):
    from compose_to_docker.model import EnvRow

    rows = []
    for svc in services:
        for key, value in _last_env(svc.environment):
            note = notes.get(key, "")
            if value is None:
                shown = "（実行する RHEL の環境から渡す）"
                source = "値を書かない指定"
            else:
                shown = value
                source = "Compose の値。${VAR:-既定} は変換時に埋まっています"
            rows.append(
                EnvRow(
                    service=svc.name,
                    key=key,
                    value=shown,
                    source=source,
                    meaning=explain_ja.meaning_of_env(key, note),
                    file_note=note,
                )
            )
    return rows


def _build_rows(services: list[Service], extras, project_dir: Path):
    from compose_to_docker.model import BuildRow

    rows = []
    ignore = parse_dockerignore(project_dir / ".dockerignore")
    if ignore:
        shown = [line.strip() for line in ignore if line.strip() and not line.strip().startswith("#")]
        rows.append(BuildRow("プロジェクト", ".dockerignore", "ビルドの段ボールに入れないもの: " + ", ".join(shown)))
    for image, dockerfile, context, facts, reason in extras:
        rows.append(BuildRow(image, _rel(dockerfile, project_dir), reason + _fact_text(facts)))
    for svc in services:
        if not svc.facts:
            continue
        rows.append(BuildRow(svc.name, _rel(Path(svc.build.dockerfile), project_dir) if svc.build else "", _fact_text(svc.facts)))
    note = _entrypoint_note(project_dir)
    if note:
        rows.append(BuildRow("起動スクリプト", note[0], note[1]))
    return rows


def _entrypoint_note(project_dir: Path) -> tuple[str, str] | None:
    skip = {".git", "vendor", "dist", "node_modules"}
    for path in project_dir.rglob("*.sh"):
        if any(part in skip for part in path.parts):
            continue
        try:
            if path.stat().st_size > 1_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "readonlyRootFilesystem" in text and "tmpfs" in text:
            rel = path.relative_to(project_dir).as_posix()
            return (
                rel,
                "このスクリプトに、読み取り専用ルートでは作業領域を tmpfs など書き込める場所にする、と書かれています。"
                "起動時の設定適用で数十秒かかるため、ヘルスチェックは直後には成功しない想定です。"
                "だから docker run は --read-only と --tmpfs を両方付け、start_period を残します。",
            )
    return None


def _fact_text(facts: DockerfileFacts | None) -> str:
    if facts is None:
        return ""
    bits = []
    if facts.from_images:
        shown = []
        for image in facts.from_images:
            if image in facts.stages:
                shown.append(image + "（このファイルの中の前の段）")
            else:
                shown.append(image)
        bits.append("FROM " + " -> ".join(shown))
    if facts.entrypoint:
        bits.append("ENTRYPOINT " + facts.entrypoint)
    if facts.cmd:
        bits.append("CMD " + facts.cmd)
    if facts.user:
        bits.append("USER " + facts.user)
    if facts.workdir:
        bits.append("WORKDIR " + facts.workdir)
    if facts.exposes:
        bits.append("EXPOSE " + ",".join(facts.exposes))
    if facts.healthcheck:
        bits.append("イメージ側の " + facts.healthcheck + " 。Compose の healthcheck がある場合は、実行時フラグが上書きします。")
    if facts.missing_sources:
        bits.append("未配置の COPY: " + "、".join(facts.missing_sources))
    if facts.ignored_sources:
        bits.append(".dockerignore に一致: " + "、".join(facts.ignored_sources))
    if facts.notes:
        bits.append(" ".join(facts.notes))
    return "。".join(bits)


def _mappings(project, services, networks, volumes, selinux):
    from compose_to_docker.model import MappingRow

    rows = [
        MappingRow("name", project, "ネットワークとボリュームの接頭辞に使います。コンテナ名は container_name が優先です。"),
        MappingRow("networks.<名前>", "docker network create <プロジェクト>_<名前>", "接頭辞とのあいだはアンダースコアです。コンテナの自動名のハイフンとは歴史が違います。"),
        MappingRow("volumes.<名前>", "docker volume create <プロジェクト>_<名前>", "コンテナを rm しても残します。停止手順では消しません。"),
        MappingRow("services.<名前>.image", "docker pull または docker run のイメージ名", "build が無いときだけ、手元に無ければ pull します。"),
        MappingRow("services.<名前>.build", "docker build --file ... コンテキスト", "コンテキストは Compose ファイルからの相対です。作業ディレクトリからではありません。"),
        MappingRow("build.args", "--build-arg", "レシピの ARG を上書きします。"),
        MappingRow("build.secrets", "--secret", "BuildKit のビルド中だけ見える秘密です。層には残りません。"),
        MappingRow("container_name", "--name", "台帳の名前です。DNS 名ではありません。"),
        MappingRow("networks とサービス名", "--network と --network-alias", "Compose が自動で付けるサービス名の名札を、明示的に付けます。"),
        MappingRow("ports", "--publish", "ホストの扉とコンテナの扉をつなぎます。"),
        MappingRow("expose", "--expose", "記録だけです。ホストへは開きません。"),
        MappingRow("volumes のバインド", f"--volume 元:先:ro,{selinux}" if selinux else "--volume 元:先", "RHEL では SELinux ラベルのため --volume を使います。現行ドキュメントでは --mount では z を付けられません。"),
        MappingRow("volumes の名前付き", "--volume ボリューム名:先", "Docker が管理するロッカーです。"),
        MappingRow("tmpfs", "--tmpfs", "メモリ上の消える作業場所です。"),
        MappingRow("read_only", "--read-only", "ルートを封印します。書けるのは tmpfs とマウントだけです。"),
        MappingRow("environment", "--env KEY=VALUE", "変換時に補間した値を、単一引用符で渡します。"),
        MappingRow("healthcheck.test の CMD", "--health-cmd", "CLI は sh -c で実行します。終了コード 0 が成功です。"),
        MappingRow("healthcheck の時間と回数", "--health-interval など", "イメージの HEALTHCHECK より、Compose の値が優先です。"),
        MappingRow("depends_on: service_healthy", "wait_healthy", "Engine に依存待機は無いので、inspect で状態を見る関数にします。"),
        MappingRow("depends_on: service_started", "wait_running", "プロセスが動いたことだけを見ます。"),
        MappingRow("command", "イメージ名の後ろの引数", "ENTRYPOINT は残し、CMD だけを差し替えます。"),
        MappingRow("profiles", "（既定では出力しない）", "通常の docker compose up と同じく、指定したプロファイルだけを含めます。"),
        MappingRow("Compose が付ける com.docker.compose.* ラベル", "付けない", "アプリの動作には不要なので、命令を短くするために省いています。"),
    ]
    return rows


def _prerequisite_images(services: list[Service], project_dir: Path):
    produced = {svc.image for svc in services}
    owners: dict[str, list[str]] = {}
    for svc in services:
        if not svc.facts:
            continue
        for image in svc.facts.from_images:
            if _is_registry_image(image) or image in produced or image == "scratch":
                continue
            owners.setdefault(image, [])
            if svc.name not in owners[image]:
                owners[image].append(svc.name)
    if not owners:
        return []
    skip = {".git", "vendor", "dist", "node_modules", "target"}
    files: list[Path] = []
    for pattern in ("Dockerfile", "Containerfile"):
        for path in project_dir.rglob(pattern):
            if any(part in skip for part in path.parts):
                continue
            files.append(path)
    used = {Path(svc.build.dockerfile).resolve() for svc in services if svc.build}
    unused = [path for path in files if path.resolve() not in used]
    extras = []
    claimed = set()
    for image, owner_names in owners.items():
        owner = "、".join(owner_names)
        if image in claimed:
            continue
        repo = image.split("@", 1)[0]
        if ":" in repo.split("/")[-1]:
            repo = repo.rsplit(":", 1)[0]
        best = None
        best_score = 0
        for path in unused:
            score = 0
            for part in path.parts:
                if part.lower() in {"dockerfile", "containerfile"}:
                    continue
                if part and part.lower() in repo.lower():
                    score += 3
            if score > best_score:
                best = path
                best_score = score
        if best is None or best_score <= 0:
            continue
        context = _best_context(best, project_dir)
        facts = inspect_dockerfile(best, context, {})
        extras.append((image, best, context, facts, f"{owner} が FROM {image} しているため、サービス定義の外にある {best.name} を先に焼きます。"))
        claimed.add(image)
    return extras


def _best_context(dockerfile: Path, project_dir: Path) -> Path:
    candidates = [project_dir]
    if dockerfile.parent != project_dir:
        candidates.append(dockerfile.parent)
    best = project_dir
    best_score = -10**9
    for ctx in candidates:
        facts = inspect_dockerfile(dockerfile, ctx, {})
        score = len(facts.copy_sources) - 3 * len(facts.missing_sources)
        if score > best_score:
            best = ctx
            best_score = score
    return best


def _group_builds(services: list[Service]) -> list[list[Service]]:
    groups: list[list[Service]] = []
    seen: dict[tuple, int] = {}
    for svc in services:
        if not svc.build:
            continue
        ident = (
            svc.build.context,
            svc.build.dockerfile,
            tuple(sorted(svc.build.args.items())),
            svc.build.target,
            tuple((item.ident, item.kind, item.value) for item in svc.build.secrets),
        )
        if ident in seen:
            groups[seen[ident]].append(svc)
        else:
            seen[ident] = len(groups)
            groups.append([svc])
    return groups


def _is_registry_image(image: str) -> bool:
    name = image.split("@", 1)[0]
    if ":" in name.split("/")[-1]:
        name = name.rsplit(":", 1)[0]
    if "/" not in name:
        return False
    first = name.split("/", 1)[0]
    return "." in first or ":" in first or first == "localhost"


def _health_shell(health: Healthcheck) -> str:
    test = health.test
    if not test or test[0] == "NONE":
        return ""
    if test[0] == "CMD-SHELL":
        return " ".join(test[1:])
    if test[0] == "CMD":
        return " ".join(test[1:])
    return " ".join(test)


def _health_budget(health: Healthcheck | None) -> int:
    if health is None or health.disable:
        return 90
    start = _seconds(health.start_period or "0s")
    interval = _seconds(health.interval or "30s")
    retries = health.retries if health.retries is not None else 3
    return int(start + retries * interval + 30)


def _seconds(text: str) -> int:
    if text.isdigit():
        return int(text)
    total = 0
    for amount, unit in re.findall(r"(\d+)(ms|s|m|h)", text):
        number = int(amount)
        total += {"ms": 1, "s": number, "m": number * 60, "h": number * 3600}[unit]
    return total or 30


def _last_env(items: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
    order: list[str] = []
    values: dict[str, str | None] = {}
    for key, value in items:
        if key not in values:
            order.append(key)
        values[key] = value
    return [(key, values[key]) for key in order]


def _volume_arg(mnt, project_dir: Path) -> str:
    opts = []
    if mnt.read_only:
        opts.append("ro")
    if mnt.selinux in {"z", "Z"} and mnt.kind == "bind":
        opts.append(mnt.selinux)
    suffix = (":" + ",".join(opts)) if opts else ""
    if mnt.kind == "bind":
        rel = _try_rel(mnt.source, project_dir)
        source = ("${PROJECT_ROOT}/" + rel) if rel is not None else mnt.source
        return '"' + source + ":" + mnt.target + suffix + '"'
    if mnt.anonymous:
        return shell_quote(mnt.target)
    return '"' + mnt.source + ":" + mnt.target + suffix + '"'


def _missing_checks(facts: DockerfileFacts | None, context_rel: str) -> str:
    if not facts or not facts.missing_sources:
        return ""
    lines = ["  missing=0"]
    for src in facts.missing_sources:
        rel = _join(context_rel, src)
        lines.append(f'  if [ ! -e {_bash_project(rel)} ]; then')
        lines.append(f'    echo {shell_quote("ビルドに必要なファイルがありません: " + rel)} >&2')
        lines.append('    missing=1')
        lines.append("  fi")
    lines.append('  if [ "$missing" -ne 0 ]; then')
    lines.append('    echo "材料を置くか、イメージを別の方法で用意してから、もう一度実行してください。" >&2')
    lines.append("    exit 1")
    lines.append("  fi")
    return "\n".join(lines) + "\n"


def _rel(path: Path, project_dir: Path) -> str:
    try:
        rel = path.resolve().relative_to(project_dir.resolve()).as_posix()
    except ValueError:
        return str(path)
    return "." if rel == "." else rel


def _try_rel(source: str, project_dir: Path) -> str | None:
    try:
        return Path(source).resolve().relative_to(project_dir.resolve()).as_posix()
    except (ValueError, OSError):
        return None


def _join(context_rel: str, child: str) -> str:
    ctx = context_rel.replace("\\", "/").strip()
    if ctx in {"", "."}:
        ctx = ""
    else:
        ctx = ctx.removeprefix("./").strip("/")
    child = child.replace("\\", "/").lstrip("/")
    return f"{ctx}/{child}" if ctx else child


def _bash_project(rel: str) -> str:
    rel = rel.replace("\\", "/").strip()
    if rel in {"", "."}:
        return '"${PROJECT_ROOT}"'
    return '"${PROJECT_ROOT}/' + rel.removeprefix("./") + '"'


def _continued(head: str, parts: list[str]) -> str:
    if not parts:
        return head
    return head + " \\\n  " + " \\\n  ".join(parts)


def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line else "" for line in text.split("\n"))
