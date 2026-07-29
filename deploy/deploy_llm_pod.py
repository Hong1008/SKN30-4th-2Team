#!/usr/bin/env python3
import sys
import os
import json
import argparse
import subprocess
import shutil
import secrets
import time
from pathlib import Path

# 모든 모델 공통 기본 옵션
COMMON_ARGS = "--host 0.0.0.0 --port 8000 --enforce-eager --gpu-memory-utilization 0.90 --max-model-len 8128 "

# 모델 프리셋 정의
MODEL_PRESETS = {
    "qwen3.5-9B-FP8-dynamic": (
        "RedHatAI/Qwen3.5-9B-FP8-dynamic "
        "--language-model-only "
        "--reasoning-parser qwen3 "
        f"{COMMON_ARGS}"
    ),
    "gemma-4-12B-it-FP8-Dynamic": (
        "RedHatAI/gemma-4-12B-it-FP8-Dynamic "
        "--reasoning-parser gemma4 "
        f"{COMMON_ARGS}"
    ),
    "EXAONE-3.5-7.8B-Instruct": (
        "LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct "
        "--dtype bfloat16 "
        "--trust-remote-code "
        f"{COMMON_ARGS}"
    )
}

def generate_api_key() -> str:
    """Generate 32-byte hex string (same as openssl rand -hex 32)."""
    if shutil.which("openssl"):
        try:
            res = subprocess.run(["openssl", "rand", "-hex", "32"], capture_output=True, text=True, check=True)
            key = res.stdout.strip()
            if key:
                return key
        except Exception:
            pass
    # Fallback to Python secrets module for cross-platform compatibility
    return secrets.token_hex(32)

def read_env_var(env_path: Path, key: str) -> str:
    """Read a specific key value from .env file."""
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip().strip("'\"")
    return ""

def update_env_file(env_path: Path, updates: dict):
    """Update or append environment variables in .env file."""
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    
    updated_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}='{updates[key]}'")
                updated_keys.add(key)
                continue
        new_lines.append(line)
    
    for key, val in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}='{val}'")
            
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

def main():
    repo_root = Path(__file__).resolve().parent.parent
    env_file = repo_root / "api" / ".env"

    parser = argparse.ArgumentParser(description="Deploy RunPod vLLM Pod with model presets")
    parser.add_argument("--model", "-m", default="qwen3.5-9b-gguf-q8_0", help="Model preset key or raw start args")
    parser.add_argument("--gpu", "-g", default="NVIDIA A40", help="GPU ID (default: NVIDIA A40)")
    parser.add_argument("--custom-args", default="", help="Override docker args directly")
    args = parser.parse_args()

    gpu_id = args.gpu
    template_id = "6o2zycj91k"
    
    # 1. Docker Args 구성
    if args.custom_args:
        docker_args = args.custom_args
        model_name = "custom"
    elif args.model in MODEL_PRESETS:
        model_name = args.model
        docker_args = MODEL_PRESETS[args.model]
    else:
        print(f"❌ Unknown model preset: '{args.model}'")
        print(f"📋 Available presets: {', '.join(MODEL_PRESETS.keys())}")
        print("Or pass custom docker args using --custom-args.")
        sys.exit(1)
    
    print("=" * 60)
    print("🚀 RunPod LLM Pod Deployment")
    print("=" * 60)
    print(f"📌 Model Preset: {model_name}")
    print(f"📌 GPU Target  : {gpu_id}")
    print(f"📌 Template ID : {template_id}")
    print(f"📌 Docker Args : {docker_args}")

    # 2. API KEY 생성
    api_key = generate_api_key()
    print(f"\n🔑 Generated VLLM_API_KEY (openssl rand -hex 32):")
    print(f"   {api_key}\n")

    # 3. HF_TOKEN 읽기 (Rate limit 및 비공개 레포지토리 다운로드 대응)
    hf_token = read_env_var(env_file, "HUGGING_FACE_TOKEN") or read_env_var(env_file, "HF_TOKEN")

    # 4. runpodctl 존재 확인
    runpodctl_bin = shutil.which("runpodctl")
    if not runpodctl_bin:
        print("❌ Error: 'runpodctl' CLI was not found in your PATH.")
        print("Please install runpodctl or run 'just install-runpod'.")
        sys.exit(1)

    # 5. Pod 생성 명령어 조립 및 실행
    pod_env = {"VLLM_API_KEY": api_key}
    if hf_token:
        pod_env["HF_TOKEN"] = hf_token
        pod_env["HUGGING_FACE_HUB_TOKEN"] = hf_token

    env_json = json.dumps(pod_env)
    cmd = [
        runpodctl_bin, "pod", "create",
        "--template-id", template_id,
        "--gpu-id", gpu_id,
        "--env", env_json,
        "--docker-args", docker_args,
        "-o", "json"
    ]
    
    print(f"🛠️ Executing command:\n  {' '.join(cmd)}\n")
    
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        out = res.stdout.strip()
        data = json.loads(out)
        pod_id = data.get("id")
        if not pod_id:
            print("❌ Failed to parse Pod ID from output:")
            print(out)
            sys.exit(1)
    except subprocess.CalledProcessError as e:
        print("❌ Error creating pod:")
        print(e.stderr or e.stdout)
        sys.exit(1)
    except json.JSONDecodeError:
        print("❌ Error parsing JSON output from runpodctl:")
        print(res.stdout)
        sys.exit(1)

    # 7. Pod Base URL 생성 (Template 8000번 포트 반영)
    base_url = f"https://{pod_id}-8000.proxy.runpod.net"
    
    print("\n" + "=" * 60)
    print("🎉 Pod Deployment Successful!")
    print(f"🆔 Pod ID       : {pod_id}")
    print(f"🌐 VLLM_BASE_URL: {base_url}")
    print(f"🔑 VLLM_API_KEY : {api_key}")
    print("=" * 60)

    # 8. api/.env 파일에 환경변수 자동 업데이트
    updates = {
        "VLLM_API_KEY": api_key,
        "VLLM_BASE_URL": base_url
    }
    update_env_file(env_file, updates)
    print(f"\n✅ Updated {env_file.relative_to(repo_root)} with new VLLM_API_KEY and VLLM_BASE_URL.")

if __name__ == "__main__":
    main()
