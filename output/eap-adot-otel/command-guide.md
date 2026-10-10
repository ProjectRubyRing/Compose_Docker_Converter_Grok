# eap-adot-otel の Docker コマンド解説

この文書は、Compose がやっていることを Docker Engine のコマンドへ戻し、
その一行が何をしているか、なぜその仕組みが必要になったか、どんな絵で考えればよいかを説明します。
2026年10月時点の Docker Engine 29 系と、2026年5月19日に一般提供が始まった RHEL 9.8 を前提にしています。

## この文書の読み方

最初に全体のたとえを読み、次に RHEL での実行手順、そのあと実行順を上から読みます。
旗（フラグ）の意味は、実行順のあとにまとめています。
歴史が長くなっている用語は『動作原理と歴史』にまとめてあり、各コマンドからはそこへ戻れるようにしてあります。

## 全体像

対象は compose.yaml、プロジェクト名は eap-adot-otel です。起動するコンテナは 11 台で、名前は eap-jaeger、eap-aurora、eap-valkey、eap-alb、eap-report-ec2、eap-external-slb、eap-localstack、eap-adot-collector、eap-lambda-runner、eap-back、eap-front です。Compose は呼ばず、docker network、docker volume、docker pull、docker build、docker run、docker inspect だけで同じ並びを作ります。バインドマウントの SELinux 指定は z です。値は Compose ファイルの ${VAR:-既定} を、変換時に埋めた結果です。変換したマシンの環境変数は、指定しない限り使いません。
変換時の注意: front のビルドに必要なファイルが、コンテキストにありません: dist/app.war / back のビルドに必要なファイルが、コンテキストにありません: dist/app.war / 通常の起動に含めないプロファイル付きサービス: batch-ec2（profile: batch）

## 文化祭の模擬店にたとえると

この環境を、学校の文化祭の模擬店として読むと次のようになります。
校舎は1台の RHEL です。Docker は本部の窓口です。橋ネットワークは、店同士だけが通れる廊下です。
eap-jaeger: 観察ノートを絵にして廊下に貼る掲示板です。本番の X-Ray の代わりに、このマシンの中で見ます。
eap-aurora: 閉めなくても中身が残る冷蔵庫です。データは名前付きボリュームというロッカーに置きます。
eap-valkey: 短い時間だけ覚えておくメモ用紙です。この定義ではロッカーを付けていないので、コンテナを捨てるとメモは消えます。
eap-alb: 正門の案内係です。経路の先頭に応じて、帳票の部屋、台所、カウンターへ通します。
eap-report-ec2: 帳票を作る別室です。観察ノートには自分からは書きません。
eap-external-slb: 学校の外にある窓口の代わりです。この定義では中身は同じ種類の小さな受け答え役です。
eap-localstack: 校内に置いた仮の郵便箱です。本番の SQS の代わりに、キューのやり取りをこのマシンの中で練習します。
eap-adot-collector: 各店から渡される観察メモを受け取り、掲示板へ届ける係です。
eap-lambda-runner: 郵便箱を見に行き、案内係を通して台所へ伝える係です。
eap-back: カウンターの奥の台所です。冷蔵庫とメモ用紙の準備ができてから開店します。
eap-front: お客さんが最初に話すカウンターです。奥の台所とは、橋の上の名前 back で話します。
お客さんが外から入るのは、--publish で開けた正門だけです。店同士の会話は、廊下の名札で足ります。

## RHEL 9.8 で実行する手順

### 1. マシンを確認する

RHEL 9.8 は 2026年5月19日に一般提供が始まり、カーネルは 5.14.0-687.5.1.el9_8 です。確認コマンドは `cat /etc/redhat-release` と `uname -r` です。cgroup は v2、SELinux は通常 Enforcing、ファイアウォールは firewalld、サービス管理は systemd です。

### 2. Docker Engine であることを確認する

`docker version` の Client と Server に Podman と出ないことを見ます。Red Hat が公式にサポートするコンテナエンジンは Podman です。`dnf install docker` だけだと、中身が Podman の互換コマンドになることがあります。この手順が想定するのは、Docker 社のリポジトリから入れた docker-ce です。2026年10月8日時点の公開版は Docker Engine 29.9.0 です。RHEL 9 用の docker-ce リポジトリに 29 系が出ています。デーモンが止まっているときは `systemctl status docker` を見ます。この手順ではインストール自体はしません。

### 3. プロジェクトを置く

変換元のファイル名は compose.yaml です。RHEL 上に、ビルドコンテキストごと同じ並びで置きます。コマンドだけをコピーしても、Dockerfile と設定ファイルが無いとビルドとマウントは失敗します。置いたディレクトリで `bash docker-commands.txt` を実行すると、その場所が PROJECT_ROOT になります。

### 4. 改行を壊さない

行末の \ は『まだ命令が続く』というしるしです。後ろに空白や CR があると、その行で命令が終わります。ファイルは LF で書いてあります。`file docker-commands.txt` が CRLF と言ったら、CR を消してから実行します。

### 5. そのまま実行する

スクリプトは、確認、橋、ロッカー、公開イメージの取得、ビルド、依存順の起動、状態の表示、の順です。既にあるネットワーク、ボリューム、イメージ、動いているコンテナは作り直しません。最後に exit 0 があるので、ファイル全体を実行しても停止コマンドには入りません。

### 6. 材料が無いときの意味

ビルドコンテキストを読んだ結果、次のファイルが未配置なら、そのイメージを焼く段階で止まります。イメージを既に持っているときは、そのビルドは飛ばします。
back、front が FROM app-eap-base:1.0 しているため、サービス定義の外にある Containerfile を先に焼きます。FROM registry.access.redhat.com/ubi9/ubi:9.8 -> registry.access.redhat.com/ubi9/ubi:9.8 -> registry.access.redhat.com/ubi9/ubi:9.8 -> server-zip（このファイルの中の前の段）。ENTRYPOINT ["/opt/app/bin/entrypoint.sh"]。CMD ["run-server"]。USER 6301:6302。WORKDIR /run/eap。未配置の COPY: vendor/jboss-eap-8.1.0.zip
FROM app-eap-base:1.0。USER 6301:6302。WORKDIR /run/eap。EXPOSE 18080。イメージ側の HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=5      CMD /opt/app/bin/healthcheck.sh 。Compose の healthcheck がある場合は、実行時フラグが上書きします。。未配置の COPY: dist/app.war
FROM app-eap-base:1.0。USER 6301:6302。WORKDIR /run/eap。EXPOSE 8080。イメージ側の HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=5      CMD /opt/app/bin/healthcheck.sh 。Compose の healthcheck がある場合は、実行時フラグが上書きします。。未配置の COPY: dist/app.war

### 7. 止める

docker-commands.txt の exit 0 より下、または command-guide の停止節を実行します。コンテナとネットワークは消えます。名前付きボリュームは残るので、データベースの中身は残ります。

## 実行順

### 1. 実行前の確認

Docker Engine に接続できること、プロジェクトの場所、SELinux の状態を確認します。このあとで使う待ち関数も、ここで定義します。

**どう実行するか。** RHEL 上で、プロジェクトのディレクトリに入って bash docker-commands.txt と実行します。別の場所からなら PROJECT_ROOT=/実際のパス bash docker-commands.txt です。

**成功すると見えるもの。** クライアントとサーバの版、SELinux の状態が表示され、次の段階へ進みます。

**失敗すると見えるもの。** docker が無い、デーモンが止まっている、Podman 互換である、PROJECT_ROOT が違う、のいずれかです。

**動作原理。** 窓口が本当に Docker Engine か、材料の置いてあるディレクトリはどこか、を最初に固定します。

**頭の中の絵。** 文化祭の朝に、本部の窓口が開いているか、模擬店の段ボールはどの教室か、を確認する段階です。

**歴史と背景。** 手順を小さな命令に分ける書き方は、Bourne shell の行継続と、失敗で止める set -e が土台です。Compose が隠していた確認を、先頭に戻しています。

**なぜ必要になったか。** 途中で失敗したときに、原因が準備不足なのか命令の中身なのかを分けられるようにするためです。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `set -euo pipefail` | （なし） | 失敗したらすぐ止まり、未設定の変数もエラーにします。 |
| `wait_healthy` | 名前と秒数 | docker inspect で健康状態を見て、healthy まで待つか unhealthy で止まります。 |
| `wait_running` | 名前と秒数 | コンテナのプロセスが動き始めたことを確認します。 |

### 2. ネットワーク eap-adot-otel_lab

コンテナが名前で呼び合うための橋を用意します。Compose 上の名前は lab、Docker 上の名前は eap-adot-otel_lab です。プロジェクト名とネットワーク名のあいだはアンダースコアです。

**どう実行するか。** この段階だけを再実行しても、既にあれば作り直しません。消すときは停止手順のあとで docker network rm を使います。

**成功すると見えるもの。** docker network inspect が名前、ドライバ、サブネットを表示できる状態です。

**失敗すると見えるもの。** 同名の別ドライバが残っている、権限が無い、指定サブネットが重なっている、のいずれかです。

**動作原理。** 同じ橋にいるコンテナだけが、サービス名の名札で互いに届きます。外の世界とはまだつながっていません。

**頭の中の絵。** 模擬店のあいだに、校舎の中だけの長い机を出す段階です。

**歴史と背景。** 2015年11月の Docker 1.9 まで、コンテナ同士は --link で結んでいました。名前の付く橋が入って、Compose のサービス名が使えるようになりました。

**なぜ必要になったか。** コンテナは最初、互いの名前を知りません。名前で呼べる範囲を先に作らないと、アプリが接続先を見つけられません。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `--driver` | bridge | --driver を指定します。 |
| `ネットワーク名` | eap-adot-otel_lab | 作成する橋の名前は eap-adot-otel_lab です。 |

### 3. ボリューム eap-adot-otel_aurora-data

コンテナを消しても残る保存場所 eap-adot-otel_aurora-data を作ります。中にデータベースのファイルが入ります。停止手順では、このロッカーは消しません。

**どう実行するか。** 中身を捨てるときだけ、コンテナを止めたあとに docker volume rm を別に実行します。

**成功すると見えるもの。** docker volume inspect に Name と Mountpoint が出ます。

**失敗すると見えるもの。** 同名の壊れたボリュームがある、ディスクが足りない、権限が無い、のいずれかです。

**動作原理。** コンテナの書き込み層はコンテナと一緒に消えます。残したいデータは、最初から外のロッカーへ置きます。

**頭の中の絵。** 冷蔵庫の中身を、お店の机ではなく校舎のロッカーへ置く段階です。

**歴史と背景。** コンテナの層は消えるため、2014年から2015年にかけて名前付きボリュームが整理されました。データベースを残す場所が、コンテナの寿命から独立しました。

**なぜ必要になったか。** コンテナを作り直すたびにデータベースが空になると、起動のたびに初期データからやり直しになるためです。

