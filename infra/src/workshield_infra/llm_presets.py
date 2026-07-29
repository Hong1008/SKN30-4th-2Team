"""지원 vLLM model ID와 결정적인 container start command preset."""

from __future__ import annotations

import shlex

COMMON_ARGS = (
    "--host 0.0.0.0 --port 8000 --enforce-eager "
    "--gpu-memory-utilization 0.90 --max-model-len 8128"
)
MODEL_PRESETS = {
    "qwen3.5-9B-FP8-dynamic": (
        "RedHatAI/Qwen3.5-9B-FP8-dynamic "
        f"--language-model-only --reasoning-parser qwen3 {COMMON_ARGS}"
    ),
    "gemma-4-12B-it-FP8-Dynamic": (
        "RedHatAI/gemma-4-12B-it-FP8-Dynamic "
        f"--reasoning-parser gemma4 {COMMON_ARGS}"
    ),
    "EXAONE-3.5-7.8B-Instruct": (
        "LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct "
        f"--dtype bfloat16 --trust-remote-code {COMMON_ARGS}"
    ),
}


def _model_id(command: str) -> str:
    arguments = shlex.split(command)
    if not arguments:
        raise RuntimeError("빈 vLLM model preset은 사용할 수 없습니다.")
    return arguments[0]


MODEL_PRESETS_BY_MODEL = {
    _model_id(command): command for command in MODEL_PRESETS.values()
}


def resolve_model_preset(model_id: str) -> str:
    """설정의 Hugging Face model ID에 대응하는 전체 vLLM 인자를 반환한다."""

    try:
        return MODEL_PRESETS_BY_MODEL[model_id]
    except KeyError as error:
        supported = ", ".join(sorted(MODEL_PRESETS_BY_MODEL))
        raise ValueError(
            f"runpod_llm_model이 지원 preset에 없습니다: {model_id}. "
            f"지원 값: {supported}"
        ) from error
