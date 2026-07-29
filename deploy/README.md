# RunPod vLLM Pod 배포 가이드

이 디렉터리의 스크립트와 루트 `justfile`은 RunPod에 vLLM Pod를 생성하거나 삭제하고, API 서버가 사용할 연결 정보를 `api/.env`에 자동으로 반영합니다.

## 사전 요구사항

- Python 3
- [just](https://github.com/casey/just)
- [runpodctl](https://docs.runpod.io/cli/get-started) — 설치 후 RunPod API 키로 인증을 완료해야 합니다.
- Pod 생성 비용을 위한 RunPod 계정 및 크레딧

선택 사항으로, Hugging Face에서 인증이 필요한 모델을 내려받거나 다운로드 제한을 완화하려면 `api/.env`에 아래 둘 중 하나를 설정합니다.

```dotenv
HUGGING_FACE_TOKEN=hf_...
# 또는
HF_TOKEN=hf_...
```

배포 스크립트는 토큰이 있으면 Pod 환경 변수 `HF_TOKEN`과 `HUGGING_FACE_HUB_TOKEN`으로 전달합니다.

## Pod 생성

저장소 루트에서 다음 명령을 실행합니다.

```bash
just deploy_llm_pod
```

기본값은 `qwen3.5-9B-FP8-dynamic` 모델과 `NVIDIA A40` GPU입니다. 다른 프리셋이나 GPU를 사용하려면 인자를 지정합니다.

```bash
just deploy_llm_pod gemma-4-12B-it-FP8-Dynamic "NVIDIA A40"
just deploy_llm_pod EXAONE-3.5-7.8B-Instruct "NVIDIA A40"
```

스크립트를 직접 실행할 수도 있습니다.

```bash
python3 deploy/deploy_llm_pod.py \
  --model qwen3.5-9B-FP8-dynamic \
  --gpu "NVIDIA A40"
```

지원하는 모델 프리셋은 다음과 같습니다.

| 프리셋 | Hugging Face 모델 |
| --- | --- |
| `qwen3.5-9B-FP8-dynamic` | `RedHatAI/Qwen3.5-9B-FP8-dynamic` |
| `gemma-4-12B-it-FP8-Dynamic` | `RedHatAI/gemma-4-12B-it-FP8-Dynamic` |
| `EXAONE-3.5-7.8B-Instruct` | `LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct` |

생성에 성공하면 스크립트는 새 `VLLM_API_KEY`를 만들고 Pod ID 및 엔드포인트를 출력한 뒤, `api/.env`에 아래 값을 저장합니다.

```dotenv
VLLM_BASE_URL='https://<pod-id>-8000.proxy.runpod.net'
VLLM_API_KEY='<자동 생성된 키>'
```

API 서버에서 vLLM을 사용하려면 `api/.env`의 `LLM_PROVIDER=vllm` 설정과 `LLM_MODEL`도 해당 Pod가 제공하는 모델에 맞게 설정합니다. 자세한 API 설정은 [api/README.md](../api/README.md)를 참고하세요.

### 사용자 정의 vLLM 실행 인자

프리셋 대신 vLLM Docker 실행 인자를 직접 넘기려면 `--custom-args`를 사용합니다. 이 경우 `--model` 값은 사용되지 않습니다.

```bash
python3 deploy/deploy_llm_pod.py \
  --gpu "NVIDIA A40" \
  --custom-args "Qwen/Qwen2.5-7B-Instruct --host 0.0.0.0 --port 8000"
```

## Pod 삭제

Pod를 더 이상 사용하지 않을 때는 반드시 아래 명령으로 삭제해 비용 발생을 중지합니다.

```bash
just rm_llm_pod
```

삭제 스크립트는 `api/.env`의 `VLLM_BASE_URL`에서 Pod ID를 읽어 RunPod Pod를 삭제한 뒤 `VLLM_BASE_URL`과 `VLLM_API_KEY`를 제거합니다. `VLLM_BASE_URL`이 없으면 삭제할 대상이 없다고 안내하고 종료합니다.

## 문제 해결

- `runpodctl CLI was not found`: `runpodctl`을 설치하고 셸의 `PATH`에 포함했는지 확인합니다.
- Pod 생성이 실패함: RunPod 인증 상태, 잔여 크레딧, 선택한 GPU의 가용성 및 GPU 이름을 확인합니다.
- 모델 다운로드가 실패함: 필요한 경우 `api/.env`에 `HUGGING_FACE_TOKEN` 또는 `HF_TOKEN`을 설정한 뒤 다시 생성합니다.
- API가 Pod에 연결되지 않음: `api/.env`의 `VLLM_BASE_URL`, `VLLM_API_KEY`, `LLM_PROVIDER`, `LLM_MODEL`을 확인하고 Pod가 준비될 때까지 기다립니다.