```bash
say "データを残すロッカーを作る: eap-adot-otel_aurora-data"
if docker volume inspect 'eap-adot-otel_aurora-data' >/dev/null 2>&1; then
  echo "ボリュームは既にあります: eap-adot-otel_aurora-data"
else
  docker volume create \
    'eap-adot-otel_aurora-data'
fi
```

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `docker volume create` | eap-adot-otel_aurora-data | Docker 管理下の名前付き保存場所を作ります。 |

### 4. 公開イメージを取り寄せる

ビルドせずに image だけが書いてあるサービスについて、同じタグが手元に無いときだけ docker pull します。

**どう実行するか。** 回線と、必要なら HTTPS_PROXY を用意してから実行します。既にあれば取り寄せません。

**成功すると見えるもの。** 各イメージに対して『手元にあります』か、pull の完了メッセージが出ます。

**失敗すると見えるもの。** 名前解決、プロキシ、認証、ディスク不足です。メッセージの画像名を見て、そのレジストリだけを確認します。

**動作原理。** 完成済みのカードは倉庫から取り、このプロジェクトで焼くカードは次の段階で作ります。

**頭の中の絵。** 既製品の冷蔵庫と掲示板を、カタログの番号で取り寄せる段階です。

**歴史と背景。** 2014年の Docker Hub 以降、完成品のイメージを名前で取り寄せるのが普通になりました。タグは動き得るので、再現が必要ならダイジェストで固定します。

**なぜ必要になったか。** MySQL や Jaeger を毎回ソースから作ると、この環境の目的であるアプリの確認にたどり着けないためです。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `docker pull` | jaegertracing/all-in-one:1.62.0 | jaeger が使う jaegertracing/all-in-one:1.62.0 を、手元に無いときだけ取り寄せます。 |
| `docker pull` | mysql:8.4 | aurora が使う mysql:8.4 を、手元に無いときだけ取り寄せます。 |
| `docker pull` | valkey/valkey:8-alpine | valkey が使う valkey/valkey:8-alpine を、手元に無いときだけ取り寄せます。 |
| `docker pull` | localstack/localstack:3.8 | localstack が使う localstack/localstack:3.8 を、手元に無いときだけ取り寄せます。 |
| `docker pull` | public.ecr.aws/aws-observability/aws-otel-collector:v0.43.3 | adot-collector が使う public.ecr.aws/aws-observability/aws-otel-collector:v0.43.3 を、手元に無いときだけ取り寄せます。 |

### 5. 前提イメージを作る: app-eap-base:1.0

back、front が FROM app-eap-base:1.0 しているため、サービス定義の外にある Containerfile を先に焼きます。 外から取る土台は registry.access.redhat.com/ubi9/ubi:9.8 です。 今の作業ツリーでは次が未配置です: vendor/jboss-eap-8.1.0.zip。イメージが既にある場合はビルドを飛ばします。

**どう実行するか。** プロジェクトディレクトリの中身が、RHEL 上の PROJECT_ROOT と同じ配置になっている必要があります。カードが既にあれば、この段階は確認だけです。

**成功すると見えるもの。** docker image inspect が成功し、次の段階へ進みます。

**失敗すると見えるもの。** COPY の材料が無い、FROM の土台が無い、プロキシで倉庫へ届かない、ディスク不足、のいずれかです。

**動作原理。** レシピと段ボールから、読み取り専用のカードを焼きます。コンテナはこの時点ではまだ開きません。

**頭の中の絵。** 材料を厨房へ渡し、レシピどおりにカードを焼く段階です。

**歴史と背景。** Dockerfile は Docker の初期からあります。直列で遅かったビルドは、2017年の BuildKit と、2023年の Engine 23 で標準になった並列ビルドへ変わりました。

**なぜ必要になったか。** 実行のたびに同じインストールを繰り返さず、焼いたカードを名前で開けるようにするためです。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `--file` | base/Containerfile | 段ボールの中の、どのレシピを読むかを指定します。 |
| `--tag` | app-eap-base:1.0 | できたイメージに、この名前と付箋を付けます。 |
| `コンテキスト` | . | ビルドに渡すファイルの範囲です。 |

### 6. イメージを作る: alb

サービス alb の build です。 外から取る土台は registry.access.redhat.com/ubi9/ubi-minimal:9.5 です。

**どう実行するか。** プロジェクトディレクトリの中身が、RHEL 上の PROJECT_ROOT と同じ配置になっている必要があります。カードが既にあれば、この段階は確認だけです。

**成功すると見えるもの。** docker image inspect が成功し、次の段階へ進みます。

**失敗すると見えるもの。** COPY の材料が無い、FROM の土台が無い、プロキシで倉庫へ届かない、ディスク不足、のいずれかです。

**動作原理。** レシピと段ボールから、読み取り専用のカードを焼きます。コンテナはこの時点ではまだ開きません。

**頭の中の絵。** 材料を厨房へ渡し、レシピどおりにカードを焼く段階です。

**歴史と背景。** 同じ種類の命令です。違うのは名前、対象、依存です。詳しい歴史は『動作原理と歴史』の同じ用語を読んでください。

**なぜ必要になったか。** 実行のたびに同じインストールを繰り返さず、焼いたカードを名前で開けるようにするためです。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `--file` | sim/alb/Dockerfile | 段ボールの中の、どのレシピを読むかを指定します。 |
| `--tag` | eap-adot-otel-alb | できたイメージに、この名前と付箋を付けます。 |
| `コンテキスト` | sim/alb | ビルドに渡すファイルの範囲です。 |

### 7. イメージを作る: report-ec2, external-slb

サービス report-ec2, external-slb の build です。 外から取る土台は registry.access.redhat.com/ubi9/ubi-minimal:9.5 です。

**どう実行するか。** プロジェクトディレクトリの中身が、RHEL 上の PROJECT_ROOT と同じ配置になっている必要があります。カードが既にあれば、この段階は確認だけです。

**成功すると見えるもの。** docker image inspect が成功し、次の段階へ進みます。

**失敗すると見えるもの。** COPY の材料が無い、FROM の土台が無い、プロキシで倉庫へ届かない、ディスク不足、のいずれかです。

**動作原理。** レシピと段ボールから、読み取り専用のカードを焼きます。コンテナはこの時点ではまだ開きません。

**頭の中の絵。** 材料を厨房へ渡し、レシピどおりにカードを焼く段階です。

**歴史と背景。** 同じ種類の命令です。違うのは名前、対象、依存です。詳しい歴史は『動作原理と歴史』の同じ用語を読んでください。

**なぜ必要になったか。** 実行のたびに同じインストールを繰り返さず、焼いたカードを名前で開けるようにするためです。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `--file` | sim/report-ec2/Dockerfile | 段ボールの中の、どのレシピを読むかを指定します。 |
| `--tag` | eap-adot-otel-report-ec2 | できたイメージに、この名前と付箋を付けます。 |
| `コンテキスト` | sim/report-ec2 | ビルドに渡すファイルの範囲です。 |
| `docker tag` | eap-adot-otel-report-ec2 -> eap-adot-otel-external-slb | 同じカードに、別の付箋を付けます。中身のビルドは1回です。 |

### 8. イメージを作る: lambda-runner

サービス lambda-runner の build です。 外から取る土台は registry.access.redhat.com/ubi9/ubi-minimal:9.5 です。

**どう実行するか。** プロジェクトディレクトリの中身が、RHEL 上の PROJECT_ROOT と同じ配置になっている必要があります。カードが既にあれば、この段階は確認だけです。

**成功すると見えるもの。** docker image inspect が成功し、次の段階へ進みます。

**失敗すると見えるもの。** COPY の材料が無い、FROM の土台が無い、プロキシで倉庫へ届かない、ディスク不足、のいずれかです。

**動作原理。** レシピと段ボールから、読み取り専用のカードを焼きます。コンテナはこの時点ではまだ開きません。

**頭の中の絵。** 材料を厨房へ渡し、レシピどおりにカードを焼く段階です。

**歴史と背景。** 同じ種類の命令です。違うのは名前、対象、依存です。詳しい歴史は『動作原理と歴史』の同じ用語を読んでください。

**なぜ必要になったか。** 実行のたびに同じインストールを繰り返さず、焼いたカードを名前で開けるようにするためです。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `--file` | sim/lambda/Dockerfile | 段ボールの中の、どのレシピを読むかを指定します。 |
| `--tag` | eap-adot-otel-lambda-runner | できたイメージに、この名前と付箋を付けます。 |
| `コンテキスト` | sim/lambda | ビルドに渡すファイルの範囲です。 |

### 9. イメージを作る: back

サービス back の build です。 外から取る土台は app-eap-base:1.0 です。 今の作業ツリーでは次が未配置です: dist/app.war。イメージが既にある場合はビルドを飛ばします。

**どう実行するか。** プロジェクトディレクトリの中身が、RHEL 上の PROJECT_ROOT と同じ配置になっている必要があります。カードが既にあれば、この段階は確認だけです。

**成功すると見えるもの。** docker image inspect が成功し、次の段階へ進みます。

**失敗すると見えるもの。** COPY の材料が無い、FROM の土台が無い、プロキシで倉庫へ届かない、ディスク不足、のいずれかです。

**動作原理。** レシピと段ボールから、読み取り専用のカードを焼きます。コンテナはこの時点ではまだ開きません。

**頭の中の絵。** 材料を厨房へ渡し、レシピどおりにカードを焼く段階です。

**歴史と背景。** 同じ種類の命令です。違うのは名前、対象、依存です。詳しい歴史は『動作原理と歴史』の同じ用語を読んでください。

**なぜ必要になったか。** 実行のたびに同じインストールを繰り返さず、焼いたカードを名前で開けるようにするためです。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `--file` | back/Containerfile | 段ボールの中の、どのレシピを読むかを指定します。 |
| `--tag` | local/eap-back:dev | できたイメージに、この名前と付箋を付けます。 |
| `--build-arg` | BASE_IMAGE=app-eap-base:1.0 | レシピの ARG を、この値で上書きします。 |
| `--build-arg` | APP_SOURCE=dist/app.war | レシピの ARG を、この値で上書きします。 |
| `コンテキスト` | . | ビルドに渡すファイルの範囲です。 |

### 10. イメージを作る: front

サービス front の build です。 外から取る土台は app-eap-base:1.0 です。 今の作業ツリーでは次が未配置です: dist/app.war。イメージが既にある場合はビルドを飛ばします。

**どう実行するか。** プロジェクトディレクトリの中身が、RHEL 上の PROJECT_ROOT と同じ配置になっている必要があります。カードが既にあれば、この段階は確認だけです。

**成功すると見えるもの。** docker image inspect が成功し、次の段階へ進みます。

**失敗すると見えるもの。** COPY の材料が無い、FROM の土台が無い、プロキシで倉庫へ届かない、ディスク不足、のいずれかです。

**動作原理。** レシピと段ボールから、読み取り専用のカードを焼きます。コンテナはこの時点ではまだ開きません。

**頭の中の絵。** 材料を厨房へ渡し、レシピどおりにカードを焼く段階です。

**歴史と背景。** 同じ種類の命令です。違うのは名前、対象、依存です。詳しい歴史は『動作原理と歴史』の同じ用語を読んでください。

