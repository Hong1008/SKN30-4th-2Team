# 인프라 설치 가이드

이 문서는 새 운영자가 저장소를 설치하고 실제 리소스를 변경하지 않는
`infra-plan`까지 실행하는 절차다. 명령은 저장소 루트에서 실행한다.

## 1. 지원 환경

- 권장: Ubuntu 또는 WSL2 Ubuntu
- Windows: Git Bash에서 동일한 `just` 명령 사용
- CDK 앱은 `uv`로 실행하므로 OS별 `.venv/bin/python` 또는 `.venv/Scripts/python.exe` 경로를 직접 실행하지 않는다.
- 저장소는 submodule을 포함해 clone해야 한다.

```bash
git clone --recurse-submodules <repository-url>
cd SKN30-4th-2Team
git submodule update --init --recursive
```

PowerShell 전용 명령은 제공하지 않는다. Windows 경로 문제를 피하려면
저장소와 Docker volume을 같은 WSL2 파일 시스템에 두는 구성을 권장한다.

## 2. 필수 도구

| 도구 | 용도 |
| --- | --- |
| Git | 저장소와 MCP submodule |
| GitHub CLI (`gh`) | 로컬 GitHub 인증과 Environment Variable 등록 |
| Docker Engine + Compose v2 (Linux) / Docker Desktop (Windows) | Compose 검증과 컨테이너 실행 |
| Python 3.13+, `uv` | 내부 인프라 모듈과 API·MCP 의존성 |
| Node.js 24.18+, npm | Web build와 CDK CLI |
| AWS CLI v2 | 로컬 AWS 인증과 운영 |
| `runpodctl` | 로컬 Pod 조회·생성·삭제 |
| `just` | 유일한 로컬 실행 인터페이스 |

사용 중인 OS/환경에 맞는 설치 가이드를 선택하여 실행한다.

---

### 2.1. Linux / WSL2 (Ubuntu 24.04)

Ubuntu 24.04/WSL2 환경에서는 먼저 기본 패키지와 Docker 공식 apt repository를 설정한다.

```bash
sudo apt-get update
sudo apt-get install -y git gh curl unzip ca-certificates xz-utils
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

group 변경은 새 로그인 shell부터 적용된다. WSL2에서 Docker Desktop 연동을
사용한다면 Docker Engine 중복 설치 대신 WSL integration을 활성화한다.

저장소의 [`.node-version`](../../../.node-version)에 고정한 Node.js 공식
binary를 설치한다. 다음 예시는 x86_64이며 ARM64는 `linux-arm64` archive를
사용한다.

```bash
NODE_VERSION="$(cat .node-version)"
curl -fsSLO \
  "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz"
sudo tar -xJf "node-v${NODE_VERSION}-linux-x64.tar.xz" \
  --strip-components=1 -C /usr/local
rm "node-v${NODE_VERSION}-linux-x64.tar.xz"
```

나머지 CLI를 설치한다. 다운로드 script는 실행 전에 조직 보안 정책에 따라
내용과 checksum을 검토한다.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.13
uv tool install rust-just

AWS_CLI_TMP="$(mktemp -d)"
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" \
  -o "${AWS_CLI_TMP}/awscliv2.zip"
unzip -q "${AWS_CLI_TMP}/awscliv2.zip" -d "$AWS_CLI_TMP"
sudo "${AWS_CLI_TMP}/aws/install"
rm -rf "$AWS_CLI_TMP"

mkdir -p "$HOME/.local/bin"
curl -fsSL \
  https://github.com/runpod/runpodctl/releases/latest/download/runpodctl-linux-amd64 \
  -o "$HOME/.local/bin/runpodctl"
chmod 0755 "$HOME/.local/bin/runpodctl"
```

---

### 2.2. Native Windows (PowerShell + Git Bash)

Native Windows 환경에서는 **PowerShell**에서 도구 및 CLI를 설치한 뒤, 저장소의 실제 execution 명령어(`just ...`)는 **Git Bash**에서 실행한다.

