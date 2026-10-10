# eap-adot-otel を Docker コマンドだけで起動する

対象は compose.yaml、プロジェクト名は eap-adot-otel です。起動するコンテナは 11 台で、名前は eap-jaeger、eap-aurora、eap-valkey、eap-alb、eap-report-ec2、eap-external-slb、eap-localstack、eap-adot-collector、eap-lambda-runner、eap-back、eap-front です。Compose は呼ばず、docker network、docker volume、docker pull、docker build、docker run、docker inspect だけで同じ並びを作ります。バインドマウントの SELinux 指定は z です。値は Compose ファイルの ${VAR:-既定} を、変換時に埋めた結果です。変換したマシンの環境変数は、指定しない限り使いません。
変換時の注意: front のビルドに必要なファイルが、コンテキストにありません: dist/app.war / back のビルドに必要なファイルが、コンテキストにありません: dist/app.war / 通常の起動に含めないプロファイル付きサービス: batch-ec2（profile: batch）

## 実行の仕方

対象は RHEL 9.8 で、Docker Engine が入っているマシンです。
このファイルのコマンドは、下のコードブロックと同じ内容が `docker-commands.txt` に入っています。
改行は LF です。Windows のメモ帳で保存し直すと CRLF になり、行末の `\` が壊れます。

```bash
cd /path/to/project
bash docker-commands.txt
```

別のディレクトリから実行するときは、プロジェクトの場所を指定します。

```bash
PROJECT_ROOT=/path/to/project bash docker-commands.txt
```

## 起動コマンド

```bash
#!/bin/bash
# compose.yaml を Docker Engine のコマンドだけで起動します。
# プロジェクト名: eap-adot-otel
# 改行は LF です。\ の後ろに空白を置かないでください。
set -euo pipefail

if [ -z "${LANG:-}" ]; then
  export LANG=C.UTF-8
fi

say() {
  echo ""
  echo "==== $* ===="
}

wait_running() {
  local name="$1"
  local timeout="${2:-60}"
  local elapsed=0
  local running
  echo "起動を待っています: ${name} （最大 ${timeout} 秒）"
  while [ "$elapsed" -lt "$timeout" ]; do
    running=$(docker inspect --format '{{.State.Running}}' "$name" 2>/dev/null || true)
    if [ "$running" = "true" ]; then
      echo "${name} は動いています。"
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  echo "${name} が起動する前に時間切れです。" >&2
  docker logs --tail 80 "$name" >&2 || true
  return 1
}

wait_healthy() {
  local name="$1"
  local timeout="${2:-180}"
  local elapsed=0
  local status
  echo "healthy になるのを待っています: ${name} （最大 ${timeout} 秒）"
  while [ "$elapsed" -lt "$timeout" ]; do
    status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}nohealth{{end}}' "$name" 2>/dev/null || true)
    echo "  ${elapsed}秒時点: ${name} は ${status:-不明}"
    if [ "$status" = "healthy" ]; then
      echo "${name} は healthy です。"
      return 0
    fi
    if [ "$status" = "unhealthy" ]; then
      echo "${name} は unhealthy です。ログの末尾を表示します。" >&2
      docker logs --tail 80 "$name" >&2 || true
      return 1
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done
  echo "${name} が healthy になる前に時間切れです。" >&2
  docker logs --tail 80 "$name" >&2 || true
  return 1
}

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
if [ -z "${PROJECT_ROOT:-}" ]; then
  if [ -f "./compose.yaml" ]; then
    PROJECT_ROOT="$(pwd)"
  else
    echo "PROJECT_ROOT が空で、今いる場所に compose.yaml もありません。" >&2
    echo "プロジェクトのディレクトリで実行するか、PROJECT_ROOT を指定してください。" >&2
    exit 1
  fi
fi
if [ ! -f "${PROJECT_ROOT}/compose.yaml" ]; then
  echo "プロジェクトの目印がありません: ${PROJECT_ROOT}/compose.yaml" >&2
  exit 1
fi
echo "プロジェクトディレクトリ: ${PROJECT_ROOT}"
docker version --format 'クライアント {{.Client.Version}} / サーバ {{.Server.Version}}'
if command -v getenforce >/dev/null 2>&1; then
  echo "SELinux: $(getenforce)"
fi
echo "バインドマウントには SELinux の共有ラベル z を付けます。対象ファイルのラベルは container_file_t に変わり、ホストに残ります。"
echo '注意: front のビルドに必要なファイルが、コンテキストにありません: dist/app.war'
echo '注意: back のビルドに必要なファイルが、コンテキストにありません: dist/app.war'
echo '注意: 通常の起動に含めないプロファイル付きサービス: batch-ec2（profile: batch）'

say "橋ネットワークを作る: eap-adot-otel_lab"
if docker network inspect 'eap-adot-otel_lab' >/dev/null 2>&1; then
  echo "ネットワークは既にあります: eap-adot-otel_lab"
else
  docker network create \
    --driver 'bridge' \
    'eap-adot-otel_lab'
fi

say "データを残すロッカーを作る: eap-adot-otel_aurora-data"
if docker volume inspect 'eap-adot-otel_aurora-data' >/dev/null 2>&1; then
  echo "ボリュームは既にあります: eap-adot-otel_aurora-data"
else
  docker volume create \
    'eap-adot-otel_aurora-data'
fi

say "手元に無い公開イメージを取り寄せる"
if docker image inspect 'jaegertracing/all-in-one:1.62.0' >/dev/null 2>&1; then
  echo "イメージは手元にあります: jaegertracing/all-in-one:1.62.0"
else
  docker pull 'jaegertracing/all-in-one:1.62.0'
fi
if docker image inspect 'mysql:8.4' >/dev/null 2>&1; then
  echo "イメージは手元にあります: mysql:8.4"
else
  docker pull 'mysql:8.4'
fi
if docker image inspect 'valkey/valkey:8-alpine' >/dev/null 2>&1; then
  echo "イメージは手元にあります: valkey/valkey:8-alpine"
else
  docker pull 'valkey/valkey:8-alpine'
fi
if docker image inspect 'localstack/localstack:3.8' >/dev/null 2>&1; then
  echo "イメージは手元にあります: localstack/localstack:3.8"
else
  docker pull 'localstack/localstack:3.8'
fi
if docker image inspect 'public.ecr.aws/aws-observability/aws-otel-collector:v0.43.3' >/dev/null 2>&1; then
  echo "イメージは手元にあります: public.ecr.aws/aws-observability/aws-otel-collector:v0.43.3"
else
  docker pull 'public.ecr.aws/aws-observability/aws-otel-collector:v0.43.3'
fi

say "前提イメージを作る: app-eap-base:1.0"
echo 'back、front が FROM app-eap-base:1.0 しているため、サービス定義の外にある Containerfile を先に焼きます。 外から取る土台は registry.access.redhat.com/ubi9/ubi:9.8 です。'
if docker image inspect 'app-eap-base:1.0' >/dev/null 2>&1; then
  echo "イメージは既にあるのでビルドしません: app-eap-base:1.0"
  echo "材料を変えて作り直すときは、先に docker image rm app-eap-base:1.0 を実行します。"
else
  echo 'このレシピの SERVER_SOURCE の既定は zip です。切り替えるときは docker build に --build-arg SERVER_SOURCE=別の値 を足します。この手順は既定のままです。'
  missing=0
  if [ ! -e "${PROJECT_ROOT}/vendor/jboss-eap-8.1.0.zip" ]; then
    echo 'ビルドに必要なファイルがありません: vendor/jboss-eap-8.1.0.zip' >&2
    missing=1
  fi
  if [ "$missing" -ne 0 ]; then
    echo "材料を置くか、イメージを別の方法で用意してから、もう一度実行してください。" >&2
    exit 1
  fi
  docker build \
    --file "${PROJECT_ROOT}/base/Containerfile" \
    --tag 'app-eap-base:1.0' \
    "${PROJECT_ROOT}"
fi

say "イメージを作る: alb"
echo 'サービス alb の build です。 外から取る土台は registry.access.redhat.com/ubi9/ubi-minimal:9.5 です。'
if docker image inspect 'eap-adot-otel-alb' >/dev/null 2>&1; then
  echo "イメージは既にあるのでビルドしません: eap-adot-otel-alb"
  echo "材料を変えて作り直すときは、先に docker image rm eap-adot-otel-alb を実行します。"
else
  docker build \
    --file "${PROJECT_ROOT}/sim/alb/Dockerfile" \
    --tag 'eap-adot-otel-alb' \
    "${PROJECT_ROOT}/sim/alb"
fi