**なぜ必要になったか。** 実行のたびに同じインストールを繰り返さず、焼いたカードを名前で開けるようにするためです。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `--file` | front/Containerfile | 段ボールの中の、どのレシピを読むかを指定します。 |
| `--tag` | local/eap-front:dev | できたイメージに、この名前と付箋を付けます。 |
| `--build-arg` | BASE_IMAGE=app-eap-base:1.0 | レシピの ARG を、この値で上書きします。 |
| `--build-arg` | APP_SOURCE=dist/app.war | レシピの ARG を、この値で上書きします。 |
| `コンテキスト` | . | ビルドに渡すファイルの範囲です。 |

### 11. 起動する: eap-jaeger

eap-jaeger を起動します。観察ノートを絵にして廊下に貼る掲示板です。本番の X-Ray の代わりに、このマシンの中で見ます。
イメージは jaegertracing/all-in-one:1.62.0 です。
ホストへ開く扉は 16686:16686 です。
同じネットワークでは jaeger という名札で届きます。台帳の名前は eap-jaeger です。
元の定義のメモ: jaeger — ローカルの可視化先 (本番は X-Ray)

**どう実行するか。** 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

**成功すると見えるもの。** docker ps に eap-jaeger が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

**失敗すると見えるもの。** 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

**動作原理。** カードの上に書き込み層を足し、橋とロッカーと扉とポケットメモを取り付けて、プロセスを開始します。

**頭の中の絵。** 観察ノートを絵にして廊下に貼る掲示板です。本番の X-Ray の代わりに、このマシンの中で見ます。

**歴史と背景。** docker run は『カードを開く』窓口です。2016年の HEALTHCHECK と、実行時の --health-* により、イメージの自己申告と運用の猶予を分けられるようになりました。

**なぜ必要になったか。** イメージは静止したカードなので、名前と接続と環境を付けて、初めてプロセスとして動き始めます。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `--detach` | （なし） | コンテナを背景で動かし、コマンド自体はすぐに戻します。 |
| `--name` | eap-jaeger | Docker がこのコンテナを区別する名前を eap-jaeger にします。 |
| `--network` | eap-adot-otel_lab | コンテナをネットワーク eap-adot-otel_lab に接続します。 |
| `--network-alias` | jaeger | 同じネットワークの中で、jaeger という名札でも届くようにします。 |
| `--publish` | 16686:16686 | ホストとコンテナのポートをつなぎます。対応は 16686:16686 です。 |
| `--env` | 1 個 | 環境変数を1行に1つ渡します。各値の意味は『環境変数』シートです。 |

### 12. 起動する: eap-aurora

eap-aurora を起動します。閉めなくても中身が残る冷蔵庫です。データは名前付きボリュームというロッカーに置きます。
イメージは mysql:8.4 です。
同じネットワークでは aurora という名札で届きます。台帳の名前は eap-aurora です。
イメージ名の後ろの引数で、起動コマンドを差し替えます。
元の定義のメモ: aurora — Aurora Serverless v2 (MySQL 8.4 互換) のローカル代替

**どう実行するか。** 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

**成功すると見えるもの。** docker ps に eap-aurora が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

**失敗すると見えるもの。** 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

**動作原理。** カードの上に書き込み層を足し、橋とロッカーと扉とポケットメモを取り付けて、プロセスを開始します。

**頭の中の絵。** 閉めなくても中身が残る冷蔵庫です。データは名前付きボリュームというロッカーに置きます。

**歴史と背景。** 同じ種類の命令です。違うのは名前、対象、依存です。詳しい歴史は『動作原理と歴史』の同じ用語を読んでください。

**なぜ必要になったか。** イメージは静止したカードなので、名前と接続と環境を付けて、初めてプロセスとして動き始めます。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `--detach` | （なし） | コンテナを背景で動かし、コマンド自体はすぐに戻します。 |
| `--name` | eap-aurora | Docker がこのコンテナを区別する名前を eap-aurora にします。 |
| `--network` | eap-adot-otel_lab | コンテナをネットワーク eap-adot-otel_lab に接続します。 |
| `--network-alias` | aurora | 同じネットワークの中で、aurora という名札でも届くようにします。 |
| `--volume` | eap-adot-otel_aurora-data:/var/lib/mysql | 保存場所を取り付けます。指定は eap-adot-otel_aurora-data:/var/lib/mysql です。 |
| `--env` | 5 個 | 環境変数を1行に1つ渡します。各値の意味は『環境変数』シートです。 |
| `--health-cmd` | mysqladmin ping -h 127.0.0.1 -u root -p${MYSQL_ROOT_PASSWORD} --silent | 健康を聞くコマンドを mysqladmin ping -h 127.0.0.1 -u root -p${MYSQL_ROOT_PASSWORD} --silent にします。 |
| `--health-interval` | 10s | 健康を聞く間隔を 10s にします。 |
| `--health-timeout` | 5s | 1回の質問の制限時間を 5s にします。 |
| `--health-start-period` | 40s | 起動直後の猶予を 40s にします。 |
| `--health-retries` | 15 | 連続失敗の上限を 15 回にします。 |

### 13. 起動する: eap-valkey

eap-valkey を起動します。短い時間だけ覚えておくメモ用紙です。この定義ではロッカーを付けていないので、コンテナを捨てるとメモは消えます。
イメージは valkey/valkey:8-alpine です。
同じネットワークでは valkey という名札で届きます。台帳の名前は eap-valkey です。
元の定義のメモ: valkey — ElastiCache for Valkey のローカル代替

**どう実行するか。** 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

**成功すると見えるもの。** docker ps に eap-valkey が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

**失敗すると見えるもの。** 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

**動作原理。** カードの上に書き込み層を足し、橋とロッカーと扉とポケットメモを取り付けて、プロセスを開始します。

**頭の中の絵。** 短い時間だけ覚えておくメモ用紙です。この定義ではロッカーを付けていないので、コンテナを捨てるとメモは消えます。

**歴史と背景。** 同じ種類の命令です。違うのは名前、対象、依存です。詳しい歴史は『動作原理と歴史』の同じ用語を読んでください。

**なぜ必要になったか。** イメージは静止したカードなので、名前と接続と環境を付けて、初めてプロセスとして動き始めます。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `--detach` | （なし） | コンテナを背景で動かし、コマンド自体はすぐに戻します。 |
| `--name` | eap-valkey | Docker がこのコンテナを区別する名前を eap-valkey にします。 |
| `--network` | eap-adot-otel_lab | コンテナをネットワーク eap-adot-otel_lab に接続します。 |
| `--network-alias` | valkey | 同じネットワークの中で、valkey という名札でも届くようにします。 |
| `--health-cmd` | valkey-cli ping | 健康を聞くコマンドを valkey-cli ping にします。 |
| `--health-interval` | 10s | 健康を聞く間隔を 10s にします。 |
| `--health-timeout` | 3s | 1回の質問の制限時間を 3s にします。 |
| `--health-start-period` | 10s | 起動直後の猶予を 10s にします。 |
| `--health-retries` | 10 | 連続失敗の上限を 10 回にします。 |

### 14. 起動する: eap-alb

eap-alb を起動します。正門の案内係です。経路の先頭に応じて、帳票の部屋、台所、カウンターへ通します。
イメージは eap-adot-otel-alb です。
ホストへ開く扉は 8081:80 です。
同じネットワークでは alb という名札で届きます。台帳の名前は eap-alb です。
元の定義のメモ: alb — ALB のトレース関連挙動 (X-Amzn-Trace-Id の採番/透過) を再現

**どう実行するか。** 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

**成功すると見えるもの。** docker ps に eap-alb が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

**失敗すると見えるもの。** 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

**動作原理。** カードの上に書き込み層を足し、橋とロッカーと扉とポケットメモを取り付けて、プロセスを開始します。

**頭の中の絵。** 正門の案内係です。経路の先頭に応じて、帳票の部屋、台所、カウンターへ通します。

**歴史と背景。** 同じ種類の命令です。違うのは名前、対象、依存です。詳しい歴史は『動作原理と歴史』の同じ用語を読んでください。

**なぜ必要になったか。** イメージは静止したカードなので、名前と接続と環境を付けて、初めてプロセスとして動き始めます。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `--detach` | （なし） | コンテナを背景で動かし、コマンド自体はすぐに戻します。 |
| `--name` | eap-alb | Docker がこのコンテナを区別する名前を eap-alb にします。 |
| `--network` | eap-adot-otel_lab | コンテナをネットワーク eap-adot-otel_lab に接続します。 |
| `--network-alias` | alb | 同じネットワークの中で、alb という名札でも届くようにします。 |
| `--publish` | 8081:80 | ホストとコンテナのポートをつなぎます。対応は 8081:80 です。 |
| `--env` | 2 個 | 環境変数を1行に1つ渡します。各値の意味は『環境変数』シートです。 |

### 15. 起動する: eap-report-ec2

eap-report-ec2 を起動します。帳票を作る別室です。観察ノートには自分からは書きません。
イメージは eap-adot-otel-report-ec2 です。
同じネットワークでは report-ec2 という名札で届きます。台帳の名前は eap-report-ec2 です。
元の定義のメモ: report-ec2 — 帳票 EC2 サーバ (あえて計装しない)

**どう実行するか。** 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

**成功すると見えるもの。** docker ps に eap-report-ec2 が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

**失敗すると見えるもの。** 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

**動作原理。** カードの上に書き込み層を足し、橋とロッカーと扉とポケットメモを取り付けて、プロセスを開始します。

**頭の中の絵。** 帳票を作る別室です。観察ノートには自分からは書きません。

**歴史と背景。** 同じ種類の命令です。違うのは名前、対象、依存です。詳しい歴史は『動作原理と歴史』の同じ用語を読んでください。

**なぜ必要になったか。** イメージは静止したカードなので、名前と接続と環境を付けて、初めてプロセスとして動き始めます。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `--detach` | （なし） | コンテナを背景で動かし、コマンド自体はすぐに戻します。 |
| `--name` | eap-report-ec2 | Docker がこのコンテナを区別する名前を eap-report-ec2 にします。 |
| `--network` | eap-adot-otel_lab | コンテナをネットワーク eap-adot-otel_lab に接続します。 |
| `--network-alias` | report-ec2 | 同じネットワークの中で、report-ec2 という名札でも届くようにします。 |
| `--env` | 3 個 | 環境変数を1行に1つ渡します。各値の意味は『環境変数』シートです。 |

### 16. 起動する: eap-external-slb

eap-external-slb を起動します。学校の外にある窓口の代わりです。この定義では中身は同じ種類の小さな受け答え役です。
イメージは eap-adot-otel-external-slb です。
同じネットワークでは external-slb という名札で届きます。台帳の名前は eap-external-slb です。
元の定義のメモ: external-slb — 外部ロードバランサー経由の VPC 外通信先 (計装しない)

**どう実行するか。** 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

**成功すると見えるもの。** docker ps に eap-external-slb が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

**失敗すると見えるもの。** 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

**動作原理。** カードの上に書き込み層を足し、橋とロッカーと扉とポケットメモを取り付けて、プロセスを開始します。

**頭の中の絵。** 学校の外にある窓口の代わりです。この定義では中身は同じ種類の小さな受け答え役です。

