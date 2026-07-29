python := if os_family() == "windows" { "py -3" } else { "python3" }

# 도움말 출력 (메뉴판)
default:
    @just --list

# RunPod vLLM LLM Pod 생성 및 api/.env 바인딩 (기본 모델: qwen3.5-9b-gguf-q8_0, 기본 GPU: NVIDIA A40)
deploy_llm_pod model="qwen3.5-9B-FP8-dynamic" gpu="NVIDIA A40":
    {{python}} deploy/deploy_llm_pod.py --model "{{model}}" --gpu "{{gpu}}"

# RunPod vLLM LLM Pod 삭제 및 api/.env의 VLLM_BASE_URL, VLLM_API_KEY 제거
rm_llm_pod:
    {{python}} deploy/rm_llm_pod.py