```powershell
# 1. winget을 이용해 필수 도구 설치
winget install -e --id Git.Git
winget install -e --id GitHub.cli
winget install -e --id Docker.DockerDesktop
winget install -e --id OpenJS.NodeJS.LTS
winget install -e --id Amazon.AWSCLI

# 2. uv 및 rust-just 설치
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
uv python install 3.13
uv tool install rust-just

# 3. runpodctl (Windows 64-bit) 설치 (%USERPROFILE%\.local\bin 에 설치)
New-Item -ItemType Directory -Force -Path "$HOME\.local\bin"
Invoke-WebRequest -Uri "https://github.com/runpod/runpodctl/releases/latest/download/runpodctl-windows-amd64.exe" -OutFile "$HOME\.local\bin\runpodctl.exe"
```

> **Windows 환경 주요 참고사항:**
> - `%USERPROFILE%\.local\bin` 이 환경 변수 `Path`에 포함되어 있어야 Git Bash / PowerShell에서 `just` 및 `runpodctl`을 직접 실행할 수 있습니다.
> - Docker Desktop은 **Linux containers** 모드로 설정되어 있어야 합니다.
> - Node.js 버전은 [`.node-version`](../../../.node-version) 고정값 이상의 LTS인지 확인합니다.
> - RunPod 관리 키를 `runpodctl config`로 영구 저장하지 마십시오.

---

### 2.3. 설치 검증

`~/.local/bin`이 `PATH`에 반영되도록 새 Git Bash 또는 WSL shell을 열고 버전을 확인한다.

```bash
git --version
gh --version
docker --version
docker compose version
python3 --version
uv --version
node --version
npm --version
aws --version
runpodctl version
just --version
```

