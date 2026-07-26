python := if os_family() == "windows" { "py -3" } else { "python3" }

# Ollama Pod 이미지 명령을 미리 확인합니다. 실제 build에는 `--confirm`이 필요합니다.
ollama-image-build-dry-run:
    {{python}} deploy/manage_ollama_pod.py build

# linux/amd64 Ollama 이미지를 build합니다. api/.env에 RUNPOD_OLLAMA_IMAGE이 필요합니다.
ollama-image-build:
    {{python}} deploy/manage_ollama_pod.py build --confirm

# build한 이미지를 Docker registry에 push합니다.
ollama-image-push:
    {{python}} deploy/manage_ollama_pod.py push --confirm

# registry 이미지를 참조하는 Runpod Pod Template을 생성합니다.
ollama-template-create:
    {{python}} deploy/manage_ollama_pod.py template-create --confirm

# A5000 Ollama Pod를 생성합니다. api/.env에 Template ID가 필요합니다.
ollama-pod-create:
    {{python}} deploy/manage_ollama_pod.py pod-create --confirm

# 계정의 Pod 상태를 조회합니다.
ollama-pod-list:
    {{python}} deploy/manage_ollama_pod.py pod-list

# api/.env의 RUNPOD_OLLAMA_POD_ID에 해당하는 Pod 상세를 조회합니다.
ollama-pod-info:
    {{python}} deploy/manage_ollama_pod.py pod-info

# GPU 실행만 멈춥니다. 비용을 완전히 끝내려면 delete를 사용하세요.
ollama-pod-stop:
    {{python}} deploy/manage_ollama_pod.py pod-stop --confirm

# Pod와 연결 디스크를 삭제합니다. 다음 시작 시 모델을 다시 내려받습니다.
ollama-pod-delete:
    {{python}} deploy/manage_ollama_pod.py pod-delete --confirm