say "イメージを作る: report-ec2, external-slb"
echo 'サービス report-ec2, external-slb の build です。 外から取る土台は registry.access.redhat.com/ubi9/ubi-minimal:9.5 です。'
if docker image inspect 'eap-adot-otel-report-ec2' >/dev/null 2>&1; then
  echo "イメージは既にあるのでビルドしません: eap-adot-otel-report-ec2"
  echo "材料を変えて作り直すときは、先に docker image rm eap-adot-otel-report-ec2 を実行します。"
else
  docker build \
    --file "${PROJECT_ROOT}/sim/report-ec2/Dockerfile" \
    --tag 'eap-adot-otel-report-ec2' \
    "${PROJECT_ROOT}/sim/report-ec2"
fi
if ! docker image inspect 'eap-adot-otel-external-slb' >/dev/null 2>&1; then
  docker tag 'eap-adot-otel-report-ec2' 'eap-adot-otel-external-slb'
fi

say "イメージを作る: lambda-runner"
echo 'サービス lambda-runner の build です。 外から取る土台は registry.access.redhat.com/ubi9/ubi-minimal:9.5 です。'
if docker image inspect 'eap-adot-otel-lambda-runner' >/dev/null 2>&1; then
  echo "イメージは既にあるのでビルドしません: eap-adot-otel-lambda-runner"
  echo "材料を変えて作り直すときは、先に docker image rm eap-adot-otel-lambda-runner を実行します。"
else
  docker build \
    --file "${PROJECT_ROOT}/sim/lambda/Dockerfile" \
    --tag 'eap-adot-otel-lambda-runner' \
    "${PROJECT_ROOT}/sim/lambda"
fi

say "イメージを作る: back"
echo 'サービス back の build です。 外から取る土台は app-eap-base:1.0 です。'
if docker image inspect 'local/eap-back:dev' >/dev/null 2>&1; then
  echo "イメージは既にあるのでビルドしません: local/eap-back:dev"
  echo "材料を変えて作り直すときは、先に docker image rm local/eap-back:dev を実行します。"
else
  missing=0
  if [ ! -e "${PROJECT_ROOT}/dist/app.war" ]; then
    echo 'ビルドに必要なファイルがありません: dist/app.war' >&2
    missing=1
  fi
  if [ "$missing" -ne 0 ]; then
    echo "材料を置くか、イメージを別の方法で用意してから、もう一度実行してください。" >&2
    exit 1
  fi
  docker build \
    --file "${PROJECT_ROOT}/back/Containerfile" \
    --tag 'local/eap-back:dev' \
    --build-arg 'BASE_IMAGE=app-eap-base:1.0' \
    --build-arg 'APP_SOURCE=dist/app.war' \
    "${PROJECT_ROOT}"
fi

say "イメージを作る: front"
echo 'サービス front の build です。 外から取る土台は app-eap-base:1.0 です。'
if docker image inspect 'local/eap-front:dev' >/dev/null 2>&1; then
  echo "イメージは既にあるのでビルドしません: local/eap-front:dev"
  echo "材料を変えて作り直すときは、先に docker image rm local/eap-front:dev を実行します。"
else
  missing=0
  if [ ! -e "${PROJECT_ROOT}/dist/app.war" ]; then
    echo 'ビルドに必要なファイルがありません: dist/app.war' >&2
    missing=1
  fi
  if [ "$missing" -ne 0 ]; then
    echo "材料を置くか、イメージを別の方法で用意してから、もう一度実行してください。" >&2
    exit 1
  fi
  docker build \
    --file "${PROJECT_ROOT}/front/Containerfile" \
    --tag 'local/eap-front:dev' \
    --build-arg 'BASE_IMAGE=app-eap-base:1.0' \
    --build-arg 'APP_SOURCE=dist/app.war' \
    "${PROJECT_ROOT}"
fi

say "起動する: eap-jaeger"
if docker container inspect 'eap-jaeger' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-jaeger')" = "true" ]; then
    echo "既に動いています: eap-jaeger"
  else
    echo "止まっているので起動します: eap-jaeger"
    docker start 'eap-jaeger'
  fi
else
  docker run \
    --detach \
    --name 'eap-jaeger' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'jaeger' \
    --publish '16686:16686' \
    --env 'COLLECTOR_OTLP_ENABLED=true' \
    'jaegertracing/all-in-one:1.62.0'
fi

say "起動する: eap-aurora"
if docker container inspect 'eap-aurora' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-aurora')" = "true" ]; then
    echo "既に動いています: eap-aurora"
  else
    echo "止まっているので起動します: eap-aurora"
    docker start 'eap-aurora'
  fi
else
  docker run \
    --detach \
    --name 'eap-aurora' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'aurora' \
    --volume "eap-adot-otel_aurora-data:/var/lib/mysql" \
    --env 'MYSQL_ROOT_PASSWORD=rootpassword' \
    --env 'MYSQL_DATABASE=appdb' \
    --env 'MYSQL_USER=appuser' \
    --env 'MYSQL_PASSWORD=apppassword' \
    --env 'TZ=UTC' \
    --health-cmd 'mysqladmin ping -h 127.0.0.1 -u root -p${MYSQL_ROOT_PASSWORD} --silent' \
    --health-interval '10s' \
    --health-timeout '5s' \
    --health-start-period '40s' \
    --health-retries 15 \
    'mysql:8.4' \
    'mysqld' \
    '--character-set-server=utf8mb4' \
    '--collation-server=utf8mb4_0900_ai_ci' \
    '--mysql-native-password=ON'
fi

say "起動する: eap-valkey"
if docker container inspect 'eap-valkey' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-valkey')" = "true" ]; then
    echo "既に動いています: eap-valkey"
  else
    echo "止まっているので起動します: eap-valkey"
    docker start 'eap-valkey'
  fi
else
  docker run \
    --detach \
    --name 'eap-valkey' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'valkey' \
    --health-cmd 'valkey-cli ping' \
    --health-interval '10s' \
    --health-timeout '3s' \
    --health-start-period '10s' \
    --health-retries 10 \
    'valkey/valkey:8-alpine'
fi

say "起動する: eap-alb"
if docker container inspect 'eap-alb' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-alb')" = "true" ]; then
    echo "既に動いています: eap-alb"
  else
    echo "止まっているので起動します: eap-alb"
    docker start 'eap-alb'
  fi
else
  docker run \
    --detach \
    --name 'eap-alb' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'alb' \
    --publish '8081:80' \
    --env 'LISTEN_PORT=80' \
    --env 'ROUTES=^/report=report-ec2:8000,^/back=back:18080,^/front=front:8080,^/=front:8080' \
    'eap-adot-otel-alb'
fi

say "起動する: eap-report-ec2"
if docker container inspect 'eap-report-ec2' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-report-ec2')" = "true" ]; then
    echo "既に動いています: eap-report-ec2"
  else
    echo "止まっているので起動します: eap-report-ec2"
    docker start 'eap-report-ec2'
  fi
else
  docker run \
    --detach \
    --name 'eap-report-ec2' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'report-ec2' \
    --env 'PORT=8000' \
    --env 'STUB_NAME=report-ec2' \
    --env 'DELAY_MS=150' \
    'eap-adot-otel-report-ec2'
fi

say "起動する: eap-external-slb"
if docker container inspect 'eap-external-slb' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-external-slb')" = "true" ]; then
    echo "既に動いています: eap-external-slb"
  else
    echo "止まっているので起動します: eap-external-slb"
    docker start 'eap-external-slb'
  fi
else
  docker run \
    --detach \
    --name 'eap-external-slb' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'external-slb' \
    --env 'PORT=80' \
    --env 'STUB_NAME=external-slb' \
    --env 'DELAY_MS=200' \
    'eap-adot-otel-external-slb'
fi

say "起動する: eap-localstack"
if docker container inspect 'eap-localstack' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-localstack')" = "true" ]; then
    echo "既に動いています: eap-localstack"
  else
    echo "止まっているので起動します: eap-localstack"
    docker start 'eap-localstack'
  fi
else
  docker run \
    --detach \
    --name 'eap-localstack' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'localstack' \
    --publish '4566:4566' \
    --volume "${PROJECT_ROOT}/scripts/localstack-init:/etc/localstack/init/ready.d:ro,z" \
    --env 'SERVICES=sqs' \
    --env 'AWS_DEFAULT_REGION=ap-northeast-1' \
    --health-cmd 'curl -sf http://localhost:4566/_localstack/health || exit 1' \
    --health-interval '10s' \
    --health-timeout '5s' \
    --health-start-period '20s' \
    --health-retries 15 \
    'localstack/localstack:3.8'
fi

say "起動する: eap-adot-collector"
wait_running 'eap-jaeger' 90
if docker container inspect 'eap-adot-collector' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-adot-collector')" = "true" ]; then
    echo "既に動いています: eap-adot-collector"
  else
    echo "止まっているので起動します: eap-adot-collector"
    docker start 'eap-adot-collector'
  fi