- [Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
- [GitHub CLI 설치](https://github.com/cli/cli/blob/trunk/docs/install_linux.md)
- [Node.js download](https://nodejs.org/en/download)
- [AWS CLI v2 설치](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- [uv 설치](https://docs.astral.sh/uv/getting-started/installation/)
- [just 설치](https://just.systems/man/en/packages.html)
- [RunPod CLI 설치](https://docs.runpod.io/runpodctl/overview)

## 3. AWS 인증

### IAM Identity Center SSO

SSO가 기본 선택이다. 관리자에게 대상 계정의 최소권한 permission set을
요청하고 profile을 만든다.

```bash
aws configure sso --profile workshield-session
aws sso login --profile workshield-session
aws sts get-caller-identity --profile workshield-session
```

출력된 account가 대상 설정과 일치하는지 반드시 확인한다.

### IAM access key와 MFA 대안

SSO 계정이나 permission set을 이용할 수 없는 환경인 경우, IAM User 및 Access Key / Virtual MFA를 준비해야 합니다.

#### 1) 관리자에게 요청하는 경우
* WorkShield 관리 범위로 제한한 IAM User 생성 요청
* Access Key (Access Key ID & Secret Access Key) 발급 요청
* Virtual MFA 디바이스 등록 안내 요청

#### 2) 본인이 직접 AWS Console에서 등록하는 경우
1. **IAM User 생성 및 권한 부여**:
   * AWS Management Console 접속 → **IAM** 서비스 → **Users** → **Create user** 클릭
   * 사용자 이름 입력 및 WorkShield 관리에 필요한 최소 권한 정책(Policy) 연결
2. **Access Key 발급**:
   * 생성한 IAM User 상세 페이지 → **Security credentials (보안 자격 증명)** 탭 이동
   * **Access keys** 섹션 → **Create access key** 클릭 → Use case에서 **Command Line Interface (CLI)** 선택
   * 발급된 `Access Key ID` 및 `Secret Access Key` 복사/안전 보관
3. **Virtual MFA 디바이스 등록**:
   * **Security credentials** 탭 → **Multi-Factor Authentication (MFA)** 섹션 → **Assign MFA device** 클릭
   * 디바이스 이름 입력 후 **Authenticator app** (Google Authenticator, Authy 등) 선택
   * 화면에 표시된 QR 코드를 모바일 앱으로 스캔 후, 앱에 생성되는 6자리 인증 코드 2개를 연속 입력하여 동기화 및 등록
   * 등록 완료 후 생성된 **MFA Device ARN** (`arn:aws:iam::<ACCOUNT_ID>:mfa/<USERNAME>`)을 복사해 둡니다.

---

#### 3) 로컬 AWS CLI 프로필 설정

장기 access key는 `~/.aws/credentials`의 base profile에만 저장한다.
프로젝트 `.env`, GitHub Secret, 채팅이나 문서에 기록하지 않는다.

```bash
aws configure --profile workshield-session
```

`~/.aws/config` 파일에  `mfa_serial`을 지정하면 MFA 코드를 입력받습니다.

`~/.aws/config` 설정 예시:
```ini
[profile workshield-session]
mfa_serial = arn:aws:iam::<ACCOUNT_ID>:mfa/<USERNAME>
region = ap-northeast-2
output = json
```

설정 후 아래 명령을 실행하면 MFA 번호 입력 프롬프트가 나타납니다:
```bash
aws sts get-caller-identity --profile workshield-session
```

설치된 환경에 따라 `sts get-session-token`으로 임시 credential을 수동 발급받아 환경 변수나 session profile에 저장할 수도 있습니다. 실제 `just infra-*` 실행에는 base profile이 아닌 MFA session profile을 전달하며, root user access key는 사용하지 않습니다.

- [AWS CLI source_profile 및 MFA 사용 가이드](https://docs.aws.amazon.com/cli/v1/userguide/cli-configure-role.html#cli-configure-role-mfa)
- [GetSessionToken](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_temp_control-access_getsessiontoken.html)

## 4. 설정 파일

초기화 명령으로 의존성과 예제 설정을 준비한다.

```bash
just infra-init
```

`infra/config/prod.example.json`을 Git 비추적 운영 설정으로 복사하고 값의
placeholder를 실제 환경에 맞게 채운다.

```bash
cp infra/config/prod.example.json infra/config/prod.json
```

설정에는 AWS account/region/AZ, GitHub repository와 Environment, DuckDNS
origin, ACME 알림 email, GHCR owner, instance와 RunPod 원하는 상태처럼
비밀이 아닌 값만 둔다.
리소스 이름과 environment를 기존 리소스에 맞추지 않은 채 임의 변경하면 새
리소스가 생성될 수 있다.

> **💡 `cloudfront_origin_prefix_list_id` 구하는 방법:**
> CloudFront 트래픽만 Security Group에서 수신 허용하기 위한 AWS 관리형 접두사 목록(Managed Prefix List) ID입니다.
> 
> * **AWS CLI로 조회 (권장 - 한 줄로 복사하여 실행):**
>   ```bash
>   aws ec2 describe-managed-prefix-lists --filters "Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing" --query "PrefixLists[0].PrefixListId" --output text --profile workshield-session
>   ```
> * **AWS Console로 조회:**
>   VPC 콘솔 접속 → **Managed Prefix Lists (관리형 접두사 목록)** 메뉴 → `com.amazonaws.global.cloudfront.origin-facing` 항목의 **Prefix List ID** (`pl-xxxxxxxx` 형식) 복사


`runpod_llm_template_id`는 `vllm/vllm-openai:latest`,
`runpod_embed_template_id`는 MCP submodule workflow가 게시하는
`ghcr.io/<owner>/<mcp-repository>/embed-rerank:latest`를 사용하는 RunPod
template ID여야 한다. (현재는 리드가 생성한 템플릿을 사용합니다.) template의 image·GPU가 설정과 다르면 자동 교체하지
않는다. Pod 조회 결과의 template ID나 GPU가 설정과 다르면
소유권/immutable drift로 중단한다.

`runpod_llm_model`에는 지원 preset의 Hugging Face model ID를 입력한다.
인프라 모듈은 model ID가 preset에 포함되는지 검사하고, 해당 preset의
reasoning parser·dtype·공통 server 인자를 RunPod container의
`--docker-args`로 전달한다. 임의 model ID나 사용자 지정 start command는
허용하지 않는다.

비밀 파일을 만들고 소유자만 읽을 수 있게 제한한다.

```bash
cp infra/config/prod.secrets.example.env infra/config/prod.secrets.env
chmod 600 infra/config/prod.secrets.env
```

`prod.secrets.env`에 포함되는 필수 비밀 항목의 구체적인 설정값은 다음과 같습니다:

| 비밀 변수명 | 설명 및 채워야 할 값 |
| --- | --- |
| `RUNPOD_MANAGEMENT_API_KEY` | RunPod 콘솔(Settings > API Keys)에서 발급받은 관리용 API Key |
| `LAW_OC` | 국가법령정보 공동활용 서비스(law.go.kr) Open API 사용자 인증키 (OC) |
| `ORIGIN_HEADER` | CloudFront → Nginx 직접 우회 접근 차단용 임의 무작위 비밀 문자열 (`openssl rand -hex 16`으로 생성 권장) |
| `DUCKDNS_TOKEN` | DuckDNS 사용자 계정 API 토큰 (아래 DuckDNS 가이드 참고) |
| `VLLM_API_KEY`, `RUNPOD_EMBED_API_KEY` | `just infra-ensure` 최초 실행 시 자동 생성되므로 초기에 빈 값 유지 |

> **💡 DuckDNS 도메인 등록 및 `DUCKDNS_TOKEN` 설정 안내:**
> 1. [DuckDNS 공식 홈페이지](https://www.duckdns.org/)에 접속하여 로그인/회원가입을 진행합니다.
> 2. `infra/config/prod.json`의 `origin_domain` 항목에 지정할 서브도메인(예: `workshield.duckdns.org`은 리드가 선점 다른 도메인 사용)을 DuckDNS 콘솔에서 추가 생성합니다.
> 3. DuckDNS 대시보드 메인 화면 상단에 표시되는 계정 **token** 값(UUID 형태)을 복사하여 `infra/config/prod.secrets.env`의 `DUCKDNS_TOKEN=` 뒤에 입력합니다.

값 입력 완료 후에도 해당 파일은 절대 Git에 추가하거나 외부에 공유하지 마십시오. 상세 내용은 [비밀 관리](../operations/secrets.md)를 참고합니다.

## 5. 첫 점검

다음 순서는 AWS·RunPod 리소스를 생성하거나 변경하지 않는다.

```bash
just infra-check
just infra-plan workshield-session prod
```

`infra-check`에서는 도구, submodule, 설정 누락과 secret 파일 권한을
확인한다. `infra-plan`은 AWS identity를 확인하고 다음을 출력한다.

- 대상 account, region, environment
- 생성·재사용·갱신·중단 대상
- 소유권 tag와 복수 후보 여부
- RunPod template와 `latest` image 계약
- 예상 비용 리소스

계획이 의도와 다르면 설정과
[장애 대응](../operations/troubleshooting.md)을 확인한다.

## 6. 인프라 구축 및 애플리케이션 배포

이 절에서는 첫 프로비저닝부터 GitHub Actions 배포까지의 순서를 설명합니다.
명령을 실행하기 전에 5장의 `infra-plan` 결과에서 AWS account, region,
GitHub 저장소와 생성 대상이 모두 의도한 값인지 확인해야 합니다.

### 6.1. 인프라 프로비저닝

`infra-up`은 사전 검사, CDK bootstrap, Access/Foundation/Service stack,
RunPod Pod 생성과 최종 상태 조회를 순서대로 실행하는 **실제 적용 명령**입니다.
EC2, Elastic IP, RunPod Pod 등의 비용이 이 단계부터 발생할 수 있습니다.

```bash
just infra-up workshield-session prod
```

단계별로 확인하면서 진행하려면 다음과 같이 실행합니다.

```bash
just infra-check prod
just infra-bootstrap workshield-session prod
just infra-ensure workshield-session prod
just infra-status workshield-session prod
```

`infra-ensure`는 다음 작업도 함께 수행합니다.

- `VLLM_API_KEY`, `RUNPOD_EMBED_API_KEY`가 비어 있으면 안전한 값을 생성하여
  `infra/config/prod.secrets.env`에 기록
- RunPod Pod에 호출 키를 바인딩하고 readiness 확인
- EC2 runtime secret을 AWS Secrets Manager에 동기화
- EC2 runtime asset과 고정 SSM 배포 Document 설치

따라서 첫 프로비저닝 직후 `infra-secrets-sync`를 다시 실행할 필요는 없습니다.
이 명령은 이후 `LAW_OC`, `ORIGIN_HEADER` 등 로컬 runtime secret 값을 직접
변경했을 때만 사용합니다.

```bash
just infra-secrets-sync workshield-session prod
```

### 6.2. 첫 배포 전 인프라 상태 확인

```bash
just infra-status workshield-session prod
```

첫 컨테이너 배포 전에는 다음 상태가 정상입니다.

| 확인 항목 | 기대 상태 |
| --- | --- |
| `WorkShieldAccess`, `WorkShieldFoundation`, `WorkShieldService` | `CREATE_COMPLETE` 또는 `UPDATE_COMPLETE` |
| `runtime.ssm_instance.ping_status` | `Online` |
| RunPod `llm`, `embed` | `RUNNING` 및 Pod ID·URL 존재 |
| `runtime.viewer_health` | 컨테이너 배포 전에는 `HTTP_502`일 수 있음 |
| `release.tag`, `api_image`, `mcp_image` | 첫 배포 전에는 `UNSET`일 수 있음 |

Stack 실패, SSM `Offline`, RunPod 소유권 오류가 있으면 GitHub 배포를 시작하지
말고 [장애 대응](../operations/troubleshooting.md)을 먼저 확인합니다.

### 6.3. GitHub 저장소와 OIDC 설정 확인

`infra/config/prod.json`의 다음 값은 workflow를 실행할 **실제 GitHub
저장소**와 정확히 일치해야 합니다.

```bash
gh auth login
gh auth status --hostname github.com
gh api "repos/<저장소 소유자>/<저장소 이름>" --jq '{
    github_owner_id: .owner.id,
    github_repository_id: .id
  }'
```

```json
{
  "github_organization": "<저장소 소유자>",
  "github_repository": "<저장소 이름>",
  "github_environment": "production",
  "github_owner_id": "<소유자 id>",
  "github_repository_id": "<저장소 id>",
  "ghcr_owner": "<GHCR package 소유자>"
}
```

현재 workflow에서는 컨테이너 게시 저장소를 실행 중인 GitHub 저장소
소유자를 기준으로 계산하므로 `ghcr_owner`도 같은 소유자로 설정합니다.
fork에서 workflow를 실행한다면 원본 organization이 아니라 fork 소유자를
사용해야 합니다. 이 값들은 CDK가 생성하는 GitHub OIDC trust와도 연결되므로
변경한 경우 `infra-bootstrap`을 다시 실행해 Access stack을 갱신합니다.

또한 다음을 확인합니다.

- `.github/workflows/`의 publish, deploy, rollback workflow가 대상 저장소에
  commit 및 push되어 있음
- workflow 입력에 사용할 `source_ref`가 원격 저장소에 존재함
- 해당 ref가 가리키는 MCP submodule commit을 GitHub Actions가 checkout할
  수 있음
- 저장소의 **Actions 권한**이 workflow 실행을 허용함

### 6.4. GitHub Environment Variable 등록

6.3에서 로그인한 GitHub CLI 계정으로 설정 명령을 실행합니다. 해당 계정에는
대상 저장소의 Environment와 Actions Variable을 생성·수정할 권한이 필요합니다.

```bash
just infra-github-configure workshield-session production prod
```

명령은 먼저 `gh auth status`로 `github.com` 로그인 상태를 확인합니다.
로그인하지 않았거나 인증이 만료되었으면 GitHub API를 호출하지 않고
`gh auth login` 안내와 함께 실패합니다.

명령은 GitHub의 `production` Environment를 생성하거나 갱신하고 다음
**비밀이 아닌 Environment Variable**을 등록합니다.

| Variable | 용도 |
| --- | --- |
| `AWS_REGION` | 배포 대상 AWS region |
| `AWS_DEPLOY_ROLE_ARN` | GitHub OIDC가 맡을 최소 권한 role |
| `SSM_DOCUMENT_NAME` | 기존 EC2에 컨테이너를 배포할 고정 Document |
| `WEB_BUCKET` | Web release와 live 파일을 저장할 S3 bucket |
| `CLOUDFRONT_DISTRIBUTION_ID` | Web 배포 후 invalidation 대상 |
| `GHCR_OWNER` | API·MCP image package 소유자 |

별도의 GitHub token을 환경 변수나 프로젝트 파일에 저장하지 않습니다.
GitHub Actions에는 AWS access key나 RunPod/runtime secret도 등록하지 않습니다.

다음 값은 **GitHub에 등록하면 안 됩니다.**

- `RUNPOD_MANAGEMENT_API_KEY`
- `VLLM_API_KEY`, `RUNPOD_EMBED_API_KEY`
- `RUNPOD_SERVERLESS_API_KEY`
- `ORIGIN_HEADER`, `LAW_OC`, `DUCKDNS_TOKEN`, `HUGGING_FACE_TOKEN`
- AWS access key와 secret access key

Workflow의 GHCR 접근에는 GitHub가 실행마다 발급하는 `GITHUB_TOKEN`을,
AWS 접근에는 단기 OIDC 자격 증명을 사용합니다.

### 6.5. API·MCP 컨테이너 게시와 배포

GitHub 저장소의 **Actions** 탭에서 다음 순서로 실행합니다.

1. **Publish container images**

   - `source_ref`: 빌드할 원격 branch, tag 또는 commit SHA
   - `image_tag`: API와 MCP가 공유할 새 불변 release tag
     (예: `2026.07.30-1`)

2. 첫 게시 후 GitHub의 **Packages**에서 API와 MCP container package를
   EC2가 인증 없이 읽을 수 있도록 public으로 설정합니다. 현재 EC2
   배포 경로에는 장기 GHCR pull credential을 저장하지 않습니다.

3. **Deploy container images**

   - `image_tag`: 1단계에서 게시한 것과 동일한 tag

게시 workflow는 AWS에 접근하지 않습니다. 배포 workflow는 기존 tag를
digest로 확정한 뒤 OIDC와 SSM을 통해 기존 EC2에만 적용합니다. 같은
`image_tag`를 다른 source 내용으로 덮어쓰지 않으므로, 변경된 이미지는
항상 새 tag로 게시합니다.

### 6.6. 컨테이너 검증과 Web 배포

컨테이너 workflow가 성공한 뒤 다시 상태를 확인합니다.

```bash
just infra-status workshield-session prod
```

이제 `runtime.viewer_health`가 정상이어야 하며 `release.tag`,
`release.api_image`, `release.mcp_image`에 방금 배포한 tag와 digest가
표시되어야 합니다.

이후 GitHub Actions의 **Deploy web release**를 실행합니다.

- `source_ref`: Web을 빌드할 원격 branch, tag 또는 commit SHA
- `web_release_tag`: 새 불변 Web release tag

Web artifact는 `releases/<web_release_tag>/`에 보존된 뒤 live 경로로
승격되고 CloudFront cache가 무효화됩니다. Web은 container image가 아니라
Vite build artifact를 S3/CloudFront로 배포합니다.

### 6.7. 롤백

롤백은 source를 다시 빌드하지 않고 이미 게시된 artifact를 재활성화합니다.

- **Roll back container images**: 복구할 기존 `image_tag` 입력
- **Roll back web release**: 복구할 기존 `web_release_tag` 입력

대상 tag나 S3 release artifact가 존재하지 않으면 자동으로 재빌드하지 않고
실패합니다. 자세한 절차는 [배포 운영](../operations/deploy.md)을 참고합니다.

### 6.8. 인프라 폐기

프로젝트 자원 폐기는 GitHub Actions가 아니라 로컬에서 수행합니다. 먼저
폐기 계획을 확인한 뒤 정확한 확인 문자열을 직접 입력합니다.

```bash
just infra-destroy-plan workshield-session prod
just infra-destroy workshield-session "DESTROY workshield-prod" prod
```

CDK bootstrap과 GitHub OIDC 기반까지 제거하려면, 다른 환경이나 저장소가
공유하지 않는다는 사실을 확인한 후 별도로 실행합니다.

```bash
just infra-purge workshield-session "PURGE workshield-prod-bootstrap" prod
```

일반적인 재배포나 프로젝트 자원 폐기에는 `infra-purge`가 필요하지 않습니다.
상세한 보존·삭제 범위는 [로컬 프로비저닝 가이드](provisioning.md)를
확인합니다.

## 7. 참고 문서 및 가이드

- [로컬 프로비저닝 가이드](provisioning.md)
- [비밀 관리 지침](../operations/secrets.md)
- [애플리케이션 배포 및 롤백](../operations/deploy.md)
- [장애 대응 가이드](../operations/troubleshooting.md)
