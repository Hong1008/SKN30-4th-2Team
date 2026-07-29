python := if os_family() == "windows" { "py -3" } else { "python3" }

# 도움말 출력 (메뉴판)
default:
    @just --list

# RunPod vLLM LLM Pod 생성 및 api/.env 바인딩 (기본 모델: qwen3.5-9b-gguf-q8_0, 기본 GPU: NVIDIA A40)
deploy_llm_pod model="qwen3.5-9B-FP8-dynamic" gpu="NVIDIA A40":
    {{python}} deploy/llm_pod/deploy_llm_pod.py --model "{{model}}" --gpu "{{gpu}}"

# RunPod vLLM LLM Pod 삭제 및 api/.env의 VLLM_BASE_URL, VLLM_API_KEY 제거
rm_llm_pod:
    {{python}} deploy/llm_pod/rm_llm_pod.py

# AWS CDK 템플릿 정적 생성 (실제 AWS 계정 접근 없음)
aws-synth:
    cd deploy/aws/iac && npm exec cdk -- synth

# 운영 Compose 파일의 변수 치환·스키마 검사 (컨테이너 실행 없음)
aws-compose-config:
    docker compose --env-file deploy/aws/env/prod.env.example -f deploy/aws/compose.prod.yaml config

# 운영 API/MCP 이미지 로컬 빌드
aws-build-api:
    docker build --tag workshield-api:local api

aws-build-mcp:
    docker build --tag workshield-mcp:local mcp