**歴史と背景。** 同じ種類の命令です。違うのは名前、対象、依存です。詳しい歴史は『動作原理と歴史』の同じ用語を読んでください。

**なぜ必要になったか。** イメージは静止したカードなので、名前と接続と環境を付けて、初めてプロセスとして動き始めます。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `--detach` | （なし） | コンテナを背景で動かし、コマンド自体はすぐに戻します。 |
| `--name` | eap-external-slb | Docker がこのコンテナを区別する名前を eap-external-slb にします。 |
| `--network` | eap-adot-otel_lab | コンテナをネットワーク eap-adot-otel_lab に接続します。 |
| `--network-alias` | external-slb | 同じネットワークの中で、external-slb という名札でも届くようにします。 |
| `--env` | 3 個 | 環境変数を1行に1つ渡します。各値の意味は『環境変数』シートです。 |

### 17. 起動する: eap-localstack

eap-localstack を起動します。校内に置いた仮の郵便箱です。本番の SQS の代わりに、キューのやり取りをこのマシンの中で練習します。
イメージは localstack/localstack:3.8 です。
ホストへ開く扉は 4566:4566 です。
同じネットワークでは localstack という名札で届きます。台帳の名前は eap-localstack です。
元の定義のメモ: localstack — SQS のローカル代替

**どう実行するか。** 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

**成功すると見えるもの。** docker ps に eap-localstack が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

**失敗すると見えるもの。** 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

**動作原理。** カードの上に書き込み層を足し、橋とロッカーと扉とポケットメモを取り付けて、プロセスを開始します。

**頭の中の絵。** 校内に置いた仮の郵便箱です。本番の SQS の代わりに、キューのやり取りをこのマシンの中で練習します。

**歴史と背景。** 同じ種類の命令です。違うのは名前、対象、依存です。詳しい歴史は『動作原理と歴史』の同じ用語を読んでください。

**なぜ必要になったか。** イメージは静止したカードなので、名前と接続と環境を付けて、初めてプロセスとして動き始めます。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `--detach` | （なし） | コンテナを背景で動かし、コマンド自体はすぐに戻します。 |
| `--name` | eap-localstack | Docker がこのコンテナを区別する名前を eap-localstack にします。 |
| `--network` | eap-adot-otel_lab | コンテナをネットワーク eap-adot-otel_lab に接続します。 |
| `--network-alias` | localstack | 同じネットワークの中で、localstack という名札でも届くようにします。 |
| `--publish` | 4566:4566 | ホストとコンテナのポートをつなぎます。対応は 4566:4566 です。 |
| `--volume` | ${PROJECT_ROOT}/scripts/localstack-init:/etc/localstack/init/ready.d:ro,z | 保存場所を取り付けます。指定は ${PROJECT_ROOT}/scripts/localstack-init:/etc/localstack/init/ready.d:ro,z です。 |
| `--env` | 2 個 | 環境変数を1行に1つ渡します。各値の意味は『環境変数』シートです。 |
| `--health-cmd` | curl -sf http://localhost:4566/_localstack/health \|\| exit 1 | 健康を聞くコマンドを curl -sf http://localhost:4566/_localstack/health \|\| exit 1 にします。 |
| `--health-interval` | 10s | 健康を聞く間隔を 10s にします。 |
| `--health-timeout` | 5s | 1回の質問の制限時間を 5s にします。 |
| `--health-start-period` | 20s | 起動直後の猶予を 20s にします。 |
| `--health-retries` | 15 | 連続失敗の上限を 15 回にします。 |

### 18. 起動する: eap-adot-collector

eap-adot-collector を起動します。各店から渡される観察メモを受け取り、掲示板へ届ける係です。
イメージは public.ecr.aws/aws-observability/aws-otel-collector:v0.43.3 です。
ホストへ開く扉は 4317:4317、4318:4318、13133:13133 です。
その前に確認すること: eap-jaeger のプロセスが動いている。
同じネットワークでは adot-collector という名札で届きます。台帳の名前は eap-adot-collector です。
イメージ名の後ろの引数で、起動コマンドを差し替えます。
元の定義のメモ: adot-collector — ADOT Collector サイドカー

**どう実行するか。** 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

**成功すると見えるもの。** docker ps に eap-adot-collector が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

**失敗すると見えるもの。** 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

**動作原理。** カードの上に書き込み層を足し、橋とロッカーと扉とポケットメモを取り付けて、プロセスを開始します。

**頭の中の絵。** 各店から渡される観察メモを受け取り、掲示板へ届ける係です。

**歴史と背景。** 同じ種類の命令です。違うのは名前、対象、依存です。詳しい歴史は『動作原理と歴史』の同じ用語を読んでください。

**なぜ必要になったか。** イメージは静止したカードなので、名前と接続と環境を付けて、初めてプロセスとして動き始めます。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `--detach` | （なし） | コンテナを背景で動かし、コマンド自体はすぐに戻します。 |
| `--name` | eap-adot-collector | Docker がこのコンテナを区別する名前を eap-adot-collector にします。 |
| `--network` | eap-adot-otel_lab | コンテナをネットワーク eap-adot-otel_lab に接続します。 |
| `--network-alias` | adot-collector | 同じネットワークの中で、adot-collector という名札でも届くようにします。 |
| `--publish` | 4317:4317 | ホストとコンテナのポートをつなぎます。対応は 4317:4317 です。 |
| `--publish` | 4318:4318 | ホストとコンテナのポートをつなぎます。対応は 4318:4318 です。 |
| `--publish` | 13133:13133 | ホストとコンテナのポートをつなぎます。対応は 13133:13133 です。 |
| `--volume` | ${PROJECT_ROOT}/otel/collector-compose.yaml:/etc/otel/collector-compose.yaml:ro,z | 保存場所を取り付けます。指定は ${PROJECT_ROOT}/otel/collector-compose.yaml:/etc/otel/collector-compose.yaml:ro,z です。 |
| `--env` | 1 個 | 環境変数を1行に1つ渡します。各値の意味は『環境変数』シートです。 |

### 19. 起動する: eap-lambda-runner

eap-lambda-runner を起動します。郵便箱を見に行き、案内係を通して台所へ伝える係です。
イメージは eap-adot-otel-lambda-runner です。
その前に確認すること: eap-localstack が healthy（最大 200 秒）。
同じネットワークでは lambda-runner という名札で届きます。台帳の名前は eap-lambda-runner です。
元の定義のメモ: lambda-runner — SQS をトリガーに ALB 経由で back を呼ぶ Lambda のスタブ

**どう実行するか。** 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

**成功すると見えるもの。** docker ps に eap-lambda-runner が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

**失敗すると見えるもの。** 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

**動作原理。** カードの上に書き込み層を足し、橋とロッカーと扉とポケットメモを取り付けて、プロセスを開始します。

**頭の中の絵。** 郵便箱を見に行き、案内係を通して台所へ伝える係です。

**歴史と背景。** 同じ種類の命令です。違うのは名前、対象、依存です。詳しい歴史は『動作原理と歴史』の同じ用語を読んでください。

**なぜ必要になったか。** イメージは静止したカードなので、名前と接続と環境を付けて、初めてプロセスとして動き始めます。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `--detach` | （なし） | コンテナを背景で動かし、コマンド自体はすぐに戻します。 |
| `--name` | eap-lambda-runner | Docker がこのコンテナを区別する名前を eap-lambda-runner にします。 |
| `--network` | eap-adot-otel_lab | コンテナをネットワーク eap-adot-otel_lab に接続します。 |
| `--network-alias` | lambda-runner | 同じネットワークの中で、lambda-runner という名札でも届くようにします。 |
| `--env` | 4 個 | 環境変数を1行に1つ渡します。各値の意味は『環境変数』シートです。 |

### 20. 起動する: eap-back

eap-back を起動します。カウンターの奥の台所です。冷蔵庫とメモ用紙の準備ができてから開店します。
イメージは local/eap-back:dev です。
ホストへ開く扉は 18080:18080 です。
ルートファイルシステムは読み取り専用です。
消える作業場所は /run/eap:uid=6301,gid=6302,mode=0770 です。
その前に確認すること: eap-aurora が healthy（最大 220 秒）。eap-valkey が healthy（最大 140 秒）。eap-adot-collector のプロセスが動いている。
同じネットワークでは back という名札で届きます。台帳の名前は eap-back です。
元の定義のメモ: back — JBoss EAP 8.1 / APP_ROLE=back / service.name = <APP_SERVICE>-back

**どう実行するか。** 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

**成功すると見えるもの。** docker ps に eap-back が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

**失敗すると見えるもの。** 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

**動作原理。** カードの上に書き込み層を足し、橋とロッカーと扉とポケットメモを取り付けて、プロセスを開始します。

**頭の中の絵。** カウンターの奥の台所です。冷蔵庫とメモ用紙の準備ができてから開店します。

**歴史と背景。** 同じ種類の命令です。違うのは名前、対象、依存です。詳しい歴史は『動作原理と歴史』の同じ用語を読んでください。

**なぜ必要になったか。** イメージは静止したカードなので、名前と接続と環境を付けて、初めてプロセスとして動き始めます。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `--detach` | （なし） | コンテナを背景で動かし、コマンド自体はすぐに戻します。 |
| `--name` | eap-back | Docker がこのコンテナを区別する名前を eap-back にします。 |
| `--network` | eap-adot-otel_lab | コンテナをネットワーク eap-adot-otel_lab に接続します。 |
| `--network-alias` | back | 同じネットワークの中で、back という名札でも届くようにします。 |
| `--read-only` | （なし） | コンテナのルートファイルシステムを読み取り専用にします。 |
| `--publish` | 18080:18080 | ホストとコンテナのポートをつなぎます。対応は 18080:18080 です。 |
| `--tmpfs` | /run/eap:uid=6301,gid=6302,mode=0770 | メモリ上の一時領域を /run/eap:uid=6301,gid=6302,mode=0770 に作ります。 |
| `--env` | 49 個 | 環境変数を1行に1つ渡します。各値の意味は『環境変数』シートです。 |
| `--health-cmd` | /opt/app/bin/healthcheck.sh | 健康を聞くコマンドを /opt/app/bin/healthcheck.sh にします。 |
| `--health-interval` | 15s | 健康を聞く間隔を 15s にします。 |
| `--health-timeout` | 5s | 1回の質問の制限時間を 5s にします。 |
| `--health-start-period` | 120s | 起動直後の猶予を 120s にします。 |
| `--health-retries` | 20 | 連続失敗の上限を 20 回にします。 |

### 21. 起動する: eap-front

eap-front を起動します。お客さんが最初に話すカウンターです。奥の台所とは、橋の上の名前 back で話します。
イメージは local/eap-front:dev です。
ホストへ開く扉は 8080:8080 です。
ルートファイルシステムは読み取り専用です。
消える作業場所は /run/eap:uid=6301,gid=6302,mode=0770 です。
その前に確認すること: eap-aurora が healthy（最大 220 秒）。eap-valkey が healthy（最大 140 秒）。eap-adot-collector のプロセスが動いている。eap-back が healthy（最大 450 秒）。
同じネットワークでは front という名札で届きます。台帳の名前は eap-front です。
元の定義のメモ: front — JBoss EAP 8.1 / APP_ROLE=front / service.name = <APP_SERVICE>-front