else
  docker run \
    --detach \
    --name 'eap-adot-collector' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'adot-collector' \
    --publish '4317:4317' \
    --publish '4318:4318' \
    --publish '13133:13133' \
    --volume "${PROJECT_ROOT}/otel/collector-compose.yaml:/etc/otel/collector-compose.yaml:ro,z" \
    --env 'AWS_REGION=ap-northeast-1' \
    'public.ecr.aws/aws-observability/aws-otel-collector:v0.43.3' \
    '--config=/etc/otel/collector-compose.yaml'
fi

say "起動する: eap-lambda-runner"
wait_healthy 'eap-localstack' 200
if docker container inspect 'eap-lambda-runner' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-lambda-runner')" = "true" ]; then
    echo "既に動いています: eap-lambda-runner"
  else
    echo "止まっているので起動します: eap-lambda-runner"
    docker start 'eap-lambda-runner'
  fi
else
  docker run \
    --detach \
    --name 'eap-lambda-runner' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'lambda-runner' \
    --env 'SQS_ENDPOINT=http://localstack:4566' \
    --env 'SQS_QUEUE_URL=http://localstack:4566/000000000000/app-queue' \
    --env 'TARGET_URL=http://alb:80/back/api/from-lambda' \
    --env 'POLL_INTERVAL=2' \
    'eap-adot-otel-lambda-runner'
fi

say "起動する: eap-back"
wait_healthy 'eap-aurora' 220
wait_healthy 'eap-valkey' 140
wait_running 'eap-adot-collector' 90
if docker container inspect 'eap-back' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-back')" = "true" ]; then
    echo "既に動いています: eap-back"
  else
    echo "止まっているので起動します: eap-back"
    docker start 'eap-back'
  fi
else
  docker run \
    --detach \
    --name 'eap-back' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'back' \
    --read-only \
    --publish '18080:18080' \
    --tmpfs '/run/eap:uid=6301,gid=6302,mode=0770' \
    --env 'TZ=Asia/Tokyo' \
    --env 'JVM_OPTS_MODE=append' \
    --env 'EAP_HTTPS_MODE=remove' \
    --env 'EAP_CLI_STDOUT=echo' \
    --env 'APP_SERVICE=intra-api' \
    --env 'APP_ENV=local' \
    --env 'APP_NAMESPACE=shopdemo' \
    --env 'APP_VERSION=1.0.0' \
    --env 'PEER_NAME_AURORA=' \
    --env 'PEER_NAME_VALKEY=' \
    --env 'PEER_NAME_EC2=' \
    --env 'PEER_NAME_ALB=' \
    --env 'PEER_NAME_EXTERNAL_SLB=' \
    --env 'PEER_NAME_SQS=' \
    --env 'APP_PEER_NAME_MODE=as-is' \
    --env 'APP_EXTRA_RESOURCE_ATTRIBUTES=aws.ecs.cluster.name=shopdemo-local,aws.ecs.task.family=intra-api-local' \
    --env 'APP_SERVICE_EVENT_PACKAGES=' \
    --env 'OTEL_TRACE_WARN_SUPPRESS=resource,context' \
    --env 'OTEL_AGENT_LOG_SUPPRESS_EXTRA=' \
    --env 'APP_PEER_ALB_MODE=upstream' \
    --env 'APP_PEER_DOMAIN_RULES=' \
    --env 'APP_PEER_PORT_RULES=' \
    --env 'APP_PEER_EXTRA_HOSTS=' \
    --env 'APP_PEER_SERVICE_MAPPING=' \
    --env 'APP_CAPTURE_REQUEST_HEADERS_EXTRA=' \
    --env 'APP_CAPTURE_RESPONSE_HEADERS_EXTRA=' \
    --env 'APP_CAPTURE_CLIENT_REQUEST_HEADERS_EXTRA=' \
    --env 'APP_CAPTURE_CLIENT_RESPONSE_HEADERS_EXTRA=' \
    --env 'APP_CAPTURE_REQUEST_PARAMETERS=' \
    --env 'OTEL_EXPORTER_OTLP_ENDPOINT=http://adot-collector:4317' \
    --env 'OTEL_EXPORTER_OTLP_PROTOCOL=grpc' \
    --env 'DB_HOST=aurora' \
    --env 'DB_PORT=3306' \
    --env 'DB_NAME=appdb' \
    --env 'DB_USER=appuser' \
    --env 'DB_PASSWORD=apppassword' \
    --env 'VALKEY_HOST=valkey' \
    --env 'VALKEY_PORT=6379' \
    --env 'REPORT_ALB_HOST=alb' \
    --env 'REPORT_ALB_URL=http://alb:80/report/daily' \
    --env 'EXTERNAL_SLB_HOST=external-slb' \
    --env 'EXTERNAL_SLB_URL=http://external-slb:80/outside/api' \
    --env 'SQS_HOST=localstack' \
    --env 'SQS_ENDPOINT=http://localstack:4566' \
    --env 'SQS_QUEUE_URL=http://localstack:4566/000000000000/app-queue' \
    --env 'AWS_REGION=ap-northeast-1' \
    --env 'AWS_ACCESS_KEY_ID=test' \
    --env 'AWS_SECRET_ACCESS_KEY=test' \
    --env 'APP_ROLE=back' \
    --health-cmd '/opt/app/bin/healthcheck.sh' \
    --health-interval '15s' \
    --health-timeout '5s' \
    --health-start-period '120s' \
    --health-retries 20 \
    'local/eap-back:dev'
fi

say "起動する: eap-front"
wait_healthy 'eap-aurora' 220
wait_healthy 'eap-valkey' 140
wait_running 'eap-adot-collector' 90
wait_healthy 'eap-back' 450
if docker container inspect 'eap-front' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-front')" = "true" ]; then
    echo "既に動いています: eap-front"
  else
    echo "止まっているので起動します: eap-front"
    docker start 'eap-front'
  fi
else
  docker run \
    --detach \
    --name 'eap-front' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'front' \
    --read-only \
    --publish '8080:8080' \
    --tmpfs '/run/eap:uid=6301,gid=6302,mode=0770' \
    --env 'TZ=Asia/Tokyo' \
    --env 'JVM_OPTS_MODE=append' \
    --env 'EAP_HTTPS_MODE=remove' \
    --env 'EAP_CLI_STDOUT=echo' \
    --env 'APP_SERVICE=intra-api' \
    --env 'APP_ENV=local' \
    --env 'APP_NAMESPACE=shopdemo' \
    --env 'APP_VERSION=1.0.0' \
    --env 'PEER_NAME_AURORA=' \
    --env 'PEER_NAME_VALKEY=' \
    --env 'PEER_NAME_EC2=' \
    --env 'PEER_NAME_ALB=' \
    --env 'PEER_NAME_EXTERNAL_SLB=' \
    --env 'PEER_NAME_SQS=' \
    --env 'APP_PEER_NAME_MODE=as-is' \
    --env 'APP_EXTRA_RESOURCE_ATTRIBUTES=aws.ecs.cluster.name=shopdemo-local,aws.ecs.task.family=intra-api-local' \
    --env 'APP_SERVICE_EVENT_PACKAGES=' \
    --env 'OTEL_TRACE_WARN_SUPPRESS=resource,context' \
    --env 'OTEL_AGENT_LOG_SUPPRESS_EXTRA=' \
    --env 'APP_PEER_ALB_MODE=upstream' \
    --env 'APP_PEER_DOMAIN_RULES=' \
    --env 'APP_PEER_PORT_RULES=' \
    --env 'APP_PEER_EXTRA_HOSTS=' \
    --env 'APP_PEER_SERVICE_MAPPING=' \
    --env 'APP_CAPTURE_REQUEST_HEADERS_EXTRA=' \
    --env 'APP_CAPTURE_RESPONSE_HEADERS_EXTRA=' \
    --env 'APP_CAPTURE_CLIENT_REQUEST_HEADERS_EXTRA=' \
    --env 'APP_CAPTURE_CLIENT_RESPONSE_HEADERS_EXTRA=' \
    --env 'APP_CAPTURE_REQUEST_PARAMETERS=' \
    --env 'OTEL_EXPORTER_OTLP_ENDPOINT=http://adot-collector:4317' \
    --env 'OTEL_EXPORTER_OTLP_PROTOCOL=grpc' \
    --env 'DB_HOST=aurora' \
    --env 'DB_PORT=3306' \
    --env 'DB_NAME=appdb' \
    --env 'DB_USER=appuser' \
    --env 'DB_PASSWORD=apppassword' \
    --env 'VALKEY_HOST=valkey' \
    --env 'VALKEY_PORT=6379' \
    --env 'REPORT_ALB_HOST=alb' \
    --env 'REPORT_ALB_URL=http://alb:80/report/daily' \
    --env 'EXTERNAL_SLB_HOST=external-slb' \
    --env 'EXTERNAL_SLB_URL=http://external-slb:80/outside/api' \
    --env 'SQS_HOST=localstack' \
    --env 'SQS_ENDPOINT=http://localstack:4566' \
    --env 'SQS_QUEUE_URL=http://localstack:4566/000000000000/app-queue' \
    --env 'AWS_REGION=ap-northeast-1' \
    --env 'AWS_ACCESS_KEY_ID=test' \
    --env 'AWS_SECRET_ACCESS_KEY=test' \
    --env 'APP_ROLE=front' \
    --env 'BACKEND_HOST=back' \
    --env 'BACKEND_URL=http://back:18080' \
    --health-cmd '/opt/app/bin/healthcheck.sh' \
    --health-interval '15s' \
    --health-timeout '5s' \
    --health-start-period '120s' \
    --health-retries 20 \
    'local/eap-front:dev'
