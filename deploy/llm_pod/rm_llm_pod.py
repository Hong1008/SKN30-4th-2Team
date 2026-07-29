#!/usr/bin/env python3
import sys
import os
import re
import subprocess
import shutil
from pathlib import Path

def extract_pod_id(url: str) -> str:
    """Extract pod ID from RunPod proxy URL (e.g. https://abc123xyz-8000.proxy.runpod.net -> abc123xyz)."""
    clean_url = url.strip().strip("'\"")
    match = re.search(r"https?://([a-zA-Z0-9]+)", clean_url)
    if match:
        return match.group(1)
    return ""

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

def remove_env_keys(env_path: Path, keys_to_remove: list):
    """Remove target keys from .env file."""
    if not env_path.exists():
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in keys_to_remove:
                continue
        new_lines.append(line)
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

def main():
    repo_root = Path(__file__).resolve().parent.parent.parent
    env_file = repo_root / "api" / ".env"

    print("=" * 60)
    print("🗑️  RunPod LLM Pod Removal")
    print("=" * 60)

    base_url = read_env_var(env_file, "VLLM_BASE_URL")
    if not base_url:
        print("⚠️  No VLLM_BASE_URL found in api/.env. Nothing to delete.")
        sys.exit(0)

    print(f"📌 Found VLLM_BASE_URL: {base_url}")
    pod_id = extract_pod_id(base_url)
    if not pod_id:
        print(f"❌ Error: Could not parse Pod ID from VLLM_BASE_URL: '{base_url}'")
        sys.exit(1)

    print(f"🆔 Extracted Pod ID  : {pod_id}")

    runpodctl_bin = shutil.which("runpodctl")
    if not runpodctl_bin:
        print("❌ Error: 'runpodctl' CLI was not found in your PATH.")
        print("Please install runpodctl or run 'just install-runpod'.")
        sys.exit(1)

    cmd = [runpodctl_bin, "pod", "delete", pod_id]
    print(f"\n🛠️ Executing command:\n  {' '.join(cmd)}\n")

    try:
        subprocess.run(cmd, check=True)
        print(f"✅ Successfully deleted Pod: {pod_id}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error deleting pod {pod_id}:")
        sys.exit(1)

    # Clean up api/.env
    remove_env_keys(env_file, ["VLLM_BASE_URL", "VLLM_API_KEY"])
    print(f"🧹 Removed VLLM_BASE_URL and VLLM_API_KEY from {env_file.relative_to(repo_root)}.")
    print("=" * 60)

if __name__ == "__main__":
    main()