**どう実行するか。** 依存先が healthy にならないときは、そのコンテナの docker logs を見ます。この段階だけを再実行しても、既に動いていれば作り直しません。

**成功すると見えるもの。** docker ps に eap-front が出ます。ヘルスチェックがある場合は、しばらくすると healthy になります。

**失敗すると見えるもの。** 同名コンテナの中身が古い、イメージが無い、公開ポートが使用中、マウント元が無い、SELinux が拒否、のいずれかです。

**動作原理。** カードの上に書き込み層を足し、橋とロッカーと扉とポケットメモを取り付けて、プロセスを開始します。

**頭の中の絵。** お客さんが最初に話すカウンターです。奥の台所とは、橋の上の名前 back で話します。

**歴史と背景。** 同じ種類の命令です。違うのは名前、対象、依存です。詳しい歴史は『動作原理と歴史』の同じ用語を読んでください。

**なぜ必要になったか。** イメージは静止したカードなので、名前と接続と環境を付けて、初めてプロセスとして動き始めます。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `--detach` | （なし） | コンテナを背景で動かし、コマンド自体はすぐに戻します。 |
| `--name` | eap-front | Docker がこのコンテナを区別する名前を eap-front にします。 |
| `--network` | eap-adot-otel_lab | コンテナをネットワーク eap-adot-otel_lab に接続します。 |
| `--network-alias` | front | 同じネットワークの中で、front という名札でも届くようにします。 |
| `--read-only` | （なし） | コンテナのルートファイルシステムを読み取り専用にします。 |
| `--publish` | 8080:8080 | ホストとコンテナのポートをつなぎます。対応は 8080:8080 です。 |
| `--tmpfs` | /run/eap:uid=6301,gid=6302,mode=0770 | メモリ上の一時領域を /run/eap:uid=6301,gid=6302,mode=0770 に作ります。 |
| `--env` | 51 個 | 環境変数を1行に1つ渡します。各値の意味は『環境変数』シートです。 |
| `--health-cmd` | /opt/app/bin/healthcheck.sh | 健康を聞くコマンドを /opt/app/bin/healthcheck.sh にします。 |
| `--health-interval` | 15s | 健康を聞く間隔を 15s にします。 |
| `--health-timeout` | 5s | 1回の質問の制限時間を 5s にします。 |
| `--health-start-period` | 120s | 起動直後の猶予を 120s にします。 |
| `--health-retries` | 20 | 連続失敗の上限を 20 回にします。 |

### 22. 起動結果を確認する

一覧と、ヘルスチェックを持つコンテナの状態を表示します。ここで healthy でなくても、猶予時間のあいだは starting のことがあります。

**どう実行するか。** 失敗している名前だけ docker logs --tail 100 名前 で見ます。全部を一度に見たいときは docker ps の Status 列を上から見ます。

**成功すると見えるもの。** 期待したコンテナ名が並び、依存の末端は healthy か、起動直後なら starting です。

**失敗すると見えるもの。** 一覧に名前が無いときは、その起動段階のメッセージとログを見ます。unhealthy なら検査コマンドの失敗です。

**動作原理。** 起動コマンドが戻ったことは、アプリが仕事を受けられることと同じではありません。状態を別に見ます。

**頭の中の絵。** 全部の店を回って、看板と準備の札を確認する段階です。

**歴史と背景。** 切り離し起動では、その場にログが残りません。docker ps と docker inspect と docker logs の3つで、後から状態を見ます。

**なぜ必要になったか。** 切り離して起動すると、その場にログが出ません。あとから同じ名前で状態を見る必要がありました。

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

| フラグ | 値 | 意味 |
| --- | --- | --- |
| `docker ps` | （なし） | 今動いているコンテナの名前、状態、扉を表にします。 |

## 動作原理と歴史

### なぜ Compose を Docker コマンドにほどくのか

**小学生向けのたとえ。** 文化祭の模擬店を、一枚の企画書だけで開ける道具が Compose です。企画書には『カウンター、台所、冷蔵庫、案内係』と順番の約束が書いてあります。Docker コマンドは、その企画書を一枚ずつ口頭の指示にしたものです。『先に廊下を作って。次に冷蔵庫のロッカーを用意して。それからカウンターを開けて』という指示です。

**動作原理。** Compose は新しい実行エンジンではありません。読んだ定義を、Docker Engine の『イメージを作る』『ネットワークを作る』『コンテナを作る』という操作へ翻訳しているだけです。同じ翻訳を人が読めるコマンドにすると、途中で何が起きたかを一行ずつ確認できます。障害のときも、企画書全体ではなく、失敗した一行だけを再実行できます。

**頭の中の絵。** 窓口（docker）の奥に当番（dockerd）がいて、当番が副担任（containerd）へ頼み、係（runc）が OS の心臓（カーネル）に『この作業机だけを見せて』と頼む、という並びです。Compose は窓口の前で、頼みごとをまとめて渡す受付係です。

**歴史と背景。** 2013年3月、Solomon Hykes が PyCon で Docker を公開しました。最初は1つのコンテナを配る道具でした。複数のコンテナを決まった順でつなぐ必要が出て、2014年に Fig が生まれ、開発元が Docker 社に加わったあと2015年に Docker Compose として広まりました。2020年に Compose Specification が公開され、ファイル先頭の version は廃止されました。2021年には Python 版から Go で書き直したCompose v2（docker compose、スペース区切り）へ変わり、2023年に Python 版の開発は終わっています。2026年10月時点の現行エンジンは Docker Engine 29 系で、2026年10月8日に 29.9.0 が出ています。

**必要になった経緯。** 1つのプロセスだけなら docker run で足ります。アプリ、データベース、集計係、案内係のように役割が分かれると、名前、起動順、ディスク、扉（ポート）を毎回忘れずに付けるのが苦しくなりました。Compose はその覚え書きです。覚え書きの中身をコマンドへ戻すと、本番の手順書や監査の説明に使えます。

### バックスラッシュと行継続

**小学生向けのたとえ。** 長い文章をノートの端で切って、次の行の先頭に『続き』と書くようなものです。Bash では行末の \ が『まだこの命令は終わっていない』というしるしです。

**動作原理。** \ の直後は改行だけで、空白を置いてはいけません。空白があると、その行で命令が終わり、次の行は別の命令として実行されます。引用符の中の改行は、このスクリプトでは使いません。1つのフラグを1行にして、実行中もログでどのお願いをしているか分かるようにしています。

**頭の中の絵。** 1本の長いリボンを、ハサミを入れずに机の幅で折り返して置いている状態です。

**歴史と背景。** 行継続の \ は Bourne shell（1970年代）からある書き方です。systemd のユニットやRPM の spec でも同種の継続が見えます。長い docker run を1行にすると、差分もレビューも読めなくなるため、手順書では継続行が今も標準です。

**必要になった経緯。** 画面幅と、人が目で追える単位に命令を分けるために必要になりました。機械にとっては1つの命令です。

### docker コマンドと dockerd

**小学生向けのたとえ。** docker は文化祭本部の窓口です。窓口の人は料理をしません。用紙を受け取って、奥の当番の先生（dockerd）へ渡します。

**動作原理。** CLI は UNIX ソケット /var/run/docker.sock へ HTTP に似た API を送ります。コンテナを作るのはデーモンです。権限が無いと、コマンドは入っていても info が失敗します。RHEL では docker グループに入っているか、root がソケットを使える必要があります。Red Hat が標準でサポートするエンジンは Podman です。podman-docker という互換コマンドは名前が docker でも中身が違います。この手順は Docker Engine（docker-ce）向けです。

**頭の中の絵。** 窓口、当番、副担任、係、カーネルの5人が縦に並んで、前の人は次の人に頼むだけです。

**歴史と背景。** 初期の Docker は1つのバイナリに全部が入っていました。その後、実行部分は runc（OCI Runtime、2015年に標準化）へ、監督は containerd（2017年に CNCF へ寄贈）へ分かれました。分けることで、Kubernetes も同じ containerd を使えるようになりました。2026年10月の Engine 29.9.0 では、コンテナの umask を決める --umask が docker run に追加されています。この Compose ファイルは umask を指定していないので、コマンドには入れていません。

**必要になった経緯。** 1つの巨大なプログラムだと、直す場所も権限も危険も大きすぎたため、窓口と当番と係に分かれました。

### イメージ

**小学生向けのたとえ。** イメージはレシピカードです。材料と手順が層になって重なっています。カード自体はまだお店が開いていません。

**動作原理。** イメージは読み取り専用の層の積み重ねです。コンテナは、その上に薄い書き込み層を1枚足して動きます。同じカードから、カウンター用と確認用のように複数のコンテナを開けます。タグ（local/eap-front:dev の :dev）は、カードにつけた付箋です。中身そのものの ID は別です。

**頭の中の絵。** 透明なシートを何枚も重ね、一番上だけが鉛筆で書ける状態です。

**歴史と背景。** Docker は AUFS などの差分ファイルシステムで層を実装し、後に overlay2 が一般的になりました。RHEL 9 の Docker CE も通常は overlay2 です。2017年からの BuildKit は、層の作り方を並列にしました。Engine 23（2023年）以降、docker build は最初から BuildKit を使います。

**必要になった経緯。** 毎回 OS からインストールすると遅いので、『変わった段だけ』をカードにして配る必要がありました。

### コンテナ

**小学生向けのたとえ。** コンテナは、レシピカードを使って今まさに開いているお店です。閉めると、書き込み層の落書きは原則として消えます。

**動作原理。** 隔離の正体は仮想マシンの別カーネルではありません。同じ Linux カーネルの上で、名前空間（見える範囲）と cgroup（使ってよい CPU とメモリ）と、必要なら SELinux（触ってよいラベル）で区切ります。RHEL 9.8 のカーネルは 5.14.0-687.5.1.el9_8 で、cgroup は v2 です。--memory や --cpus はこの cgroup へ渡ります。

**頭の中の絵。** 同じ校舎の中で、クラスごとに見える廊下とロッカーを分けている状態です。校舎は1つです。

**歴史と背景。** 2000年代の LXC や、さらに前の chroot（1979年）、2006年頃の cgroups が土台です。Docker は2013年にそれらを『イメージとして配れる』形にしました。2014年の libcontainer が後の runc です。仮想マシンと違い、起動は秒ではなく、もっと短くできます。その代わり、カーネルはホストと共有です。

**必要になった経緯。** 仮想マシンをアプリの数だけ起動すると重い。プロセスよりは壁が欲しい。その中間が必要になりました。

### docker build とビルドコンテキスト

**小学生向けのたとえ。** 料理教室に、レシピと材料の入った段ボールをまとめて渡すのがビルドです。段ボールの中身がコンテキスト、レシピが Dockerfile です。