fi

say "起動結果を確認する"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
docker inspect --format '{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{else}}healthcheckなし{{end}}' 'eap-aurora'
docker inspect --format '{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{else}}healthcheckなし{{end}}' 'eap-valkey'
docker inspect --format '{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{else}}healthcheckなし{{end}}' 'eap-localstack'
docker inspect --format '{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{else}}healthcheckなし{{end}}' 'eap-back'
docker inspect --format '{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{else}}healthcheckなし{{end}}' 'eap-front'
echo "ログを追うときは docker logs --tail 50 コンテナ名 を実行します。"

echo ""
echo "起動手順はここまでです。"
echo "止めるときは、このファイルの exit 0 より下だけを実行してください。"
exit 0

#!/bin/bash
# 停止用です。コンテナとネットワークを消し、名前付きボリュームとイメージは残します。
set -euo pipefail
echo "コンテナを止めて捨てます。ボリュームは残します。"
docker rm --force 'eap-front' || true
docker rm --force 'eap-back' || true
docker rm --force 'eap-lambda-runner' || true
docker rm --force 'eap-adot-collector' || true
docker rm --force 'eap-localstack' || true
docker rm --force 'eap-external-slb' || true
docker rm --force 'eap-report-ec2' || true
docker rm --force 'eap-alb' || true
docker rm --force 'eap-valkey' || true
docker rm --force 'eap-aurora' || true
docker rm --force 'eap-jaeger' || true
echo "ネットワークを消します。"
docker network rm 'eap-adot-otel_lab' || true
echo "ボリュームは残しています。データも捨てるときだけ、次を手で実行します。"
echo "  docker volume ls"
echo "停止が終わりました。"
```

## 各段階

### 1. 実行前の確認

Docker Engine に接続できること、プロジェクトの場所、SELinux の状態を確認します。このあとで使う待ち関数も、ここで定義します。

実行の仕方: RHEL 上で、プロジェクトのディレクトリに入って bash docker-commands.txt と実行します。別の場所からなら PROJECT_ROOT=/実際のパス bash docker-commands.txt です。

成功すると: クライアントとサーバの版、SELinux の状態が表示され、次の段階へ進みます。

失敗すると: docker が無い、デーモンが止まっている、Podman 互換である、PROJECT_ROOT が違う、のいずれかです。

```bash
#!/bin/bash
# compose.yaml を Docker Engine のコマンドだけで起動します。
# プロジェクト名: eap-adot-otel
# 改行は LF です。\ の後ろに空白を置かないでください。
set -euo pipefail

if [ -z "${LANG:-}" ]; then
  export LANG=C.UTF-8
fi

say() {
  echo ""
  echo "==== $* ===="
}

wait_running() {
  local name="$1"
  local timeout="${2:-60}"
  local elapsed=0
  local running
  echo "起動を待っています: ${name} （最大 ${timeout} 秒）"
  while [ "$elapsed" -lt "$timeout" ]; do
    running=$(docker inspect --format '{{.State.Running}}' "$name" 2>/dev/null || true)
    if [ "$running" = "true" ]; then
      echo "${name} は動いています。"
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  echo "${name} が起動する前に時間切れです。" >&2
  docker logs --tail 80 "$name" >&2 || true
  return 1
}

wait_healthy() {
  local name="$1"
  local timeout="${2:-180}"
  local elapsed=0
  local status
  echo "healthy になるのを待っています: ${name} （最大 ${timeout} 秒）"
  while [ "$elapsed" -lt "$timeout" ]; do
    status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}nohealth{{end}}' "$name" 2>/dev/null || true)
    echo "  ${elapsed}秒時点: ${name} は ${status:-不明}"
    if [ "$status" = "healthy" ]; then
      echo "${name} は healthy です。"
      return 0
    fi
    if [ "$status" = "unhealthy" ]; then
      echo "${name} は unhealthy です。ログの末尾を表示します。" >&2
      docker logs --tail 80 "$name" >&2 || true
      return 1
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done
  echo "${name} が healthy になる前に時間切れです。" >&2
  docker logs --tail 80 "$name" >&2 || true
  return 1
}

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
if [ -z "${PROJECT_ROOT:-}" ]; then
  if [ -f "./compose.yaml" ]; then
    PROJECT_ROOT="$(pwd)"
  else
    echo "PROJECT_ROOT が空で、今いる場所に compose.yaml もありません。" >&2
    echo "プロジェクトのディレクトリで実行するか、PROJECT_ROOT を指定してください。" >&2
    exit 1
  fi
fi
if [ ! -f "${PROJECT_ROOT}/compose.yaml" ]; then
  echo "プロジェクトの目印がありません: ${PROJECT_ROOT}/compose.yaml" >&2
  exit 1
fi
echo "プロジェクトディレクトリ: ${PROJECT_ROOT}"
docker version --format 'クライアント {{.Client.Version}} / サーバ {{.Server.Version}}'
if command -v getenforce >/dev/null 2>&1; then
  echo "SELinux: $(getenforce)"
fi
echo "バインドマウントには SELinux の共有ラベル z を付けます。対象ファイルのラベルは container_file_t に変わり、ホストに残ります。"
echo '注意: front のビルドに必要なファイルが、コンテキストにありません: dist/app.war'
echo '注意: back のビルドに必要なファイルが、コンテキストにありません: dist/app.war'
echo '注意: 通常の起動に含めないプロファイル付きサービス: batch-ec2（profile: batch）'
```

### 2. ネットワーク eap-adot-otel_lab

コンテナが名前で呼び合うための橋を用意します。Compose 上の名前は lab、Docker 上の名前は eap-adot-otel_lab です。プロジェクト名とネットワーク名のあいだはアンダースコアです。

実行の仕方: この段階だけを再実行しても、既にあれば作り直しません。消すときは停止手順のあとで docker network rm を使います。

成功すると: docker network inspect が名前、ドライバ、サブネットを表示できる状態です。

失敗すると: 同名の別ドライバが残っている、権限が無い、指定サブネットが重なっている、のいずれかです。

```bash
say "橋ネットワークを作る: eap-adot-otel_lab"
if docker network inspect 'eap-adot-otel_lab' >/dev/null 2>&1; then
  echo "ネットワークは既にあります: eap-adot-otel_lab"
else
  docker network create \
    --driver 'bridge' \
    'eap-adot-otel_lab'
fi
```

### 3. ボリューム eap-adot-otel_aurora-data

コンテナを消しても残る保存場所 eap-adot-otel_aurora-data を作ります。中にデータベースのファイルが入ります。停止手順では、このロッカーは消しません。

実行の仕方: 中身を捨てるときだけ、コンテナを止めたあとに docker volume rm を別に実行します。

成功すると: docker volume inspect に Name と Mountpoint が出ます。

失敗すると: 同名の壊れたボリュームがある、ディスクが足りない、権限が無い、のいずれかです。

```bash
say "データを残すロッカーを作る: eap-adot-otel_aurora-data"
if docker volume inspect 'eap-adot-otel_aurora-data' >/dev/null 2>&1; then
  echo "ボリュームは既にあります: eap-adot-otel_aurora-data"
else
  docker volume create \
    'eap-adot-otel_aurora-data'
fi
```

### 4. 公開イメージを取り寄せる

ビルドせずに image だけが書いてあるサービスについて、同じタグが手元に無いときだけ docker pull します。

実行の仕方: 回線と、必要なら HTTPS_PROXY を用意してから実行します。既にあれば取り寄せません。

成功すると: 各イメージに対して『手元にあります』か、pull の完了メッセージが出ます。

失敗すると: 名前解決、プロキシ、認証、ディスク不足です。メッセージの画像名を見て、そのレジストリだけを確認します。

```bash
say "手元に無い公開イメージを取り寄せる"
if docker image inspect 'jaegertracing/all-in-one:1.62.0' >/dev/null 2>&1; then
  echo "イメージは手元にあります: jaegertracing/all-in-one:1.62.0"
