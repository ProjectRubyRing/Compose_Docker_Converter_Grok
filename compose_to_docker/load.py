"""Compose ファイルを読み、サービス・ネットワーク・ボリュームへ正規化する。"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from compose_to_docker.dockerfile import inspect_dockerfile
from compose_to_docker.interpolate import interpolate_obj
from compose_to_docker.model import (
    BuildSecret,
    BuildSpec,
    Depends,
    DockerfileFacts,
    Healthcheck,
    NamedNetwork,
    NamedVolume,
    NetworkAttachment,
    Service,
    VolumeMount,
)

KNOWN_SERVICE_KEYS = {
    "annotations",
    "build",
    "cap_add",
    "cap_drop",
    "cgroup",
    "cgroup_parent",
    "command",
    "configs",
    "container_name",
    "depends_on",
    "deploy",
    "devices",
    "device_cgroup_rules",
    "dns",
    "dns_opt",
    "dns_search",
    "domainname",
    "entrypoint",
    "env_file",
    "environment",
    "expose",
    "extends",
    "extra_hosts",
    "group_add",
    "healthcheck",
    "hostname",
    "image",
    "init",
    "ipc",
    "labels",
    "logging",
    "mac_address",
    "mem_limit",
    "mem_reservation",
    "memswap_limit",
    "network_mode",
    "networks",
    "pid",
    "platform",
    "ports",
    "privileged",
    "profiles",
    "pull_policy",
    "read_only",
    "restart",
    "runtime",
    "secrets",
    "security_opt",
    "shm_size",
    "stdin_open",
    "stop_grace_period",
    "stop_signal",
    "sysctls",
    "tmpfs",
    "tty",
    "ulimits",
    "user",
    "userns_mode",
    "volumes",
    "volumes_from",
    "working_dir",
    "cpus",
    "cpu_shares",
    "pids_limit",
    "oom_kill_disable",
    "oom_score_adj",
    "cpuset",
}


class ComposeError(ValueError):
    pass


class Reset:
    pass


class OverrideList(list):
    pass


class OverrideDict(dict):
    pass


def _loader() -> type[yaml.SafeLoader]:
    class Loader(yaml.SafeLoader):
        pass

    def reset_tag(loader: yaml.SafeLoader, node: yaml.Node):
        return Reset()

    def override_tag(loader: yaml.SafeLoader, node: yaml.Node):
        if isinstance(node, yaml.SequenceNode):
            return OverrideList(loader.construct_sequence(node, deep=True))
        if isinstance(node, yaml.MappingNode):
            return OverrideDict(loader.construct_mapping(node, deep=True))
        return loader.construct_scalar(node)

    Loader.add_constructor("!reset", reset_tag)
    Loader.add_constructor("!override", override_tag)
    return Loader


def load_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def harvest_comments(text: str) -> tuple[dict[str, str], dict[str, str]]:
    """環境変数名とサービス名に、直上のコメントを結び付ける。"""
    env_notes: dict[str, str] = {}
    service_notes: dict[str, str] = {}
    buf: list[str] = []
    in_services = False
    for raw in text.splitlines():
        if not raw.strip():
            buf = []
            continue
        if raw.lstrip().startswith("#"):
            buf.append(raw.lstrip()[1:].strip())
            continue
        if re.match(r"^services:\s*$", raw):
            in_services = True
            buf = []
            continue
        service_match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", raw) if in_services else None
        if service_match and buf:
            note = _clean_comment(buf)
            if note:
                service_notes[service_match.group(1)] = note
            buf = []
            continue
        key_match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", raw)
        if key_match and buf:
            key = key_match.group(1)
            note = _clean_comment(buf)
            if note and len(note) > len(env_notes.get(key, "")):
                env_notes[key] = note
        buf = []
    return env_notes, service_notes


def _clean_comment(lines: list[str]) -> str:
    kept = []
    for line in lines:
        if re.fullmatch(r"[-=*#\s]+", line or ""):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def build_environment(
    compose_dir: Path,
    env_files: list[Path],
    use_shell_env: bool,
) -> dict[str, str]:
    merged: dict[str, str] = {}
    default_env = compose_dir / ".env"
    explicit = [path.resolve() for path in env_files]
    if default_env.resolve() not in explicit and default_env.is_file():
        merged.update(load_env_file(default_env))
    for path in env_files:
        merged.update(load_env_file(path))
    if use_shell_env:
        merged.update({key: value for key, value in os.environ.items()})
    return merged


def load_compose(
    path: Path,
    *,
    env_files: list[Path] | None = None,
    use_shell_env: bool = False,
    profiles: set[str] | None = None,
    selinux: str = "z",
) -> tuple[str, list[Service], list[NamedNetwork], list[NamedVolume], list[str], dict[str, str], dict[str, str]]:
    path = path.resolve()
    if not path.is_file():
        raise ComposeError(f"Compose ファイルがありません: {path}")
    raw_text = path.read_text(encoding="utf-8", errors="replace")
    env_notes, service_notes = harvest_comments(raw_text)
    try:
        loaded = yaml.load(raw_text, Loader=_loader())
    except yaml.YAMLError as exc:
        raise ComposeError(f"YAML を読めません: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ComposeError("Compose ファイルの先頭はマッピングである必要があります。")
    warnings: list[str] = []
    env = build_environment(path.parent, list(env_files or []), use_shell_env)
    data = interpolate_obj(loaded, env, origin=path.name)
    if not isinstance(data, dict):
        raise ComposeError("補間後の Compose ファイルがマッピングではありません。")

    project = str(data.get("name") or sanitize_project_name(path.parent.name))
    project = sanitize_project_name(project)
    services_raw = data.get("services") or {}
    if not isinstance(services_raw, dict) or not services_raw:
        raise ComposeError("services が空です。")

    file_cache: dict[Path, dict] = {path: data}
    selected: list[tuple[str, dict]] = []
    skipped: list[str] = []
    wanted = profiles or set()
    for name, body in services_raw.items():
        if not isinstance(body, dict):
            raise ComposeError(f"サービス {name} の定義がマッピングではありません。")
        resolved = _resolve_extends(body, path, file_cache, env, [])
        service_profiles = _as_str_list(resolved.get("profiles"))
        if service_profiles and not (set(service_profiles) & wanted):
            skipped.append(f"{name}（profile: {', '.join(service_profiles)}）")
            continue
        selected.append((str(name), resolved))

    networks = _networks(data.get("networks") or {}, project, warnings)
    volumes = _volumes(data.get("volumes") or {}, project, warnings)
    network_by_key = {item.key: item for item in networks}
    volume_by_key = {item.key: item for item in volumes}
    secrets = data.get("secrets") or {}
    configs = data.get("configs") or {}
    if not isinstance(secrets, dict):
        secrets = {}
    if not isinstance(configs, dict):
        configs = {}

    services: list[Service] = []
    for name, body in selected:
        services.append(
            _service(
                name,
                body,
                project,
                path.parent,
                network_by_key,
                volume_by_key,
                secrets,
                configs,
                selinux,
                service_notes.get(name, ""),
                warnings,
            )
        )
    if skipped:
        warnings.append(
            "通常の起動に含めないプロファイル付きサービス: " + "、".join(skipped)
        )
    return project, services, networks, volumes, warnings, env_notes, service_notes


def sanitize_project_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", name).lower()
    cleaned = cleaned.strip("_-")
    if not cleaned:
        return "compose"
    if not re.match(r"^[a-z0-9]", cleaned):
        cleaned = "p" + cleaned
    return cleaned


def _resolve_extends(body: dict, current: Path, cache: dict[Path, dict], env: dict[str, str], stack: list[str]) -> dict:
    extends = body.get("extends")
    if not extends:
        return body
    if isinstance(extends, str):
        file_path = current
        service_name = extends
    elif isinstance(extends, dict):
        service_name = str(extends.get("service") or "")
        file_path = current
        if extends.get("file"):
            file_path = (current.parent / str(extends["file"])).resolve()
    else:
        raise ComposeError("extends の形が不正です。")
    if not service_name:
        raise ComposeError("extends.service が空です。")
    marker = f"{file_path}:{service_name}"
    if marker in stack:
        raise ComposeError(f"extends が循環しています: {marker}")
    document = cache.get(file_path)
    if document is None:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        loaded = yaml.load(text, Loader=_loader())
        document = interpolate_obj(loaded, env, origin=file_path.name)
        cache[file_path] = document
    base = ((document or {}).get("services") or {}).get(service_name)
    if not isinstance(base, dict):
        raise ComposeError(f"extends の参照先がありません: {marker}")
    base = _resolve_extends(dict(base), file_path, cache, env, stack + [marker])
    child = dict(body)
    child.pop("extends", None)
    return _merge_service(base, child)


def _merge_service(base: dict, child: dict) -> dict:
    merged = dict(base)
    for key, value in child.items():
        if isinstance(value, Reset):
            merged.pop(key, None)
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict) and not isinstance(value, OverrideDict):
            merged[key] = {**merged[key], **value}
            continue
        merged[key] = value
    return merged


def _networks(raw, project: str, warnings: list[str]) -> list[NamedNetwork]:
    if raw in (None, {}):
        return [NamedNetwork(key="default", docker_name=f"{project}_default", driver="bridge")]
    if not isinstance(raw, dict):
        raise ComposeError("networks がマッピングではありません。")
    items: list[NamedNetwork] = []
    for key, body in raw.items():
        body = body or {}
        if not isinstance(body, dict):
            raise ComposeError(f"network {key} がマッピングではありません。")
        external = bool(body.get("external"))
        docker_name = str(body.get("name") or key if external else body.get("name") or f"{project}_{key}")
        ipam = body.get("ipam") or {}
        config = (ipam.get("config") or [{}])[0] if isinstance(ipam, dict) else {}
        if not isinstance(config, dict):
            config = {}
        driver = str(body.get("driver") or ("bridge" if not external else ""))
        items.append(
            NamedNetwork(
                key=str(key),
                docker_name=docker_name,
                driver=driver,
                external=external,
                internal=bool(body.get("internal")),
                attachable=bool(body.get("attachable")),
                enable_ipv6=bool(body.get("enable_ipv6")),
                subnet=str(config.get("subnet") or ""),
                gateway=str(config.get("gateway") or ""),
                driver_opts=[f"{k}={v}" for k, v in (body.get("driver_opts") or {}).items()]
                if isinstance(body.get("driver_opts"), dict)
                else [],
            )
        )
    return items


def _volumes(raw, project: str, warnings: list[str]) -> list[NamedVolume]:
    if not isinstance(raw, dict):
        if raw:
            warnings.append("volumes のトップレベルを解釈できません。")
        return []
    items: list[NamedVolume] = []
    for key, body in raw.items():
        body = body or {}
        if not isinstance(body, dict):
            raise ComposeError(f"volume {key} がマッピングではありません。")
        external = bool(body.get("external"))
        docker_name = str(body.get("name") or key if external else body.get("name") or f"{project}_{key}")
        opts = body.get("driver_opts") or {}
        items.append(
            NamedVolume(
                key=str(key),
                docker_name=docker_name,
                external=external,
                driver=str(body.get("driver") or ""),
                driver_opts=[f"{k}={v}" for k, v in opts.items()] if isinstance(opts, dict) else [],
            )
        )
    return items


def _service(
    name: str,
    body: dict,
    project: str,
    project_dir: Path,
    networks: dict[str, NamedNetwork],
    volumes: dict[str, NamedVolume],
    secrets: dict,
    configs: dict,
    selinux: str,
    comment: str,
    warnings: list[str],
) -> Service:
    unknown = sorted(set(body) - KNOWN_SERVICE_KEYS)
    for key in unknown:
        warnings.append(f"サービス {name} のキー {key} はこの変換では使いません。")
    image = str(body.get("image") or "")
    build = _build(body.get("build"), project_dir, secrets, warnings, name)
    if not image and build:
        image = f"{project}-{name}"
    if not image and not build:
        raise ComposeError(f"サービス {name} に image も build もありません。")
    container_name = str(body.get("container_name") or f"{project}-{name}-1")
    replicas = _replicas(body)
    if replicas > 1:
        warnings.append(
            f"サービス {name} の replicas は {replicas} です。公開ポートの競合を避けるため、この変換は 1 台だけ作ります。"
        )
    attachments = _service_networks(body, name, container_name, networks, project, warnings)
    service = Service(
        name=name,
        image=image,
        container_name=container_name,
        build=build,
        hostname=str(body.get("hostname") or ""),
        command=_command(body.get("command"), warnings, name),
        entrypoint=_command(body.get("entrypoint"), warnings, name) if "entrypoint" in body else None,
        environment=_environment(body, project_dir, warnings, name),
        ports=[_port(item) for item in _as_list(body.get("ports"))],
        expose=[str(item) for item in _as_list(body.get("expose"))],
        volumes=_service_volumes(body, project_dir, volumes, selinux, warnings, name),
        tmpfs=_tmpfs(body.get("tmpfs")),
        networks=attachments,
        network_mode=str(body.get("network_mode") or ""),
        depends_on=_depends(body.get("depends_on")),
        healthcheck=_health(body.get("healthcheck")),
        restart=_restart(body),
        read_only=bool(body.get("read_only")),
        user=str(body.get("user") or ""),
        working_dir=str(body.get("working_dir") or ""),
        extra_hosts=_extra_hosts(body.get("extra_hosts")),
        cap_add=_as_str_list(body.get("cap_add")),
        cap_drop=_as_str_list(body.get("cap_drop")),
        security_opt=_as_str_list(body.get("security_opt")),
        devices=_as_str_list(body.get("devices")),
        privileged=bool(body.get("privileged")),
        init=body.get("init") if isinstance(body.get("init"), bool) else None,
        ulimits=_ulimits(body.get("ulimits")),
        memory=str(body.get("mem_limit") or _deploy_limit(body, "memory")),
        memory_reservation=str(body.get("mem_reservation") or _deploy_reservation(body, "memory")),
        cpus=str(body.get("cpus") or _deploy_limit(body, "cpus")),
        pids_limit=str(body.get("pids_limit") or ""),
        shm_size=str(body.get("shm_size") or ""),
        stop_timeout=_duration_seconds(body.get("stop_grace_period")),
        stop_signal=str(body.get("stop_signal") or ""),
        stdin_open=bool(body.get("stdin_open")),
        tty=bool(body.get("tty")),
        profiles=_as_str_list(body.get("profiles")),
        pull_policy=str(body.get("pull_policy") or ""),
        platform=str(body.get("platform") or ""),
        pid_mode=str(body.get("pid") or ""),
        ipc_mode=str(body.get("ipc") or ""),
        gpus=_gpus(body),
        volumes_from=_as_str_list(body.get("volumes_from")),
        sysctls=_sysctls(body.get("sysctls")),
        labels=_labels(body.get("labels")),
        replicas=replicas,
        comments=comment,
        warnings=[],
    )
    _apply_secrets_and_configs(service, body, project_dir, secrets, configs, selinux)
    logging = body.get("logging") or {}
    if isinstance(logging, dict) and logging:
        service.log_driver = str(logging.get("driver") or "")
        options = logging.get("options") or {}
        if isinstance(options, dict):
            service.log_options = [f"{key}={value}" for key, value in options.items()]
    service.dns = _as_str_list(body.get("dns"))
    service.dns_search = _as_str_list(body.get("dns_search"))
    service.group_add = _as_str_list(body.get("group_add"))
    if build:
        facts = inspect_dockerfile(Path(build.dockerfile), Path(build.context), build.args)
        service.facts = facts
        for missing in facts.missing_sources:
            warnings.append(f"{name} のビルドに必要なファイルが、コンテキストにありません: {missing}")
        for ignored in facts.ignored_sources:
            warnings.append(f"{name} の COPY 対象は .dockerignore に一致します: {ignored}")
    else:
        service.facts = None
    return service


def _build(raw, project_dir: Path, secrets: dict, warnings: list[str], service: str) -> BuildSpec | None:
    if not raw:
        return None
    if isinstance(raw, str):
        raw = {"context": raw}
    if not isinstance(raw, dict):
        raise ComposeError(f"{service} の build が不正です。")
    context_rel = str(raw.get("context") or ".")
    context = (project_dir / context_rel).resolve()
    dockerfile_rel = str(raw.get("dockerfile") or "Dockerfile")
    dockerfile = (context / dockerfile_rel).resolve() if not Path(dockerfile_rel).is_absolute() else Path(dockerfile_rel)
    # dockerfile が context からの相対であるのが Compose の規則。
    if not Path(str(raw.get("dockerfile") or "Dockerfile")).is_absolute():
        dockerfile = (context / dockerfile_rel).resolve()
    args_raw = raw.get("args") or {}
    args: dict[str, str] = {}
    if isinstance(args_raw, list):
        for item in args_raw:
            text = str(item)
            if "=" in text:
                key, value = text.split("=", 1)
                args[key] = value
            else:
                args[text] = os.environ.get(text, "")
    elif isinstance(args_raw, dict):
        args = {str(key): "" if value is None else str(value) for key, value in args_raw.items()}
    build_secrets: list[BuildSecret] = []
    for item in _as_list(raw.get("secrets")):
        if isinstance(item, str):
            source = item
            ident = item
        elif isinstance(item, dict):
            source = str(item.get("source") or item.get("id") or "")
            ident = str(item.get("id") or source)
        else:
            continue
        spec = secrets.get(source) or {}
        if isinstance(spec, dict) and "environment" in spec:
            build_secrets.append(BuildSecret(ident=ident, kind="env", value=str(spec.get("environment"))))
        elif isinstance(spec, dict) and "file" in spec:
            build_secrets.append(BuildSecret(ident=ident, kind="file", value=_host_file(str(spec.get("file")), project_dir)))
        else:
            warnings.append(f"{service} のビルドシークレット {source} の定義がありません。")
    platforms = []
    if raw.get("platforms"):
        platforms = _as_str_list(raw.get("platforms"))
    elif raw.get("platform"):
        platforms = [str(raw.get("platform"))]
    cache_from = []
    for item in _as_list(raw.get("cache_from")):
        cache_from.append(str(item))
    return BuildSpec(
        context=str(context),
        context_rel=context_rel,
        dockerfile=str(dockerfile),
        dockerfile_rel=dockerfile_rel,
        args=args,
        target=str(raw.get("target") or ""),
        secrets=build_secrets,
        platforms=platforms,
        network=str(raw.get("network") or ""),
        cache_from=cache_from,
    )


def _environment(body: dict, project_dir: Path, warnings: list[str], service: str) -> list[tuple[str, str | None]]:
    values: list[tuple[str, str | None]] = []
    for item in _as_list(body.get("env_file")):
        file_path = item.get("path") if isinstance(item, dict) else item
        path = project_dir / str(file_path)
        if not path.is_file():
            warnings.append(f"{service} の env_file がありません: {file_path}")
            continue
        for key, value in load_env_file(path).items():
            values.append((key, value))
    raw = body.get("environment")
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, Reset) or value is None:
                values.append((str(key), None))
            else:
                values.append((str(key), str(value)))
    elif isinstance(raw, list):
        for item in raw:
            text = str(item)
            if "=" not in text:
                values.append((text, None))
            else:
                key, value = text.split("=", 1)
                values.append((key, value))
    return values


def _depends(raw) -> list[Depends]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [Depends(name=str(item), condition="service_started") for item in raw]
    if isinstance(raw, dict):
        items = []
        for name, body in raw.items():
            condition = "service_started"
            if isinstance(body, dict) and body.get("condition"):
                condition = str(body["condition"])
            items.append(Depends(name=str(name), condition=condition))
        return items
    return []


def _health(raw) -> Healthcheck | None:
    if not raw:
        return None
    if not isinstance(raw, dict):
        return None
    test = raw.get("test")
    parsed: list[str] = []
    if isinstance(test, str):
        parsed = ["CMD-SHELL", test]
    elif isinstance(test, list):
        parsed = [str(item) for item in test]
    disable = bool(raw.get("disable")) or (parsed[:1] == ["NONE"])
    return Healthcheck(
        disable=disable,
        test=parsed,
        interval=str(raw.get("interval") or ""),
        timeout=str(raw.get("timeout") or ""),
        retries=int(raw["retries"]) if raw.get("retries") not in (None, "") else None,
        start_period=str(raw.get("start_period") or ""),
        start_interval=str(raw.get("start_interval") or ""),
    )


def _command(raw, warnings: list[str], service: str) -> list[str] | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if isinstance(raw, str):
        warnings.append(
            f"{service} の command/entrypoint は文字列です。Compose と同様に /bin/sh -c で実行する形へ寄せます。"
        )
        return ["/bin/sh", "-c", raw]
    return None


def _service_networks(body, service: str, container_name: str, networks: dict[str, NamedNetwork], project: str, warnings: list[str]) -> list[NetworkAttachment]:
    raw = body.get("networks")
    if raw is None:
        if "default" not in networks:
            networks["default"] = NamedNetwork(key="default", docker_name=f"{project}_default")
        raw = ["default"]
    attachments: list[NetworkAttachment] = []
    if isinstance(raw, list):
        pairs = [(str(item), {}) for item in raw]
    elif isinstance(raw, dict):
        pairs = []
        for key, value in raw.items():
            pairs.append((str(key), value or {}))
    else:
        warnings.append(f"{service} の networks を解釈できません。")
        return []
    for key, spec in pairs:
        if key not in networks:
            networks[key] = NamedNetwork(key=key, docker_name=f"{project}_{key}")
            warnings.append(f"{service} が参照するネットワーク {key} の定義が無いので、bridge として作ります。")
        net = networks[key]
        aliases = [service]
        ipv4 = ""
        ipv6 = ""
        if isinstance(spec, dict):
            aliases.extend(_as_str_list(spec.get("aliases")))
            ipv4 = str(spec.get("ipv4_address") or "")
            ipv6 = str(spec.get("ipv6_address") or "")
        deduped = []
        for alias in aliases:
            if alias and alias not in deduped:
                deduped.append(alias)
        attachments.append(
            NetworkAttachment(
                name=key,
                docker_name=net.docker_name,
                aliases=deduped,
                ipv4_address=ipv4,
                ipv6_address=ipv6,
            )
        )
    return attachments


def _service_volumes(body, project_dir: Path, volumes: dict[str, NamedVolume], selinux: str, warnings: list[str], service: str) -> list[VolumeMount]:
    mounts: list[VolumeMount] = []
    for item in _as_list(body.get("volumes")):
        mounts.append(_one_volume(item, project_dir, volumes, selinux, warnings, service))
    return [item for item in mounts if item is not None]


def _one_volume(item, project_dir: Path, volumes: dict[str, NamedVolume], selinux: str, warnings: list[str], service: str) -> VolumeMount | None:
    if isinstance(item, str):
        return _short_volume(item, project_dir, volumes, selinux)
    if not isinstance(item, dict):
        warnings.append(f"{service} の volume 項目を飛ばしました。")
        return None
    kind = str(item.get("type") or "volume")
    target = str(item.get("target") or "")
    source = str(item.get("source") or "")
    read_only = bool(item.get("read_only"))
    label = ""
    if kind == "bind":
        bind = item.get("bind") or {}
        label = str(bind.get("selinux") or "") if isinstance(bind, dict) else ""
        if not label and selinux in {"z", "Z"}:
            label = selinux
        host = source if Path(source).is_absolute() else str((project_dir / source).resolve())
        return VolumeMount(kind="bind", source=host, target=target, read_only=read_only, selinux=label)
    if kind == "tmpfs":
        return VolumeMount(kind="tmpfs", source="", target=target)
    if kind == "volume":
        if not source:
            return VolumeMount(kind="volume", source="", target=target, read_only=read_only, anonymous=True)
        named = volumes.get(source)
        docker_name = named.docker_name if named else source
        return VolumeMount(kind="volume", source=docker_name, target=target, read_only=read_only)
    warnings.append(f"{service} の volume type={kind} は単純なマウントとして扱います。")
    return None


def _short_volume(text: str, project_dir: Path, volumes: dict[str, NamedVolume], selinux: str) -> VolumeMount:
    parts = text.split(":")
    # Windows のドライブ文字は対象外。RHEL のパスは / から始まる。
    if len(parts) == 1:
        return VolumeMount(kind="volume", source="", target=parts[0], anonymous=True)
    options = ""
    if len(parts) >= 3:
        source, target, options = parts[0], parts[1], ":".join(parts[2:])
    else:
        source, target = parts[0], parts[1]
    read_only = "ro" in options.split(",")
    label = "Z" if "Z" in options.split(",") else ("z" if "z" in options.split(",") else "")
    if source.startswith((".", "/")):
        if not label and selinux in {"z", "Z"}:
            label = selinux
        host = source if source.startswith("/") else str((project_dir / source).resolve())
        return VolumeMount(kind="bind", source=host, target=target, read_only=read_only, selinux=label, options=options)
    named = volumes.get(source)
    docker_name = named.docker_name if named else source
    return VolumeMount(kind="volume", source=docker_name, target=target, read_only=read_only, options=options)


def _tmpfs(raw) -> list[str]:
    items = []
    for entry in _as_list(raw):
        if isinstance(entry, str):
            items.append(entry)
        elif isinstance(entry, dict):
            target = str(entry.get("target") or "")
            opts = entry.get("tmpfs") or {}
            extra = []
            if isinstance(opts, dict):
                if opts.get("size"):
                    extra.append(f"size={opts['size']}")
                if opts.get("mode"):
                    extra.append(f"mode={opts['mode']}")
            items.append(target + (":" + ",".join(extra) if extra else ""))
    return items


def _port(item) -> str:
    if isinstance(item, dict):
        target = str(item.get("target"))
        published = item.get("published")
        host_ip = str(item.get("host_ip") or "")
        protocol = str(item.get("protocol") or "tcp")
        base = f"{target}/{protocol}" if protocol and protocol != "tcp" else str(target)
        if published in (None, ""):
            return base
        published = str(published)
        if host_ip:
            return f"{host_ip}:{published}:{base}"
        return f"{published}:{base}"
    return str(item)


def _extra_hosts(raw) -> list[str]:
    if isinstance(raw, dict):
        return [f"{key}:{value}" for key, value in raw.items()]
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return []


def _ulimits(raw) -> list[str]:
    if not isinstance(raw, dict):
        return []
    items = []
    for key, value in raw.items():
        if isinstance(value, dict):
            items.append(f"{key}={value.get('soft')}:{value.get('hard')}")
        else:
            items.append(f"{key}={value}")
    return items


def _sysctls(raw) -> list[str]:
    if isinstance(raw, dict):
        return [f"{key}={value}" for key, value in raw.items()]
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return []


def _labels(raw) -> list[str]:
    if isinstance(raw, dict):
        return [f"{key}={value}" for key, value in raw.items()]
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return []


def _restart(body: dict) -> str:
    if body.get("restart"):
        return str(body["restart"])
    deploy = body.get("deploy") or {}
    policy = deploy.get("restart_policy") if isinstance(deploy, dict) else None
    if isinstance(policy, dict) and policy.get("condition"):
        condition = str(policy["condition"])
        return {"any": "always", "on-failure": "on-failure", "none": "no"}.get(condition, condition)
    return ""


def _replicas(body: dict) -> int:
    deploy = body.get("deploy") or {}
    if isinstance(deploy, dict) and deploy.get("replicas"):
        return int(deploy["replicas"])
    return 1


def _deploy_limit(body: dict, key: str) -> str:
    deploy = body.get("deploy") or {}
    if not isinstance(deploy, dict):
        return ""
    limits = ((deploy.get("resources") or {}).get("limits") or {}) if isinstance(deploy.get("resources"), dict) else {}
    if isinstance(limits, dict) and limits.get(key) is not None:
        return str(limits[key])
    return ""


def _deploy_reservation(body: dict, key: str) -> str:
    deploy = body.get("deploy") or {}
    if not isinstance(deploy, dict):
        return ""
    resources = deploy.get("resources") or {}
    reservations = resources.get("reservations") if isinstance(resources, dict) else {}
    if isinstance(reservations, dict) and reservations.get(key) is not None:
        return str(reservations[key])
    return ""


def _gpus(body: dict) -> str:
    deploy = body.get("deploy") or {}
    if not isinstance(deploy, dict):
        return ""
    resources = deploy.get("resources") or {}
    reservations = resources.get("reservations") if isinstance(resources, dict) else {}
    devices = reservations.get("devices") if isinstance(reservations, dict) else None
    if not isinstance(devices, list):
        return ""
    for device in devices:
        caps = device.get("capabilities") if isinstance(device, dict) else None
        if caps and "gpu" in [str(item).lower() for item in caps]:
            count = device.get("count")
            return "all" if count in (None, -1, "all") else str(count)
    return ""


def _apply_secrets_and_configs(service: Service, body: dict, project_dir: Path, secrets: dict, configs: dict, selinux: str) -> None:
    for kind, table, default_dir in (("secret", secrets, "/run/secrets"), ("config", configs, "")):
        for item in _as_list(body.get("secrets" if kind == "secret" else "configs")):
            if isinstance(item, str):
                source = target = item
            elif isinstance(item, dict):
                source = str(item.get("source") or "")
                target = str(item.get("target") or source)
            else:
                continue
            spec = table.get(source) or {}
            if not isinstance(spec, dict) or "file" not in spec:
                continue
            host = _host_file(str(spec["file"]), project_dir)
            if kind == "secret":
                container_target = target if target.startswith("/") else f"{default_dir}/{target}"
            else:
                container_target = target if target.startswith("/") else f"/{target}"
            service.volumes.append(
                VolumeMount(
                    kind="bind",
                    source=host,
                    target=container_target,
                    read_only=True,
                    selinux=selinux if selinux in {"z", "Z"} else "",
                )
            )


def _duration_seconds(raw) -> str:
    if raw in (None, ""):
        return ""
    text = str(raw).strip()
    if text.isdigit():
        return text
    total = 0
    found = False
    for amount, unit in re.findall(r"(\d+)(ms|s|m|h)", text):
        found = True
        number = int(amount)
        if unit == "ms":
            total += 1 if number else 0
        elif unit == "s":
            total += number
        elif unit == "m":
            total += number * 60
        elif unit == "h":
            total += number * 3600
    return str(total) if found else text


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_str_list(value) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _host_file(file_path: str, project_dir: Path) -> str:
    """RHEL で意味を持つ絶対パスは、変換した Windows のパスへ潰さない。"""
    if file_path.startswith("/"):
        return file_path.replace("\\", "/")
    return str((project_dir / file_path).resolve())