**動作原理。** docker build の最後の引数が段ボールの場所です。--file で段ボールの中のどのレシピを読むかを指定します。レシピの COPY は、段ボールに入っているファイルしか取れません。親ディレクトリの外は取れません。.dockerignore に書いたものは段ボールに入れません。実行時の --volume とは別です。FROM の土台イメージがローカル名だけのときは、先にそのカードを作っておく必要があります。

**頭の中の絵。** 段ボールを窓口へ渡し、奥の厨房が層を焼いて、名前のついたカードを返してくる様子です。

**歴史と背景。** Dockerfile は Docker の初期からあります。ビルドが直列で遅かったため、2017年に BuildKit が発表され、2018年に実験機能、2023年の Engine 23 で標準になりました。シークレットを層に残さない --secret は BuildKit の機能です。2026年10月の Engine 29.9.0 は BuildKit v0.34.0 を同梱しています。

**必要になった経緯。** 完成品のカードだけを配ると、材料の出所が消え、作り直しも監査もできなくなるため、レシピと段ボールを残す必要がありました。

### 橋ネットワークと名前札

**小学生向けのたとえ。** bridge は、そのマシンの中だけにある長い机です。同じ机に着いたコンテナは、サービス名という名札で呼び合えます。外の世界へは、公開したポートという正門からだけ入ります。

**動作原理。** Compose はサービス名を DNS 名にします。docker run では --network-alias で同じ名札を付けます。--name は Docker 自身がコンテナを区別する名前で、他のコンテナからの呼び名とは別です。ネットワーク名とボリューム名は『プロジェクト名_名前』、コンテナの自動名は『プロジェクト名-サービス-1』です。アンダースコアとハイフンが混ざるのは、時代の違う命名が残っているためです。

**頭の中の絵。** 机の上の名札は front。本部の台帳の名前は eap-front。呼ぶ相手によって名前が違います。

**歴史と背景。** 初期の Docker は --link でコンテナを1対1で結んでいました。相手が増えると紐が絡み、起動順まで縛られました。2015年11月の Docker 1.9 でユーザー定義 bridge と内蔵 DNS が入り、名前で呼び合えるようになりました。Compose のネットワーク接頭辞のアンダースコアは、その頃の実装が残したものです。

**必要になった経緯。** リンクの紐では、データベースとアプリと集計係の全員が互いに話す構成を書けなくなったためです。

### ボリュームとバインドマウントと tmpfs

**小学生向けのたとえ。** ボリュームは、お店を閉めても残るロッカーです。データベースの中身はここへ置きます。バインドマウントは、校舎の棚のファイルを店の机の上へ直接置くことです。設定ファイル向きです。tmpfs はメモリの上の付箋で、コンテナを止めると消えます。作業用の下書き向きです。

**動作原理。** 名前付きボリュームは Docker が /var/lib/docker/volumes 以下に作ります。コンテナを rm しても、ボリュームを消さなければデータは残ります。バインドはホストの実ファイルです。コンテキストの .dockerignore は関係しません。読み取り専用ルートと tmpfs はセットです。ルートを封印しても、作業場所だけは書けるようにします。RHEL の SELinux が Enforcing のとき、バインドには共有ラベル z が要ることがあります。Docker の現行ドキュメントでは、z は --volume の接尾辞で付け、--mount ではラベルを変えられません。

**頭の中の絵。** ロッカー、机の上に置いた原本、消える付箋の3つが並んでいます。

**歴史と背景。** データ用ボリュームは Docker 1.0 前後からあり、2015年以降に名前付きボリュームが整理されました。tmpfs の --tmpfs は Docker 1.10 頃です。SELinux の :z と :Z は、コンテナに別のラベルを付けるRed Hat 系の必要から入りました。z は共有、Z はプライベートです。Z を /home のような広い場所に付けるとホストが壊れます。

**必要になった経緯。** コンテナの書き込み層は消えるので、残したいデータと、毎回捨てたい下書きと、ホストの設定ファイルを分けて置く必要がありました。

### ポートの公開

**小学生向けのたとえ。** 店の中の扉番号と、校舎の正門の番号をつなぐ内線です。中の 80 番を、外の 8081 番で受ける、という対応表です。

**動作原理。** --publish ホスト:コンテナ は、ホストのネットワーク名前空間で待ち、コンテナのポートへ転送します。公開しないポートは、同じ橋の上のコンテナからだけ届きます。データベースを公開しないのはこのためです。firewalld がある RHEL でも、Docker が自分の転送規則を入れるため、公開ポートは多くの場合そのまま届きます。

**頭の中の絵。** 正門の番号札と、店内のドア番号をひもで結んだ図です。

**歴史と背景。** 初期から -p がありました。bridge の実装は iptables、新しい環境では nftables バックエンドです。Docker 20.10 以降は nftables と iptables の選択がテーマになり、RHEL 9 ではファイアウォール実装との共存に注意が要ります。届かないときは、まず docker ps の PORTS 列と、コンテナの中の待受を分けて見ます。

**必要になった経緯。** コンテナの中のポートは、そのままではホストの外から見えません。見せる扉だけを選ぶ必要がありました。

### 環境変数

**小学生向けのたとえ。** お店の人のポケットに入れた名札メモです。プログラムは起動の瞬間にポケットを見て、接続先やパスワードを知ります。

**動作原理。** Compose の ${VAR:-既定} は、起動前に企画書を埋める作業です。埋めた結果が --env の値です。$$ は『今は埋めず、コンテナの中のシェルに $ を残す』というエスケープです。値の無い --env KEY は、実行する RHEL の環境からその場で渡します。変換したマシンの値は焼き込みません。このツールの既定では、変換している Windows の環境変数では埋めません。Compose ファイルと .env と、書き方の既定値で決めます。

**頭の中の絵。** 企画書の空欄を鉛筆で埋めてから、ポケットへコピーする二段階です。

**歴史と背景。** 環境変数は 1970年代の UNIX からプロセスに付いています。Docker はイメージに環境を焼き込む ENV と、実行時に渡す --env を分けました。秘密をイメージの層へ残さないための --secret（BuildKit）は、環境変数とは別の道です。

**必要になった経緯。** 接続先だけが違う同じカードを、作り直さずに開きたい。そのために、差をポケットメモへ出す必要がありました。

### ヘルスチェックと起動待ち

**小学生向けのたとえ。** 先生が『準備できた？』と一定間隔で聞くのがヘルスチェックです。開店直後のバタバタでは、失敗を点数にしない時間が start_period です。

**動作原理。** 検査コマンドの終了コード 0 が成功です。interval ごとに聞き、timeout を超えたらその回は失敗、retries 回続くと unhealthy です。start_period のあいだの失敗は、この回数に入れません。docker run の --health-cmd は、CLI の仕様として /bin/sh -c で実行されます（CMD-SHELL）。Compose の CMD（exec 形式）とはプロセスの形が少し違いますが、スクリプトの終了コードで見る点は同じです。depends_on は Docker Engine の機能ではありません。状態を docker inspect で見て待つ関数で代用します。

**頭の中の絵。** 開店前の沈黙時間のあと、先生がドアをノックし続ける図です。

**歴史と背景。** HEALTHCHECK は 2016年7月の Docker 1.12 で入りました。それまでは外側の監視が独自に叩いていました。start_period は、起動の遅いアプリがすぐ unhealthy になる問題への答えです。起動中だけ間隔を変える --health-start-interval は API 1.44（Engine 25、2024年）以降です。この Compose は start_interval を使っていないので、フラグは付けていません。

**必要になった経緯。** プロセスが生きていても、データベースの準備が終わっていないことがあります。『動いている』と『お願いを受けられる』を分ける必要がありました。

### RHEL 9.8 と SELinux

**小学生向けのたとえ。** ファイルに『誰が読んでよいか』の色シールが付いているのが SELinux です。コンテナは container_t という色の人です。色が違うファイルは、UNIX の権限が許していても拒否されます。

**動作原理。** RHEL 9.8 は 2026年5月19日に一般提供が始まり、カーネルは 5.14.0-687.5.1.el9_8 です。既定は SELinux Enforcing、ファイアウォールは firewalld、サービス管理は systemd です。Docker CE は download.docker.com のリポジトリから入り、RHEL 8、9、10 が対象です。dnf install docker だけだと Podman の互換コマンドになることがあるので、docker version に Podman と出ないことを確認します。バインドの :z は、そのホストファイルのラベルを container_file_t の共有ラベルへ変えます。変更はコンテナの外にも残ります。

**頭の中の絵。** 色シールの違う本を、色の合う人だけが開ける図書室です。

**歴史と背景。** SELinux は NSA と Red Hat が広めた強制アクセス制御で、RHEL 4 以降の系譜です。コンテナ用ポリシーは container-selinux パッケージとして Docker CE の依存に入ります。Red Hat は Podman / CRI-O を公式のコンテナエンジンとして推しています。Docker Engine は Docker 社のパッケージで動かす、という二本立てです。

**必要になった経緯。** root に見えるプロセスがホストのファイルを全部読めないようにするため、権限ビットとは別のラベルが必要になりました。

### 切り離して起動する

**小学生向けのたとえ。** お店の鍵を開けたあと、窓口の人は店内に残らず、次の店の鍵を開けに行きます。

**動作原理。** --detach が無いと、docker run はそのコンテナの前景に貼り付きます。複数台を1つのスクリプトで開けるのは、切り離すからです。ログは docker logs、状態は docker ps と docker inspect で後から見ます。

**頭の中の絵。** 鍵を回して次の扉へ歩く係の人です。

**歴史と背景。** 初期から -d があります。Compose up の既定は前景でログを流し、up -d が切り離しです。この手順は up -d に相当します。ログをその場で見たいときは、起動後に docker logs -f を使います。

**必要になった経緯。** 前景に貼り付くと、2台目を同じ端末から開けません。並んだサービスを手順にするには切り離しが必要でした。

### イメージを取ってくる

**小学生向けのたとえ。** レシピカードを、まだ手元に無いときだけ倉庫から取り寄せます。

**動作原理。** Compose の pull_policy の既定は、手元に無いときだけ取る動きに揃えています。ビルドするサービスは、完成イメージを pull しません。FROM の土台は docker build が必要に応じて取ります。毎回 pull すると、同じタグの中身が倉庫側で差し替わることがあります。再現したいときはタグだけでなくダイジェストを固定します。このファイルはタグ固定で、ダイジェスト固定ではありません。

**頭の中の絵。** 倉庫係が、棚に同じ付箋のカードが無いときだけ小包を開ける図です。

**歴史と背景。** レジストリは Docker Hub（2014年の公開レジストリ）から広まり、その後 OCI Distribution Spec として標準化されました。公開イメージのタグは動き得ます。本番ではダイジェスト固定が後から必要になりました。

**必要になった経緯。** カードを毎回自分で焼かなくても、合意した完成品を名前で取り寄せたい。そのための倉庫です。

### エントリポイントとコマンド

**小学生向けのたとえ。** エントリポイントは『開店の決まった手順』、コマンドは『今日のメニュー』です。手順が決まっている店では、メニューだけを差し替えます。