else
  docker pull 'jaegertracing/all-in-one:1.62.0'
fi
if docker image inspect 'mysql:8.4' >/dev/null 2>&1; then
  echo "イメージは手元にあります: mysql:8.4"
else
  docker pull 'mysql:8.4'
fi
if docker image inspect 'valkey/valkey:8-alpine' >/dev/null 2>&1; then
  echo "イメージは手元にあります: valkey/valkey:8-alpine"
else
  docker pull 'valkey/valkey:8-alpine'
fi
if docker image inspect 'localstack/localstack:3.8' >/dev/null 2>&1; then
  echo "イメージは手元にあります: localstack/localstack:3.8"
else
  docker pull 'localstack/localstack:3.8'
fi
if docker image inspect 'public.ecr.aws/aws-observability/aws-otel-collector:v0.43.3' >/dev/null 2>&1; then
  echo "イメージは手元にあります: public.ecr.aws/aws-observability/aws-otel-collector:v0.43.3"
else
  docker pull 'public.ecr.aws/aws-observability/aws-otel-collector:v0.43.3'
fi
```

### 5. 前提イメージを作る: app-eap-base:1.0

back、front が FROM app-eap-base:1.0 しているため、サービス定義の外にある Containerfile を先に焼きます。 外から取る土台は registry.access.redhat.com/ubi9/ubi:9.8 です。 今の作業ツリーでは次が未配置です: vendor/jboss-eap-8.1.0.zip。イメージが既にある場合はビルドを飛ばします。

実行の仕方: プロジェクトディレクトリの中身が、RHEL 上の PROJECT_ROOT と同じ配置になっている必要があります。カードが既にあれば、この段階は確認だけです。

成功すると: docker image inspect が成功し、次の段階へ進みます。

失敗すると: COPY の材料が無い、FROM の土台が無い、プロキシで倉庫へ届かない、ディスク不足、のいずれかです。

```bash
say "前提イメージを作る: app-eap-base:1.0"
echo 'back、front が FROM app-eap-base:1.0 しているため、サービス定義の外にある Containerfile を先に焼きます。 外から取る土台は registry.access.redhat.com/ubi9/ubi:9.8 です。'
if docker image inspect 'app-eap-base:1.0' >/dev/null 2>&1; then
  echo "イメージは既にあるのでビルドしません: app-eap-base:1.0"
  echo "材料を変えて作り直すときは、先に docker image rm app-eap-base:1.0 を実行します。"
else
  echo 'このレシピの SERVER_SOURCE の既定は zip です。切り替えるときは docker build に --build-arg SERVER_SOURCE=別の値 を足します。この手順は既定のままです。'
  missing=0
  if [ ! -e "${PROJECT_ROOT}/vendor/jboss-eap-8.1.0.zip" ]; then
    echo 'ビルドに必要なファイルがありません: vendor/jboss-eap-8.1.0.zip' >&2
    missing=1
  fi
  if [ "$missing" -ne 0 ]; then
    echo "材料を置くか、イメージを別の方法で用意してから、もう一度実行してください。" >&2
    exit 1
  fi
  docker build \
    --file "${PROJECT_ROOT}/base/Containerfile" \
    --tag 'app-eap-base:1.0' \
    "${PROJECT_ROOT}"
fi
```

### 6. イメージを作る: alb

サービス alb の build です。 外から取る土台は registry.access.redhat.com/ubi9/ubi-minimal:9.5 です。

実行の仕方: プロジェクトディレクトリの中身が、RHEL 上の PROJECT_ROOT と同じ配置になっている必要があります。カードが既にあれば、この段階は確認だけです。

成功すると: docker image inspect が成功し、次の段階へ進みます。

失敗すると: COPY の材料が無い、FROM の土台が無い、プロキシで倉庫へ届かない、ディスク不足、のいずれかです。

```bash
say "イメージを作る: alb"
echo 'サービス alb の build です。 外から取る土台は registry.access.redhat.com/ubi9/ubi-minimal:9.5 です。'
if docker image inspect 'eap-adot-otel-alb' >/dev/null 2>&1; then
  echo "イメージは既にあるのでビルドしません: eap-adot-otel-alb"
  echo "材料を変えて作り直すときは、先に docker image rm eap-adot-otel-alb を実行します。"
else
  docker build \
    --file "${PROJECT_ROOT}/sim/alb/Dockerfile" \
    --tag 'eap-adot-otel-alb' \
    "${PROJECT_ROOT}/sim/alb"
fi
```

### 7. イメージを作る: report-ec2, external-slb

サービス report-ec2, external-slb の build です。 外から取る土台は registry.access.redhat.com/ubi9/ubi-minimal:9.5 です。

実行の仕方: プロジェクトディレクトリの中身が、RHEL 上の PROJECT_ROOT と同じ配置になっている必要があります。カードが既にあれば、この段階は確認だけです。

成功すると: docker image inspect が成功し、次の段階へ進みます。

失敗すると: COPY の材料が無い、FROM の土台が無い、プロキシで倉庫へ届かない、ディスク不足、のいずれかです。

```bash
say "イメージを作る: report-ec2, external-slb"
echo 'サービス report-ec2, external-slb の build です。 外から取る土台は registry.access.redhat.com/ubi9/ubi-minimal:9.5 です。'
if docker image inspect 'eap-adot-otel-report-ec2' >/dev/null 2>&1; then
  echo "イメージは既にあるのでビルドしません: eap-adot-otel-report-ec2"
  echo "材料を変えて作り直すときは、先に docker image rm eap-adot-otel-report-ec2 を実行します。"
else
  docker build \
    --file "${PROJECT_ROOT}/sim/report-ec2/Dockerfile" \
    --tag 'eap-adot-otel-report-ec2' \
    "${PROJECT_ROOT}/sim/report-ec2"
fi
if ! docker image inspect 'eap-adot-otel-external-slb' >/dev/null 2>&1; then
  docker tag 'eap-adot-otel-report-ec2' 'eap-adot-otel-external-slb'
fi
```

### 8. イメージを作る: lambda-runner

サービス lambda-runner の build です。 外から取る土台は registry.access.redhat.com/ubi9/ubi-minimal:9.5 です。

実行の仕方: プロジェクトディレクトリの中身が、RHEL 上の PROJECT_ROOT と同じ配置になっている必要があります。カードが既にあれば、この段階は確認だけです。

成功すると: docker image inspect が成功し、次の段階へ進みます。

失敗すると: COPY の材料が無い、FROM の土台が無い、プロキシで倉庫へ届かない、ディスク不足、のいずれかです。

```bash
say "イメージを作る: lambda-runner"
echo 'サービス lambda-runner の build です。 外から取る土台は registry.access.redhat.com/ubi9/ubi-minimal:9.5 です。'
if docker image inspect 'eap-adot-otel-lambda-runner' >/dev/null 2>&1; then
  echo "イメージは既にあるのでビルドしません: eap-adot-otel-lambda-runner"
  echo "材料を変えて作り直すときは、先に docker image rm eap-adot-otel-lambda-runner を実行します。"
else
  docker build \
    --file "${PROJECT_ROOT}/sim/lambda/Dockerfile" \
    --tag 'eap-adot-otel-lambda-runner' \
    "${PROJECT_ROOT}/sim/lambda"
fi
```

### 9. イメージを作る: back

サービス back の build です。 外から取る土台は app-eap-base:1.0 です。 今の作業ツリーでは次が未配置です: dist/app.war。イメージが既にある場合はビルドを飛ばします。

実行の仕方: プロジェクトディレクトリの中身が、RHEL 上の PROJECT_ROOT と同じ配置になっている必要があります。カードが既にあれば、この段階は確認だけです。

成功すると: docker image inspect が成功し、次の段階へ進みます。

失敗すると: COPY の材料が無い、FROM の土台が無い、プロキシで倉庫へ届かない、ディスク不足、のいずれかです。

```bash
say "イメージを作る: back"
echo 'サービス back の build です。 外から取る土台は app-eap-base:1.0 です。'
if docker image inspect 'local/eap-back:dev' >/dev/null 2>&1; then
  echo "イメージは既にあるのでビルドしません: local/eap-back:dev"
  echo "材料を変えて作り直すときは、先に docker image rm local/eap-back:dev を実行します。"
