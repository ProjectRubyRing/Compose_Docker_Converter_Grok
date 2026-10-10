"""変換の途中と結果で共有するデータ。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Depends:
    name: str
    condition: str  # service_started | service_healthy | service_completed_successfully


@dataclass
class VolumeMount:
    kind: str  # volume | bind | tmpfs
    source: str
    target: str
    read_only: bool = False
    selinux: str = ""  # z, Z, or empty
    options: str = ""
    anonymous: bool = False
    external_name: str = ""


@dataclass
class NetworkAttachment:
    name: str  # compose 上のキー
    docker_name: str
    aliases: list[str] = field(default_factory=list)
    ipv4_address: str = ""
    ipv6_address: str = ""


@dataclass
class Healthcheck:
    disable: bool = False
    test: list[str] = field(default_factory=list)
    interval: str = ""
    timeout: str = ""
    retries: int | None = None
    start_period: str = ""
    start_interval: str = ""


@dataclass
class BuildSecret:
    ident: str
    kind: str  # env | file
    value: str  # env var name or host file path


@dataclass
class BuildSpec:
    context: str
    context_rel: str
    dockerfile: str
    dockerfile_rel: str
    args: dict[str, str] = field(default_factory=dict)
    target: str = ""
    secrets: list[BuildSecret] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    network: str = ""
    cache_from: list[str] = field(default_factory=list)


@dataclass
class DockerfileFacts:
    path: str
    from_images: list[str] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)
    exposes: list[str] = field(default_factory=list)
    entrypoint: str = ""
    cmd: str = ""
    user: str = ""
    workdir: str = ""
    healthcheck: str = ""
    copy_sources: list[str] = field(default_factory=list)
    missing_sources: list[str] = field(default_factory=list)
    ignored_sources: list[str] = field(default_factory=list)
    arg_defaults: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class Service:
    name: str
    image: str
    container_name: str
    build: BuildSpec | None = None
    hostname: str = ""
    command: list[str] | None = None
    entrypoint: list[str] | None = None
    environment: list[tuple[str, str | None]] = field(default_factory=list)
    ports: list[str] = field(default_factory=list)
    expose: list[str] = field(default_factory=list)
    volumes: list[VolumeMount] = field(default_factory=list)
    tmpfs: list[str] = field(default_factory=list)
    networks: list[NetworkAttachment] = field(default_factory=list)
    network_mode: str = ""
    depends_on: list[Depends] = field(default_factory=list)
    healthcheck: Healthcheck | None = None
    restart: str = ""
    read_only: bool = False
    user: str = ""
    working_dir: str = ""
    extra_hosts: list[str] = field(default_factory=list)
    cap_add: list[str] = field(default_factory=list)
    cap_drop: list[str] = field(default_factory=list)
    security_opt: list[str] = field(default_factory=list)
    devices: list[str] = field(default_factory=list)
    privileged: bool = False
    init: bool | None = None
    ulimits: list[str] = field(default_factory=list)
    memory: str = ""
    memory_reservation: str = ""
    cpus: str = ""
    pids_limit: str = ""
    shm_size: str = ""
    stop_timeout: str = ""
    stop_signal: str = ""
    stdin_open: bool = False
    tty: bool = False
    profiles: list[str] = field(default_factory=list)
    pull_policy: str = ""
    platform: str = ""
    log_driver: str = ""
    log_options: list[str] = field(default_factory=list)
    dns: list[str] = field(default_factory=list)
    dns_search: list[str] = field(default_factory=list)
    group_add: list[str] = field(default_factory=list)
    pid_mode: str = ""
    ipc_mode: str = ""
    gpus: str = ""
    volumes_from: list[str] = field(default_factory=list)
    sysctls: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    replicas: int = 1
    facts: DockerfileFacts | None = None
    comments: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class NamedVolume:
    key: str
    docker_name: str
    external: bool = False
    driver: str = ""
    driver_opts: list[str] = field(default_factory=list)


@dataclass
class NamedNetwork:
    key: str
    docker_name: str
    driver: str = "bridge"
    external: bool = False
    internal: bool = False
    attachable: bool = False
    enable_ipv6: bool = False
    subnet: str = ""
    gateway: str = ""
    driver_opts: list[str] = field(default_factory=list)


@dataclass
class FlagRow:
    phase: str
    target: str
    flag: str
    value: str
    meaning: str
    happens: str
    analogy: str
    background: str


@dataclass
class Step:
    phase: str
    title: str
    script: str
    summary: str
    how_to: str
    success: str
    failure: str
    principle: str
    analogy: str
    history: str
    why: str
    concept_ids: list[str] = field(default_factory=list)
    flags: list[FlagRow] = field(default_factory=list)
    service: str = ""


@dataclass
class EnvRow:
    service: str
    key: str
    value: str
    source: str
    meaning: str
    file_note: str


@dataclass
class BuildRow:
    target: str
    path: str
    fact: str


@dataclass
class MappingRow:
    compose: str
    docker: str
    meaning: str


@dataclass
class Concept:
    ident: str
    title: str
    analogy: str
    principle: str
    picture: str
    history: str
    why: str


@dataclass
class Plan:
    project_name: str
    compose_path: str
    compose_filename: str
    project_dir_name: str
    services: list[Service]
    steps: list[Step]
    down_script: str
    env_rows: list[EnvRow]
    build_rows: list[BuildRow]
    mapping_rows: list[MappingRow]
    warnings: list[str]
    concepts: list[Concept]
    overview: str
    story: str
    selinux: str
    skipped_profiles: list[str]