**動作原理。** Docker は ENTRYPOINT の配列の後ろに CMD の配列を足して実行します。--entrypoint は手順のプログラムだけを差し替え、イメージ名の後ろの語がコマンドです。この環境の JBoss 系は、イメージの /opt/app/bin/entrypoint.sh をそのまま使い、Compose はコマンドを上書きしません。MySQL は公式イメージのエントリポイントを残したまま、mysqld と設定引数だけをコマンドとして渡します。

**頭の中の絵。** 開店マニュアルの表紙は固定で、今日の品書きのページだけを差し替える図です。

**歴史と背景。** Dockerfile の ENTRYPOINT と CMD の二段は初期からあります。shell 形式は /bin/sh -c になり、exec 形式は指定したプログラムが PID 1 になります。PID 1 はシグナルの受け方が違うため、停止の速さに影響します。--init を付けると小さな init が PID 1 になり、ゾンビプロセスを回収します。この Compose は指定していないので付けていません。

**必要になった経緯。** 『いつも同じ起動手順』と『今日だけ変える引数』を、イメージを焼き直さずに分けたかったためです。

### 停止と後始末

**小学生向けのたとえ。** お店を閉めて看板を外しても、冷蔵庫のロッカーは校舎に残します。

**動作原理。** docker rm --force は、動いていても止めてからコンテナを捨てます。名前付きボリュームは捨てません。ネットワークは、接続しているコンテナが無くなってから消せます。だから先にコンテナを捨てます。イメージは消しません。次の起動で作り直す時間を省くためです。ボリュームまで消すのは、中のデータベースを捨てる操作なので、手順の本体には入れていません。

**頭の中の絵。** 看板を外し、机を片付け、廊下の名前を消し、ロッカーだけ残す図です。

**歴史と背景。** docker rm と docker stop は初期から分かれています。--force は停止と削除をまとめます。Compose down はコンテナとネットワークを消し、ボリュームは -v のときだけ消します。この停止手順は -v 無しの down に揃えています。

**必要になった経緯。** 消してよいものと、残すものを同じ命令で扱うと、データベースを誤って捨てるためです。

## 環境変数