else
  missing=0
  if [ ! -e "${PROJECT_ROOT}/dist/app.war" ]; then
    echo 'ビルドに必要なファイルがありません: dist/app.war' >&2
    missing=1
  fi
  if [ "$missing" -ne 0 ]; then
    echo "材料を置くか、イメージを別の方法で用意してから、もう一度実行してください。" >&2
    exit 1
  fi
  docker build \
    --file "${PROJECT_ROOT}/back/Containerfile" \
    --tag 'local/eap-back:dev' \
    --build-arg 'BASE_IMAGE=app-eap-base:1.0' \
    --build-arg 'APP_SOURCE=dist/app.war' \
    "${PROJECT_ROOT}"
fi
```

### 10. イメージを作る: front

サービス front の build です。 外から取る土台は app-eap-base:1.0 です。 今の作業ツリーでは次が未配置です: dist/app.war。イメージが既にある場合はビルドを飛ばします。

実行の仕方: プロジェクトディレクトリの中身が、RHEL 上の PROJECT_ROOT と同じ配置になっている必要があります。カードが既にあれば、この段階は確認だけです。

成功すると: docker image inspect が成功し、次の段階へ進みます。

失敗すると: COPY の材料が無い、FROM の土台が無い、プロキシで倉庫へ届かない、ディスク不足、のいずれかです。

```bash
say "イメージを作る: front"
echo 'サービス front の build です。 外から取る土台は app-eap-base:1.0 です。'
if docker image inspect 'local/eap-front:dev' >/dev/null 2>&1; then
  echo "イメージは既にあるのでビルドしません: local/eap-front:dev"
  echo "材料を変えて作り直すときは、先に docker image rm local/eap-front:dev を実行します。"
else
  missing=0
  if [ ! -e "${PROJECT_ROOT}/dist/app.war" ]; then
    echo 'ビルドに必要なファイルがありません: dist/app.war' >&2
    missing=1
  fi
  if [ "$missing" -ne 0 ]; then
    echo "材料を置くか、イメージを別の方法で用意してから、もう一度実行してください。" >&2
    exit 1
  fi
  docker build \
    --file "${PROJECT_ROOT}/front/Containerfile" \
    --tag 'local/eap-front:dev' \
    --build-arg 'BASE_IMAGE=app-eap-base:1.0' \
    --build-arg 'APP_SOURCE=dist/app.war' \
    "${PROJECT_ROOT}"
fi
```

### 11. 起動する: eap-jaeger

eap-jaeger を起動します。観察ノートを絵にして廊下に貼る掲示板です。本番の X-Ray の代わりに、このマシンの中で見ます。
イメージは jaegertracing/all-in-one:1.62.0 です。
ホストへ開く扉は 16686:16686 です。
同じネットワークでは jaeger という名札で届きます。台帳の名前は eap-jaeger です。
元の定義のメモ: jaeger — ローカルの可視化先 (本番は X-Ray)

実行の仕方: 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

成功すると: docker ps に eap-jaeger が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

失敗すると: 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

```bash
say "起動する: eap-jaeger"
if docker container inspect 'eap-jaeger' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-jaeger')" = "true" ]; then
    echo "既に動いています: eap-jaeger"
  else
    echo "止まっているので起動します: eap-jaeger"
    docker start 'eap-jaeger'
  fi
else
  docker run \
    --detach \
    --name 'eap-jaeger' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'jaeger' \
    --publish '16686:16686' \
    --env 'COLLECTOR_OTLP_ENABLED=true' \
    'jaegertracing/all-in-one:1.62.0'
fi
```

### 12. 起動する: eap-aurora

eap-aurora を起動します。閉めなくても中身が残る冷蔵庫です。データは名前付きボリュームというロッカーに置きます。
イメージは mysql:8.4 です。
同じネットワークでは aurora という名札で届きます。台帳の名前は eap-aurora です。
イメージ名の後ろの引数で、起動コマンドを差し替えます。
元の定義のメモ: aurora — Aurora Serverless v2 (MySQL 8.4 互換) のローカル代替

実行の仕方: 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

成功すると: docker ps に eap-aurora が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

失敗すると: 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

```bash
say "起動する: eap-aurora"
if docker container inspect 'eap-aurora' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-aurora')" = "true" ]; then
    echo "既に動いています: eap-aurora"
  else
    echo "止まっているので起動します: eap-aurora"
    docker start 'eap-aurora'
  fi
else
  docker run \
    --detach \
    --name 'eap-aurora' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'aurora' \
    --volume "eap-adot-otel_aurora-data:/var/lib/mysql" \
    --env 'MYSQL_ROOT_PASSWORD=rootpassword' \
    --env 'MYSQL_DATABASE=appdb' \
    --env 'MYSQL_USER=appuser' \
    --env 'MYSQL_PASSWORD=apppassword' \
    --env 'TZ=UTC' \
    --health-cmd 'mysqladmin ping -h 127.0.0.1 -u root -p${MYSQL_ROOT_PASSWORD} --silent' \
    --health-interval '10s' \
    --health-timeout '5s' \
    --health-start-period '40s' \
    --health-retries 15 \
    'mysql:8.4' \
    'mysqld' \
    '--character-set-server=utf8mb4' \
    '--collation-server=utf8mb4_0900_ai_ci' \
    '--mysql-native-password=ON'
fi
```

### 13. 起動する: eap-valkey

eap-valkey を起動します。短い時間だけ覚えておくメモ用紙です。この定義ではロッカーを付けていないので、コンテナを捨てるとメモは消えます。
イメージは valkey/valkey:8-alpine です。
同じネットワークでは valkey という名札で届きます。台帳の名前は eap-valkey です。
元の定義のメモ: valkey — ElastiCache for Valkey のローカル代替

実行の仕方: 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

成功すると: docker ps に eap-valkey が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

失敗すると: 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

```bash
say "起動する: eap-valkey"
if docker container inspect 'eap-valkey' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-valkey')" = "true" ]; then
    echo "既に動いています: eap-valkey"
  else
    echo "止まっているので起動します: eap-valkey"
    docker start 'eap-valkey'
  fi
else
  docker run \
    --detach \
    --name 'eap-valkey' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'valkey' \
    --health-cmd 'valkey-cli ping' \
    --health-interval '10s' \
    --health-timeout '3s' \
    --health-start-period '10s' \
    --health-retries 10 \
    'valkey/valkey:8-alpine'
fi
```

### 14. 起動する: eap-alb

eap-alb を起動します。正門の案内係です。経路の先頭に応じて、帳票の部屋、台所、カウンターへ通します。
イメージは eap-adot-otel-alb です。
ホストへ開く扉は 8081:80 です。
同じネットワークでは alb という名札で届きます。台帳の名前は eap-alb です。
元の定義のメモ: alb — ALB のトレース関連挙動 (X-Amzn-Trace-Id の採番/透過) を再現

実行の仕方: 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

成功すると: docker ps に eap-alb が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

失敗すると: 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

```bash
say "起動する: eap-alb"
if docker container inspect 'eap-alb' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-alb')" = "true" ]; then
    echo "既に動いています: eap-alb"
  else
    echo "止まっているので起動します: eap-alb"
    docker start 'eap-alb'
  fi
else
  docker run \
    --detach \
    --name 'eap-alb' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'alb' \
    --publish '8081:80' \
    --env 'LISTEN_PORT=80' \
    --env 'ROUTES=^/report=report-ec2:8000,^/back=back:18080,^/front=front:8080,^/=front:8080' \
    'eap-adot-otel-alb'
fi
```

### 15. 起動する: eap-report-ec2

eap-report-ec2 を起動します。帳票を作る別室です。観察ノートには自分からは書きません。
イメージは eap-adot-otel-report-ec2 です。
同じネットワークでは report-ec2 という名札で届きます。台帳の名前は eap-report-ec2 です。
元の定義のメモ: report-ec2 — 帳票 EC2 サーバ (あえて計装しない)

実行の仕方: 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

成功すると: docker ps に eap-report-ec2 が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

失敗すると: 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

```bash
say "起動する: eap-report-ec2"
if docker container inspect 'eap-report-ec2' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-report-ec2')" = "true" ]; then
    echo "既に動いています: eap-report-ec2"
  else
    echo "止まっているので起動します: eap-report-ec2"
    docker start 'eap-report-ec2'
  fi
else
  docker run \
    --detach \
    --name 'eap-report-ec2' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'report-ec2' \
    --env 'PORT=8000' \
    --env 'STUB_NAME=report-ec2' \
    --env 'DELAY_MS=150' \
    'eap-adot-otel-report-ec2'
fi
```

### 16. 起動する: eap-external-slb

eap-external-slb を起動します。学校の外にある窓口の代わりです。この定義では中身は同じ種類の小さな受け答え役です。
イメージは eap-adot-otel-external-slb です。
同じネットワークでは external-slb という名札で届きます。台帳の名前は eap-external-slb です。
元の定義のメモ: external-slb — 外部ロードバランサー経由の VPC 外通信先 (計装しない)

実行の仕方: 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

成功すると: docker ps に eap-external-slb が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

失敗すると: 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

```bash
say "起動する: eap-external-slb"
if docker container inspect 'eap-external-slb' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-external-slb')" = "true" ]; then
    echo "既に動いています: eap-external-slb"
  else
    echo "止まっているので起動します: eap-external-slb"
    docker start 'eap-external-slb'
  fi