| サービス | 変数 | 値 | 意味 |
| --- | --- | --- | --- |
| jaeger | `COLLECTOR_OTLP_ENABLED` | `true` | コンテナの中のプロセスが、この名前で読む設定値です。 |
| aurora | `MYSQL_ROOT_PASSWORD` | `rootpassword` | MySQL が初回起動のときだけ使う、管理者のパスワードです。 |
| aurora | `MYSQL_DATABASE` | `appdb` | MySQL が初回起動のときに作るデータベースの名前です。 |
| aurora | `MYSQL_USER` | `appuser` | MySQL が初回起動のときに作る利用ユーザーです。 |
| aurora | `MYSQL_PASSWORD` | `apppassword` | その利用ユーザーのパスワードです。 |
| aurora | `TZ` | `UTC` | コンテナの中で日付を表示するときの時間帯です。 |
| alb | `LISTEN_PORT` | `80` | コンテナの中のプロセスが、この名前で読む設定値です。 |
| alb | `ROUTES` | `^/report=report-ec2:8000,^/back=back:18080,^/front=front:8080,^/=front:8080` | コンテナの中のプロセスが、この名前で読む設定値です。 |
| report-ec2 | `PORT` | `8000` | コンテナの中のプロセスが、この名前で読む設定値です。 |
| report-ec2 | `STUB_NAME` | `report-ec2` | コンテナの中のプロセスが、この名前で読む設定値です。 |
| report-ec2 | `DELAY_MS` | `150` | コンテナの中のプロセスが、この名前で読む設定値です。 |
| external-slb | `PORT` | `80` | コンテナの中のプロセスが、この名前で読む設定値です。 |
| external-slb | `STUB_NAME` | `external-slb` | コンテナの中のプロセスが、この名前で読む設定値です。 |
| external-slb | `DELAY_MS` | `200` | コンテナの中のプロセスが、この名前で読む設定値です。 |
| localstack | `SERVICES` | `sqs` | LocalStack に、どの AWS の真似をさせるかの一覧です。 |
| localstack | `AWS_DEFAULT_REGION` | `ap-northeast-1` | AWS の SDK やコレクターが、地域や資格情報として読む値です。ローカルの練習用です。 |
| adot-collector | `AWS_REGION` | `ap-northeast-1` | AWS の SDK やコレクターが、地域や資格情報として読む値です。ローカルの練習用です。 |
| lambda-runner | `SQS_ENDPOINT` | `http://localstack:4566` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| lambda-runner | `SQS_QUEUE_URL` | `http://localstack:4566/000000000000/app-queue` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| lambda-runner | `TARGET_URL` | `http://alb:80/back/api/from-lambda` | コンテナの中のプロセスが、この名前で読む設定値です。 |
| lambda-runner | `POLL_INTERVAL` | `2` | コンテナの中のプロセスが、この名前で読む設定値です。 |
| back | `TZ` | `Asia/Tokyo` | コンテナの中で日付を表示するときの時間帯です。 |
| back | `JVM_OPTS_MODE` | `append` | --- JVM オプションの渡し方 (2 パターン) ---------------------------------- |
| back | `EAP_HTTPS_MODE` | `remove` | --- JBoss CLI の適用 (コンテナ起動時) ----------------------------------- |
| back | `EAP_CLI_STDOUT` | `echo` | JBoss EAP または JVM の起動方法を変える値です。イメージを作り直さずに切り替えられます。 |
| back | `APP_SERVICE` | `intra-api` | --- 命名規約の入力 (これだけで service.name が決まる) ------------------- |
| back | `APP_ENV` | `local` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| back | `APP_NAMESPACE` | `shopdemo` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| back | `APP_VERSION` | `1.0.0` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| back | `PEER_NAME_AURORA` | `` | --- X-Ray / Jaeger のノード表示名 (段1 の表示名) ------------------------- |
| back | `PEER_NAME_VALKEY` | `` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| back | `PEER_NAME_EC2` | `` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| back | `PEER_NAME_ALB` | `` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| back | `PEER_NAME_EXTERNAL_SLB` | `` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| back | `PEER_NAME_SQS` | `` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| back | `APP_PEER_NAME_MODE` | `as-is` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| back | `APP_EXTRA_RESOURCE_ATTRIBUTES` | `aws.ecs.cluster.name=shopdemo-local,aws.ecs.task.family=intra-api-local` | --- ECS ディテクタが本番でだけ付ける属性のローカル代替 ------------------- |
| back | `APP_SERVICE_EVENT_PACKAGES` | `` | --- ADOT の関数レベル計装 (AWS Service Events) -------------------------- |
| back | `OTEL_TRACE_WARN_SUPPRESS` | `resource,context` | --- トレース関連 WARN の抑制 -------------------------------------------- |
| back | `OTEL_AGENT_LOG_SUPPRESS_EXTRA` | `` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| back | `APP_PEER_ALB_MODE` | `upstream` | --- 下流ノード名の多段階判定 (peer.service) ------------------------------ |
| back | `APP_PEER_DOMAIN_RULES` | `` | ★ 段2/段3 のルールは既定値をここに書かない。 |
| back | `APP_PEER_PORT_RULES` | `` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| back | `APP_PEER_EXTRA_HOSTS` | `` | 用途が未知の連携先を段2 以降だけで名付けさせる (host または host:port) |
| back | `APP_PEER_SERVICE_MAPPING` | `` | ホストを名指しで上書きする最優先の対応表 |
| back | `APP_CAPTURE_REQUEST_HEADERS_EXTRA` | `` | --- トレースに載せるリクエスト情報 --------------------------------------- |
| back | `APP_CAPTURE_RESPONSE_HEADERS_EXTRA` | `` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| back | `APP_CAPTURE_CLIENT_REQUEST_HEADERS_EXTRA` | `` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| back | `APP_CAPTURE_CLIENT_RESPONSE_HEADERS_EXTRA` | `` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| back | `APP_CAPTURE_REQUEST_PARAMETERS` | `` | ★ 既定は空 = パラメータは 1 つも載せない。 |
| back | `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://adot-collector:4317` | --- ADOT Collector への送信先 (ECS では http://localhost:4317) ---------- |
| back | `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| back | `DB_HOST` | `aurora` | --- Aurora Serverless v2 (MySQL 8.4) 相当 ------------------------------- |
| back | `DB_PORT` | `3306` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| back | `DB_NAME` | `appdb` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| back | `DB_USER` | `appuser` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| back | `DB_PASSWORD` | `apppassword` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| back | `VALKEY_HOST` | `valkey` | --- ElastiCache for Valkey 相当 ----------------------------------------- |
| back | `VALKEY_PORT` | `6379` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| back | `REPORT_ALB_HOST` | `alb` | --- 帳票 EC2 / 外部 SLB (どちらも ALB / SLB 越し) ------------------------ |
| back | `REPORT_ALB_URL` | `http://alb:80/report/daily` | コンテナの中のプロセスが、この名前で読む設定値です。 |
| back | `EXTERNAL_SLB_HOST` | `external-slb` | コンテナの中のプロセスが、この名前で読む設定値です。 |
| back | `EXTERNAL_SLB_URL` | `http://external-slb:80/outside/api` | コンテナの中のプロセスが、この名前で読む設定値です。 |
| back | `SQS_HOST` | `localstack` | --- SQS (LocalStack) ----------------------------------------------------- |
| back | `SQS_ENDPOINT` | `http://localstack:4566` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| back | `SQS_QUEUE_URL` | `http://localstack:4566/000000000000/app-queue` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| back | `AWS_REGION` | `ap-northeast-1` | AWS の SDK やコレクターが、地域や資格情報として読む値です。ローカルの練習用です。 |
| back | `AWS_ACCESS_KEY_ID` | `test` | AWS の SDK やコレクターが、地域や資格情報として読む値です。ローカルの練習用です。 |
| back | `AWS_SECRET_ACCESS_KEY` | `test` | AWS の SDK やコレクターが、地域や資格情報として読む値です。ローカルの練習用です。 |
| back | `APP_ROLE` | `back` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| front | `TZ` | `Asia/Tokyo` | コンテナの中で日付を表示するときの時間帯です。 |
| front | `JVM_OPTS_MODE` | `append` | --- JVM オプションの渡し方 (2 パターン) ---------------------------------- |
| front | `EAP_HTTPS_MODE` | `remove` | --- JBoss CLI の適用 (コンテナ起動時) ----------------------------------- |
| front | `EAP_CLI_STDOUT` | `echo` | JBoss EAP または JVM の起動方法を変える値です。イメージを作り直さずに切り替えられます。 |
| front | `APP_SERVICE` | `intra-api` | --- 命名規約の入力 (これだけで service.name が決まる) ------------------- |
| front | `APP_ENV` | `local` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| front | `APP_NAMESPACE` | `shopdemo` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| front | `APP_VERSION` | `1.0.0` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| front | `PEER_NAME_AURORA` | `` | --- X-Ray / Jaeger のノード表示名 (段1 の表示名) ------------------------- |
| front | `PEER_NAME_VALKEY` | `` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| front | `PEER_NAME_EC2` | `` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| front | `PEER_NAME_ALB` | `` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| front | `PEER_NAME_EXTERNAL_SLB` | `` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| front | `PEER_NAME_SQS` | `` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| front | `APP_PEER_NAME_MODE` | `as-is` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| front | `APP_EXTRA_RESOURCE_ATTRIBUTES` | `aws.ecs.cluster.name=shopdemo-local,aws.ecs.task.family=intra-api-local` | --- ECS ディテクタが本番でだけ付ける属性のローカル代替 ------------------- |
| front | `APP_SERVICE_EVENT_PACKAGES` | `` | --- ADOT の関数レベル計装 (AWS Service Events) -------------------------- |
| front | `OTEL_TRACE_WARN_SUPPRESS` | `resource,context` | --- トレース関連 WARN の抑制 -------------------------------------------- |
| front | `OTEL_AGENT_LOG_SUPPRESS_EXTRA` | `` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| front | `APP_PEER_ALB_MODE` | `upstream` | --- 下流ノード名の多段階判定 (peer.service) ------------------------------ |
| front | `APP_PEER_DOMAIN_RULES` | `` | ★ 段2/段3 のルールは既定値をここに書かない。 |
| front | `APP_PEER_PORT_RULES` | `` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| front | `APP_PEER_EXTRA_HOSTS` | `` | 用途が未知の連携先を段2 以降だけで名付けさせる (host または host:port) |
| front | `APP_PEER_SERVICE_MAPPING` | `` | ホストを名指しで上書きする最優先の対応表 |
| front | `APP_CAPTURE_REQUEST_HEADERS_EXTRA` | `` | --- トレースに載せるリクエスト情報 --------------------------------------- |
| front | `APP_CAPTURE_RESPONSE_HEADERS_EXTRA` | `` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| front | `APP_CAPTURE_CLIENT_REQUEST_HEADERS_EXTRA` | `` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| front | `APP_CAPTURE_CLIENT_RESPONSE_HEADERS_EXTRA` | `` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| front | `APP_CAPTURE_REQUEST_PARAMETERS` | `` | ★ 既定は空 = パラメータは 1 つも載せない。 |
| front | `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://adot-collector:4317` | --- ADOT Collector への送信先 (ECS では http://localhost:4317) ---------- |
| front | `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| front | `DB_HOST` | `aurora` | --- Aurora Serverless v2 (MySQL 8.4) 相当 ------------------------------- |
| front | `DB_PORT` | `3306` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| front | `DB_NAME` | `appdb` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| front | `DB_USER` | `appuser` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| front | `DB_PASSWORD` | `apppassword` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| front | `VALKEY_HOST` | `valkey` | --- ElastiCache for Valkey 相当 ----------------------------------------- |
| front | `VALKEY_PORT` | `6379` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| front | `REPORT_ALB_HOST` | `alb` | --- 帳票 EC2 / 外部 SLB (どちらも ALB / SLB 越し) ------------------------ |
| front | `REPORT_ALB_URL` | `http://alb:80/report/daily` | コンテナの中のプロセスが、この名前で読む設定値です。 |
| front | `EXTERNAL_SLB_HOST` | `external-slb` | コンテナの中のプロセスが、この名前で読む設定値です。 |
| front | `EXTERNAL_SLB_URL` | `http://external-slb:80/outside/api` | コンテナの中のプロセスが、この名前で読む設定値です。 |
| front | `SQS_HOST` | `localstack` | --- SQS (LocalStack) ----------------------------------------------------- |
| front | `SQS_ENDPOINT` | `http://localstack:4566` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| front | `SQS_QUEUE_URL` | `http://localstack:4566/000000000000/app-queue` | 接続先のホスト名、ポート、表示名を渡す値です。 |
| front | `AWS_REGION` | `ap-northeast-1` | AWS の SDK やコレクターが、地域や資格情報として読む値です。ローカルの練習用です。 |
| front | `AWS_ACCESS_KEY_ID` | `test` | AWS の SDK やコレクターが、地域や資格情報として読む値です。ローカルの練習用です。 |
| front | `AWS_SECRET_ACCESS_KEY` | `test` | AWS の SDK やコレクターが、地域や資格情報として読む値です。ローカルの練習用です。 |
| front | `APP_ROLE` | `front` | アプリまたは起動スクリプトが、計装と名前の規則を決めるために読む値です。 |
| front | `BACKEND_HOST` | `back` | ECS では http://localhost:18080 (同一タスク内) |
| front | `BACKEND_URL` | `http://back:18080` | コンテナの中のプロセスが、この名前で読む設定値です。 |

## ビルドコンテキストで確認したこと

### プロジェクト

場所: `.dockerignore`

ビルドの段ボールに入れないもの: .git, .gitignore, .gitattributes, docs/, scripts/, ecs/, sim/, compose.yaml, README.md, sample-app/target/

### app-eap-base:1.0

場所: `base/Containerfile`

back、front が FROM app-eap-base:1.0 しているため、サービス定義の外にある Containerfile を先に焼きます。FROM registry.access.redhat.com/ubi9/ubi:9.8 -> registry.access.redhat.com/ubi9/ubi:9.8 -> registry.access.redhat.com/ubi9/ubi:9.8 -> server-zip（このファイルの中の前の段）。ENTRYPOINT ["/opt/app/bin/entrypoint.sh"]。CMD ["run-server"]。USER 6301:6302。WORKDIR /run/eap。未配置の COPY: vendor/jboss-eap-8.1.0.zip

### alb

場所: `sim/alb/Dockerfile`

FROM registry.access.redhat.com/ubi9/ubi-minimal:9.5。ENTRYPOINT ["python3", "-u", "/opt/alb_sim.py"]。EXPOSE 80

### report-ec2

場所: `sim/report-ec2/Dockerfile`

FROM registry.access.redhat.com/ubi9/ubi-minimal:9.5。ENTRYPOINT ["python3", "-u", "/opt/stub.py"]

### external-slb

場所: `sim/report-ec2/Dockerfile`

FROM registry.access.redhat.com/ubi9/ubi-minimal:9.5。ENTRYPOINT ["python3", "-u", "/opt/stub.py"]

### lambda-runner

場所: `sim/lambda/Dockerfile`

FROM registry.access.redhat.com/ubi9/ubi-minimal:9.5。ENTRYPOINT ["python3", "-u", "/opt/sqs_to_alb.py"]

### back

場所: `back/Containerfile`

FROM app-eap-base:1.0。USER 6301:6302。WORKDIR /run/eap。EXPOSE 18080。イメージ側の HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=5      CMD /opt/app/bin/healthcheck.sh 。Compose の healthcheck がある場合は、実行時フラグが上書きします。。未配置の COPY: dist/app.war

### front

場所: `front/Containerfile`

FROM app-eap-base:1.0。USER 6301:6302。WORKDIR /run/eap。EXPOSE 8080。イメージ側の HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=5      CMD /opt/app/bin/healthcheck.sh 。Compose の healthcheck がある場合は、実行時フラグが上書きします。。未配置の COPY: dist/app.war

### 起動スクリプト

場所: `base/bin/entrypoint.sh`

このスクリプトに、読み取り専用ルートでは作業領域を tmpfs など書き込める場所にする、と書かれています。起動時の設定適用で数十秒かかるため、ヘルスチェックは直後には成功しない想定です。だから docker run は --read-only と --tmpfs を両方付け、start_period を残します。

## Compose の項目と Docker のフラグ

| Compose | Docker | 意味 |
| --- | --- | --- |
| name | eap-adot-otel | ネットワークとボリュームの接頭辞に使います。コンテナ名は container_name が優先です。 |
| networks.<名前> | docker network create <プロジェクト>_<名前> | 接頭辞とのあいだはアンダースコアです。コンテナの自動名のハイフンとは歴史が違います。 |
| volumes.<名前> | docker volume create <プロジェクト>_<名前> | コンテナを rm しても残します。停止手順では消しません。 |
| services.<名前>.image | docker pull または docker run のイメージ名 | build が無いときだけ、手元に無ければ pull します。 |
| services.<名前>.build | docker build --file ... コンテキスト | コンテキストは Compose ファイルからの相対です。作業ディレクトリからではありません。 |
| build.args | --build-arg | レシピの ARG を上書きします。 |
| build.secrets | --secret | BuildKit のビルド中だけ見える秘密です。層には残りません。 |
| container_name | --name | 台帳の名前です。DNS 名ではありません。 |
| networks とサービス名 | --network と --network-alias | Compose が自動で付けるサービス名の名札を、明示的に付けます。 |
| ports | --publish | ホストの扉とコンテナの扉をつなぎます。 |
| expose | --expose | 記録だけです。ホストへは開きません。 |
| volumes のバインド | --volume 元:先:ro,z | RHEL では SELinux ラベルのため --volume を使います。現行ドキュメントでは --mount では z を付けられません。 |
| volumes の名前付き | --volume ボリューム名:先 | Docker が管理するロッカーです。 |
| tmpfs | --tmpfs | メモリ上の消える作業場所です。 |
| read_only | --read-only | ルートを封印します。書けるのは tmpfs とマウントだけです。 |
| environment | --env KEY=VALUE | 変換時に補間した値を、単一引用符で渡します。 |
| healthcheck.test の CMD | --health-cmd | CLI は sh -c で実行します。終了コード 0 が成功です。 |
| healthcheck の時間と回数 | --health-interval など | イメージの HEALTHCHECK より、Compose の値が優先です。 |
| depends_on: service_healthy | wait_healthy | Engine に依存待機は無いので、inspect で状態を見る関数にします。 |
| depends_on: service_started | wait_running | プロセスが動いたことだけを見ます。 |
| command | イメージ名の後ろの引数 | ENTRYPOINT は残し、CMD だけを差し替えます。 |
| profiles | （既定では出力しない） | 通常の docker compose up と同じく、指定したプロファイルだけを含めます。 |
| Compose が付ける com.docker.compose.* ラベル | 付けない | アプリの動作には不要なので、命令を短くするために省いています。 |

## 停止

お店を閉めて看板を外しても、冷蔵庫のロッカーは残します。
次のコマンドはコンテナとネットワークだけを消します。

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

## うまくいかないとき

- `permission denied` でバインドしたファイルを読めないときは、SELinux です。`getenforce` が Enforcing なら、マウントの `z` が付いているか、`ausearch -m avc -ts recent` で拒否を見ます。
- イメージの取得が名前解決や接続で失敗するときは、そのマシンからレジストリへ 443 番で届くかを見ます。社内プロキシがあるときは `HTTPS_PROXY` を設定して、同じ `docker pull` だけを再実行します。
- `bind source path does not exist` は、PROJECT_ROOT の場所が違うか、材料ファイルがまだ置かれていません。
- 公開ポートが使用中なら、`ss -lptn` でその番号を使っているプロセスを見ます。
- `unhealthy` のときは、そのコンテナの `docker logs --tail 100 名前` を見ます。起動直後の `starting` は失敗ではありません。猶予時間のあいだは正常です。
- 行が途中で別の命令として動くときは、`\` の後ろに空白か CR が入っています。`sed -i 's/\r$//' docker-commands.txt` で CR を消せます。