else
  docker run \
    --detach \
    --name 'eap-external-slb' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'external-slb' \
    --env 'PORT=80' \
    --env 'STUB_NAME=external-slb' \
    --env 'DELAY_MS=200' \
    'eap-adot-otel-external-slb'
fi
```

### 17. 起動する: eap-localstack

eap-localstack を起動します。校内に置いた仮の郵便箱です。本番の SQS の代わりに、キューのやり取りをこのマシンの中で練習します。
イメージは localstack/localstack:3.8 です。
ホストへ開く扉は 4566:4566 です。
同じネットワークでは localstack という名札で届きます。台帳の名前は eap-localstack です。
元の定義のメモ: localstack — SQS のローカル代替

実行の仕方: 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

成功すると: docker ps に eap-localstack が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

失敗すると: 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

```bash
say "起動する: eap-localstack"
if docker container inspect 'eap-localstack' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-localstack')" = "true" ]; then
    echo "既に動いています: eap-localstack"
  else
    echo "止まっているので起動します: eap-localstack"
    docker start 'eap-localstack'
  fi
else
  docker run \
    --detach \
    --name 'eap-localstack' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'localstack' \
    --publish '4566:4566' \
    --volume "${PROJECT_ROOT}/scripts/localstack-init:/etc/localstack/init/ready.d:ro,z" \
    --env 'SERVICES=sqs' \
    --env 'AWS_DEFAULT_REGION=ap-northeast-1' \
    --health-cmd 'curl -sf http://localhost:4566/_localstack/health || exit 1' \
    --health-interval '10s' \
    --health-timeout '5s' \
    --health-start-period '20s' \
    --health-retries 15 \
    'localstack/localstack:3.8'
fi
```

### 18. 起動する: eap-adot-collector

eap-adot-collector を起動します。各店から渡される観察メモを受け取り、掲示板へ届ける係です。
イメージは public.ecr.aws/aws-observability/aws-otel-collector:v0.43.3 です。
ホストへ開く扉は 4317:4317、4318:4318、13133:13133 です。
その前に確認すること: eap-jaeger のプロセスが動いている。
同じネットワークでは adot-collector という名札で届きます。台帳の名前は eap-adot-collector です。
イメージ名の後ろの引数で、起動コマンドを差し替えます。
元の定義のメモ: adot-collector — ADOT Collector サイドカー

実行の仕方: 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

成功すると: docker ps に eap-adot-collector が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

失敗すると: 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

```bash
say "起動する: eap-adot-collector"
wait_running 'eap-jaeger' 90
if docker container inspect 'eap-adot-collector' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-adot-collector')" = "true" ]; then
    echo "既に動いています: eap-adot-collector"
  else
    echo "止まっているので起動します: eap-adot-collector"
    docker start 'eap-adot-collector'
  fi
else
  docker run \
    --detach \
    --name 'eap-adot-collector' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'adot-collector' \
    --publish '4317:4317' \
    --publish '4318:4318' \
    --publish '13133:13133' \
    --volume "${PROJECT_ROOT}/otel/collector-compose.yaml:/etc/otel/collector-compose.yaml:ro,z" \
    --env 'AWS_REGION=ap-northeast-1' \
    'public.ecr.aws/aws-observability/aws-otel-collector:v0.43.3' \
    '--config=/etc/otel/collector-compose.yaml'
fi
```

### 19. 起動する: eap-lambda-runner

eap-lambda-runner を起動します。郵便箱を見に行き、案内係を通して台所へ伝える係です。
イメージは eap-adot-otel-lambda-runner です。
その前に確認すること: eap-localstack が healthy（最大 200 秒）。
同じネットワークでは lambda-runner という名札で届きます。台帳の名前は eap-lambda-runner です。
元の定義のメモ: lambda-runner — SQS をトリガーに ALB 経由で back を呼ぶ Lambda のスタブ

実行の仕方: 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

成功すると: docker ps に eap-lambda-runner が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

失敗すると: 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

```bash
say "起動する: eap-lambda-runner"
wait_healthy 'eap-localstack' 200
if docker container inspect 'eap-lambda-runner' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-lambda-runner')" = "true" ]; then
    echo "既に動いています: eap-lambda-runner"
  else
    echo "止まっているので起動します: eap-lambda-runner"
    docker start 'eap-lambda-runner'
  fi
else
  docker run \
    --detach \
    --name 'eap-lambda-runner' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'lambda-runner' \
    --env 'SQS_ENDPOINT=http://localstack:4566' \
    --env 'SQS_QUEUE_URL=http://localstack:4566/000000000000/app-queue' \
    --env 'TARGET_URL=http://alb:80/back/api/from-lambda' \
    --env 'POLL_INTERVAL=2' \
    'eap-adot-otel-lambda-runner'
fi
```

### 20. 起動する: eap-back

eap-back を起動します。カウンターの奥の台所です。冷蔵庫とメモ用紙の準備ができてから開店します。
イメージは local/eap-back:dev です。
ホストへ開く扉は 18080:18080 です。
ルートファイルシステムは読み取り専用です。
消える作業場所は /run/eap:uid=6301,gid=6302,mode=0770 です。
その前に確認すること: eap-aurora が healthy（最大 220 秒）。eap-valkey が healthy（最大 140 秒）。eap-adot-collector のプロセスが動いている。
同じネットワークでは back という名札で届きます。台帳の名前は eap-back です。
元の定義のメモ: back — JBoss EAP 8.1 / APP_ROLE=back / service.name = <APP_SERVICE>-back

実行の仕方: 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

成功すると: docker ps に eap-back が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

失敗すると: 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

```bash
say "起動する: eap-back"
wait_healthy 'eap-aurora' 220
wait_healthy 'eap-valkey' 140
wait_running 'eap-adot-collector' 90
if docker container inspect 'eap-back' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-back')" = "true" ]; then
    echo "既に動いています: eap-back"
  else
    echo "止まっているので起動します: eap-back"
    docker start 'eap-back'
  fi
else
  docker run \
    --detach \
    --name 'eap-back' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'back' \
    --read-only \
    --publish '18080:18080' \
    --tmpfs '/run/eap:uid=6301,gid=6302,mode=0770' \
    --env 'TZ=Asia/Tokyo' \
    --env 'JVM_OPTS_MODE=append' \
    --env 'EAP_HTTPS_MODE=remove' \
    --env 'EAP_CLI_STDOUT=echo' \
    --env 'APP_SERVICE=intra-api' \
    --env 'APP_ENV=local' \
    --env 'APP_NAMESPACE=shopdemo' \
    --env 'APP_VERSION=1.0.0' \
    --env 'PEER_NAME_AURORA=' \
    --env 'PEER_NAME_VALKEY=' \
    --env 'PEER_NAME_EC2=' \
    --env 'PEER_NAME_ALB=' \
    --env 'PEER_NAME_EXTERNAL_SLB=' \
    --env 'PEER_NAME_SQS=' \
    --env 'APP_PEER_NAME_MODE=as-is' \
    --env 'APP_EXTRA_RESOURCE_ATTRIBUTES=aws.ecs.cluster.name=shopdemo-local,aws.ecs.task.family=intra-api-local' \
    --env 'APP_SERVICE_EVENT_PACKAGES=' \
    --env 'OTEL_TRACE_WARN_SUPPRESS=resource,context' \
    --env 'OTEL_AGENT_LOG_SUPPRESS_EXTRA=' \
    --env 'APP_PEER_ALB_MODE=upstream' \
    --env 'APP_PEER_DOMAIN_RULES=' \
    --env 'APP_PEER_PORT_RULES=' \
    --env 'APP_PEER_EXTRA_HOSTS=' \
    --env 'APP_PEER_SERVICE_MAPPING=' \
    --env 'APP_CAPTURE_REQUEST_HEADERS_EXTRA=' \
    --env 'APP_CAPTURE_RESPONSE_HEADERS_EXTRA=' \
    --env 'APP_CAPTURE_CLIENT_REQUEST_HEADERS_EXTRA=' \
    --env 'APP_CAPTURE_CLIENT_RESPONSE_HEADERS_EXTRA=' \
    --env 'APP_CAPTURE_REQUEST_PARAMETERS=' \
    --env 'OTEL_EXPORTER_OTLP_ENDPOINT=http://adot-collector:4317' \
    --env 'OTEL_EXPORTER_OTLP_PROTOCOL=grpc' \
    --env 'DB_HOST=aurora' \
    --env 'DB_PORT=3306' \
    --env 'DB_NAME=appdb' \
    --env 'DB_USER=appuser' \
    --env 'DB_PASSWORD=apppassword' \
    --env 'VALKEY_HOST=valkey' \
    --env 'VALKEY_PORT=6379' \
    --env 'REPORT_ALB_HOST=alb' \
    --env 'REPORT_ALB_URL=http://alb:80/report/daily' \
    --env 'EXTERNAL_SLB_HOST=external-slb' \
    --env 'EXTERNAL_SLB_URL=http://external-slb:80/outside/api' \
    --env 'SQS_HOST=localstack' \
    --env 'SQS_ENDPOINT=http://localstack:4566' \
    --env 'SQS_QUEUE_URL=http://localstack:4566/000000000000/app-queue' \
    --env 'AWS_REGION=ap-northeast-1' \
    --env 'AWS_ACCESS_KEY_ID=test' \
    --env 'AWS_SECRET_ACCESS_KEY=test' \
    --env 'APP_ROLE=back' \
    --health-cmd '/opt/app/bin/healthcheck.sh' \
    --health-interval '15s' \
    --health-timeout '5s' \
    --health-start-period '120s' \
    --health-retries 20 \
    'local/eap-back:dev'
fi
```

### 21. 起動する: eap-front

eap-front を起動します。お客さんが最初に話すカウンターです。奥の台所とは、橋の上の名前 back で話します。
イメージは local/eap-front:dev です。
ホストへ開く扉は 8080:8080 です。
ルートファイルシステムは読み取り専用です。
消える作業場所は /run/eap:uid=6301,gid=6302,mode=0770 です。
その前に確認すること: eap-aurora が healthy（最大 220 秒）。eap-valkey が healthy（最大 140 秒）。eap-adot-collector のプロセスが動いている。eap-back が healthy（最大 450 秒）。
同じネットワークでは front という名札で届きます。台帳の名前は eap-front です。
元の定義のメモ: front — JBoss EAP 8.1 / APP_ROLE=front / service.name = <APP_SERVICE>-front

実行の仕方: 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

成功すると: docker ps に eap-front が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

失敗すると: 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

```bash
say "起動する: eap-front"
wait_healthy 'eap-aurora' 220
wait_healthy 'eap-valkey' 140
wait_running 'eap-adot-collector' 90
wait_healthy 'eap-back' 450
if docker container inspect 'eap-front' >/dev/null 2>&1; then
  if [ "$(docker inspect --format '{{.State.Running}}' 'eap-front')" = "true" ]; then
    echo "既に動いています: eap-front"
  else
    echo "止まっているので起動します: eap-front"
    docker start 'eap-front'
  fi
else
  docker run \
    --detach \
    --name 'eap-front' \
    --network 'eap-adot-otel_lab' \
    --network-alias 'front' \
    --read-only \
    --publish '8080:8080' \
    --tmpfs '/run/eap:uid=6301,gid=6302,mode=0770' \
    --env 'TZ=Asia/Tokyo' \
    --env 'JVM_OPTS_MODE=append' \
    --env 'EAP_HTTPS_MODE=remove' \
    --env 'EAP_CLI_STDOUT=echo' \
    --env 'APP_SERVICE=intra-api' \
    --env 'APP_ENV=local' \
    --env 'APP_NAMESPACE=shopdemo' \
    --env 'APP_VERSION=1.0.0' \
    --env 'PEER_NAME_AURORA=' \
    --env 'PEER_NAME_VALKEY=' \
    --env 'PEER_NAME_EC2=' \
    --env 'PEER_NAME_ALB=' \
    --env 'PEER_NAME_EXTERNAL_SLB=' \
    --env 'PEER_NAME_SQS=' \
    --env 'APP_PEER_NAME_MODE=as-is' \
    --env 'APP_EXTRA_RESOURCE_ATTRIBUTES=aws.ecs.cluster.name=shopdemo-local,aws.ecs.task.family=intra-api-local' \
    --env 'APP_SERVICE_EVENT_PACKAGES=' \
    --env 'OTEL_TRACE_WARN_SUPPRESS=resource,context' \
    --env 'OTEL_AGENT_LOG_SUPPRESS_EXTRA=' \
    --env 'APP_PEER_ALB_MODE=upstream' \
    --env 'APP_PEER_DOMAIN_RULES=' \
    --env 'APP_PEER_PORT_RULES=' \
    --env 'APP_PEER_EXTRA_HOSTS=' \
    --env 'APP_PEER_SERVICE_MAPPING=' \
    --env 'APP_CAPTURE_REQUEST_HEADERS_EXTRA=' \
    --env 'APP_CAPTURE_RESPONSE_HEADERS_EXTRA=' \
    --env 'APP_CAPTURE_CLIENT_REQUEST_HEADERS_EXTRA=' \
    --env 'APP_CAPTURE_CLIENT_RESPONSE_HEADERS_EXTRA=' \
    --env 'APP_CAPTURE_REQUEST_PARAMETERS=' \
    --env 'OTEL_EXPORTER_OTLP_ENDPOINT=http://adot-collector:4317' \
    --env 'OTEL_EXPORTER_OTLP_PROTOCOL=grpc' \
    --env 'DB_HOST=aurora' \
    --env 'DB_PORT=3306' \
    --env 'DB_NAME=appdb' \
    --env 'DB_USER=appuser' \
    --env 'DB_PASSWORD=apppassword' \
    --env 'VALKEY_HOST=valkey' \
    --env 'VALKEY_PORT=6379' \
    --env 'REPORT_ALB_HOST=alb' \
    --env 'REPORT_ALB_URL=http://alb:80/report/daily' \
    --env 'EXTERNAL_SLB_HOST=external-slb' \
    --env 'EXTERNAL_SLB_URL=http://external-slb:80/outside/api' \
    --env 'SQS_HOST=localstack' \
    --env 'SQS_ENDPOINT=http://localstack:4566' \
    --env 'SQS_QUEUE_URL=http://localstack:4566/000000000000/app-queue' \
    --env 'AWS_REGION=ap-northeast-1' \
    --env 'AWS_ACCESS_KEY_ID=test' \
    --env 'AWS_SECRET_ACCESS_KEY=test' \
    --env 'APP_ROLE=front' \
    --env 'BACKEND_HOST=back' \
    --env 'BACKEND_URL=http://back:18080' \
    --health-cmd '/opt/app/bin/healthcheck.sh' \
    --health-interval '15s' \
    --health-timeout '5s' \
    --health-start-period '120s' \
    --health-retries 20 \
    'local/eap-front:dev'
fi
```

### 22. 起動結果を確認する

一覧と、ヘルスチェックを持つコンテナの状態を表示します。ここで healthy でなくても、猶予時間のあいだは starting のことがあります。

実行の仕方: 失敗している名前だけ docker logs --tail 100 名前 で見ます。全部を一度に見たいときは docker ps の Status 列を上から見ます。

成功すると: 期待したコンテナ名が並び、依存の末端は healthy か、起動直後なら starting です。

失敗すると: 一覧に名前が無いときは、その起動段階のメッセージとログを見ます。unhealthy なら検査コマンドの失敗です。

```bash
say "起動結果を確認する"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
docker inspect --format '{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{else}}healthcheckなし{{end}}' 'eap-aurora'
docker inspect --format '{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{else}}healthcheckなし{{end}}' 'eap-valkey'
docker inspect --format '{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{else}}healthcheckなし{{end}}' 'eap-localstack'
docker inspect --format '{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{else}}healthcheckなし{{end}}' 'eap-back'
docker inspect --format '{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{else}}healthcheckなし{{end}}' 'eap-front'
echo "ログを追うときは docker logs --tail 50 コンテナ名 を実行します。"
```

## 停止

コンテナとネットワークを消し、ボリュームとイメージは残します。

```bash
#!/bin/bash
# 停止用です。コンテナとネットワークを消し、名前付きボリュームとイメージは残します。
set -euo pipefail
echo "コンテナを止めて捨てます。ボリュームは残します。"
docker rm --force 'eap-front' || true
docker rm --force 'eap-back' || true
docker rm --force 'eap-lambda-runner' || true
docker rm --force 'eap-adot-collector' || true
docker rm --force 'eap-localstack' || true
docker rm --force 'eap-external-slb' || true
docker rm --force 'eap-report-ec2' || true
docker rm --force 'eap-alb' || true
docker rm --force 'eap-valkey' || true
docker rm --force 'eap-aurora' || true
docker rm --force 'eap-jaeger' || true
echo "ネットワークを消します。"
docker network rm 'eap-adot-otel_lab' || true
echo "ボリュームは残しています。データも捨てるときだけ、次を手で実行します。"
echo "  docker volume ls"
echo "停止が終わりました。"
```
