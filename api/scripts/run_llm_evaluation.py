#!/usr/bin/env python3
"""MCP 참조형 fixture로 Suggestions LLM 경량 평가를 실행한다."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import subprocess
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import httpx

from app.config import API_ROOT, Settings
from app.core.common.errors import ExternalServiceTimeoutError
from app.core.llm.evaluation import (
    ResolvedLLMEvaluationFixture,
    load_evaluation_suite,
    resolve_evaluation_fixtures,
)
from app.core.llm.factory import create_chat_model
from app.core.llm.provider.vllm import _api_base_url
from app.domains.reviews.domain import MCPReviewStatus, Review, ReviewState
from app.domains.suggestions.schemas import SuggestionRequest
from app.domains.suggestions.service import generate_suggestion


REPOSITORY_ROOT = API_ROOT.parent
DEFAULT_SUITE = API_ROOT / "evaluation/llm/fixtures/suggestions_v1.json"
DEFAULT_MODEL = "RedHatAI/Qwen3.5-9B-FP8-dynamic"
METRIC_TTFT_SUM = "vllm:time_to_first_token_seconds_sum"
METRIC_TTFT_COUNT = "vllm:time_to_first_token_seconds_count"
METRIC_GENERATION_TOKENS = "vllm:generation_tokens_total"


def _jsonable(value: object) -> object:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return value


def _value(source: object, key: str) -> object | None:
    """객체와 mapping 양쪽에서 안전하게 값을 읽는다."""
    if isinstance(source, Mapping):
        return source.get(key)
    return getattr(source, key, None)


def _record_generation_metadata(
    record: dict[str, object],
    source: object | None,
) -> None:
    """AIMessage 또는 OpenAI completion에서 종료 사유와 토큰을 기록한다."""
    if source is None:
        return
    response_metadata = _value(source, "response_metadata")
    finish_reason = (
        _value(response_metadata, "finish_reason")
        if response_metadata is not None
        else None
    )
    choices = _value(source, "choices")
    if finish_reason is None and isinstance(choices, list) and choices:
        finish_reason = _value(choices[0], "finish_reason")
    if finish_reason is not None:
        record["finish_reason"] = str(finish_reason)

    usage = _value(source, "usage_metadata") or _value(source, "usage")
    if usage is None and response_metadata is not None:
        usage = _value(response_metadata, "token_usage")
    if usage is None:
        return
    prompt_tokens = _value(usage, "input_tokens")
    if prompt_tokens is None:
        prompt_tokens = _value(usage, "prompt_tokens")
    completion_tokens = _value(usage, "output_tokens")
    if completion_tokens is None:
        completion_tokens = _value(usage, "completion_tokens")
    total_tokens = _value(usage, "total_tokens")
    token_usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
    record["token_usage"] = {
        key: int(value)
        for key, value in token_usage.items()
        if isinstance(value, int | float)
    }


class _RecordingStructuredRunnable:
    def __init__(
        self,
        delegate: object,
        records: list[dict[str, object]],
    ) -> None:
        self._delegate = delegate
        self._records = records

    async def ainvoke(self, prompt: str) -> object:
        started = time.monotonic()
        record: dict[str, object] = {
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        }
        try:
            result = await self._delegate.ainvoke(prompt)
            output = result
            if isinstance(result, dict) and "parsed" in result:
                _record_generation_metadata(record, result.get("raw"))
                parsing_error = result.get("parsing_error")
                if isinstance(parsing_error, Exception):
                    raise parsing_error
                output = result["parsed"]
            record["status"] = "success"
            record["output"] = _jsonable(output)
            return output
        except Exception as error:
            _record_generation_metadata(
                record,
                getattr(error, "completion", None),
            )
            record["status"] = "error"
            record["error_type"] = type(error).__name__
            raise
        finally:
            record["elapsed_seconds"] = round(time.monotonic() - started, 6)
            self._records.append(record)


class RecordingChatModel:
    """실제 provider 호출을 위임하고 repair를 포함한 시도별 결과를 기록한다."""

    def __init__(self, delegate: object) -> None:
        self._delegate = delegate
        self.records: list[dict[str, object]] = []

    def with_structured_output(self, schema: type) -> _RecordingStructuredRunnable:
        return _RecordingStructuredRunnable(
            self._delegate.with_structured_output(schema, include_raw=True),
            self.records,
        )


class FixtureGroundingTool:
    """외부 법령 조회 없이 LLM 생성 경계만 평가하는 합성 grounding."""

    name = "get_category_grounding"

    def __init__(self, fixture_id: str, category: str) -> None:
        self._fixture_id = fixture_id
        self._category = category

    async def ainvoke(self, payload: dict[str, object]) -> dict[str, object]:
        if payload["category"] != self._category:
            raise ValueError("fixture category와 grounding 요청이 다릅니다.")
        return {
            "status": "OK",
            "category": {
                "code": self._category,
                "label": self._category,
            },
            "grounding": [
                {
                    "source_id": f"law_eval_{self._fixture_id}",
                    "law_name": "합성 평가 근거",
                    "article": self._fixture_id,
                    "text": (
                        "이 원문은 제공된 사용자 조항과 표준조항 범위 안에서 "
                        "협의 문구를 생성하기 위한 합성 평가 근거입니다."
                    ),
                    "source": "WorkShield LLM 평가 fixture",
                }
            ],
        }


def _build_review(fixture: ResolvedLLMEvaluationFixture) -> tuple[Review, str]:
    now = datetime.now(UTC)
    fixture_id = fixture.overlay.fixture_id
    clause_id = f"uc_eval_{fixture_id}"
    review = Review.restore(
        review_id=f"rev_eval_{fixture_id}",
        session_id=f"ses_eval_{fixture_id}",
        idempotency_key=f"eval-{fixture_id}",
        state=ReviewState.COMPLETED,
        contract_type=fixture.standard["contract_type"],
        created_at=now,
        expires_at=now + timedelta(hours=1),
        mcp_review_status=MCPReviewStatus.OK,
        result={
            "status": "OK",
            "contract_type": fixture.standard["contract_type"],
            "clause_results": [
                {
                    "user_clause_id": clause_id,
                    "user_clause": fixture.user_clause,
                    "deviation": fixture.deviation,
                    "match": {
                        "status": "CANDIDATE_SELECTED",
                        "standard": fixture.standard,
                        "score": 1.0,
                    },
                    "toxic_patterns": [],
                }
            ],
            "missing_standard_clauses": [],
            "message": None,
        },
        started_at=now,
        completed_at=now,
    )
    return review, clause_id


def _request_text(url: str, settings: Settings) -> str:
    if settings.vllm_api_key is None:
        raise ValueError("VLLM_API_KEY가 필요합니다.")
    response = httpx.get(
        url,
        headers={
            "Authorization": (
                f"Bearer {settings.vllm_api_key.get_secret_value()}"
            ),
            "User-Agent": "OpenAI/Python 2.15.0",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def _metric_total(metrics: str, name: str) -> float:
    total = 0.0
    pattern = re.compile(rf"^{re.escape(name)}(?:\{{[^}}]*\}})?\s+(\S+)$")
    for line in metrics.splitlines():
        match = pattern.match(line)
        if match:
            total += float(match.group(1))
    return total


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 6)


def _sanitize_metadata(value: object) -> object:
    if isinstance(value, dict):
        sanitized: dict[str, object] = {}
        for key, item in value.items():
            normalized = key.lower()
            if any(
                marker in normalized
                for marker in ("secret", "token", "api_key", "apikey", "env")
            ):
                sanitized[key] = "<redacted>"
            else:
                sanitized[key] = _sanitize_metadata(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_metadata(item) for item in value]
    return value


def _runpod_metadata(settings: Settings) -> dict[str, object]:
    if settings.vllm_base_url is None:
        return {"status": "unavailable"}
    hostname = urlparse(str(settings.vllm_base_url)).hostname or ""
    suffix = "-8000.proxy.runpod.net"
    if not hostname.endswith(suffix):
        return {"status": "not_runpod_proxy"}
    pod_id = hostname.removesuffix(suffix)
    try:
        completed = subprocess.run(
            [
                "runpodctl",
                "pod",
                "get",
                pod_id,
                "--include-machine",
                "-o",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "status": "ok",
            "pod": _sanitize_metadata(json.loads(completed.stdout)),
        }
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        return {
            "status": "error",
            "error_type": type(error).__name__,
        }


def _git_metadata() -> dict[str, object]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    return {"commit": commit, "worktree_dirty": dirty}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assess_result(
    fixture: ResolvedLLMEvaluationFixture,
    *,
    response: object,
    attempts: list[dict[str, object]],
    elapsed_seconds: float,
    repetition: int,
) -> dict[str, object]:
    payload = response.model_dump(mode="json")
    text = payload.get("text") or ""
    source_keys = set(payload.get("used_source_keys") or [])
    required_keys = {key.value for key in fixture.overlay.required_source_keys}
    missing_terms = [
        term for term in fixture.overlay.required_terms if term not in text
    ]
    missing_source_keys = sorted(required_keys - source_keys)
    passed = (
        payload["outcome"] == "GENERATED"
        and not missing_terms
        and not missing_source_keys
        and len(attempts) <= 2
    )
    return {
        "fixture_id": fixture.overlay.fixture_id,
        "mcp_case_id": fixture.overlay.mcp_case_id,
        "repetition": repetition,
        "elapsed_seconds": round(elapsed_seconds, 6),
        "attempt_count": len(attempts),
        "repair_used": len(attempts) == 2,
        "attempts": attempts,
        "response": payload,
        "missing_terms": missing_terms,
        "missing_source_keys": missing_source_keys,
        "passed": passed,
    }


def _assess_error_result(
    fixture: ResolvedLLMEvaluationFixture,
    *,
    attempts: list[dict[str, object]],
    elapsed_seconds: float,
    repetition: int,
    error: ExternalServiceTimeoutError,
) -> dict[str, object]:
    """한 fixture의 timeout을 전체 평가 중단 대신 실패 결과로 기록한다."""
    required_keys = sorted(
        key.value for key in fixture.overlay.required_source_keys
    )
    return {
        "fixture_id": fixture.overlay.fixture_id,
        "mcp_case_id": fixture.overlay.mcp_case_id,
        "repetition": repetition,
        "elapsed_seconds": round(elapsed_seconds, 6),
        "attempt_count": len(attempts),
        "repair_used": len(attempts) == 2,
        "attempts": attempts,
        "response": {
            "outcome": error.code,
            "text": None,
        },
        "missing_terms": fixture.overlay.required_terms,
        "missing_source_keys": required_keys,
        "error_type": type(error).__name__,
        "passed": False,
    }


def _build_summary(
    results: list[dict[str, object]],
    *,
    metrics_before: str,
    metrics_after: str,
    expected_total: int = 16,
) -> dict[str, object]:
    latencies = [float(item["elapsed_seconds"]) for item in results]
    passed = sum(bool(item["passed"]) for item in results)
    repairs = sum(bool(item["repair_used"]) for item in results)
    invalid_outcomes = sum(
        item["response"]["outcome"]  # type: ignore[index]
        in {
            "LLM_OUTPUT_INVALID",
            "GENERATED_FACT_NOT_GROUNDED",
            "LLM_TIMEOUT",
        }
        for item in results
    )
    generation_tokens = (
        _metric_total(metrics_after, METRIC_GENERATION_TOKENS)
        - _metric_total(metrics_before, METRIC_GENERATION_TOKENS)
    )
    ttft_sum = (
        _metric_total(metrics_after, METRIC_TTFT_SUM)
        - _metric_total(metrics_before, METRIC_TTFT_SUM)
    )
    ttft_count = (
        _metric_total(metrics_after, METRIC_TTFT_COUNT)
        - _metric_total(metrics_before, METRIC_TTFT_COUNT)
    )
    hard_gate_passed = invalid_outcomes == 0
    is_full_evaluation = len(results) == expected_total
    attempt_records = [
        attempt
        for result in results
        for attempt in result.get("attempts", [])
        if isinstance(attempt, dict)
    ]
    completion_tokens = [
        int(token_usage["completion_tokens"])
        for attempt in attempt_records
        if isinstance(
            token_usage := attempt.get("token_usage"),
            dict,
        )
        and isinstance(token_usage.get("completion_tokens"), int | float)
    ]
    finish_reasons: dict[str, int] = {}
    for attempt in attempt_records:
        finish_reason = attempt.get("finish_reason")
        if isinstance(finish_reason, str):
            finish_reasons[finish_reason] = (
                finish_reasons.get(finish_reason, 0) + 1
            )
    return {
        "mode": "full" if is_full_evaluation else "dry_run",
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "repairs": repairs,
        "invalid_or_ungrounded": invalid_outcomes,
        "latency_seconds": {
            "p50": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
            "max": round(max(latencies), 6) if latencies else None,
        },
        "generation_tokens": round(generation_tokens),
        "completion_tokens_per_call": {
            "values": completion_tokens,
            "p50": _percentile(
                [float(value) for value in completion_tokens],
                0.5,
            ),
            "p95": _percentile(
                [float(value) for value in completion_tokens],
                0.95,
            ),
            "max": max(completion_tokens) if completion_tokens else None,
        },
        "finish_reasons": finish_reasons,
        "average_ttft_seconds": (
            round(ttft_sum / ttft_count, 6) if ttft_count > 0 else None
        ),
        "criteria": {
            "structured_and_expectation": f"{passed}/{len(results)}",
            "requires_at_least": 15,
            "hard_gate_passed": hard_gate_passed,
            "overall_passed": (
                passed >= 15 and hard_gate_passed
                if is_full_evaluation
                else None
            ),
        },
    }


def _write_report(
    path: Path,
    *,
    manifest: dict[str, object],
    summary: dict[str, object],
    results: list[dict[str, object]],
) -> None:
    failures = [item for item in results if not item["passed"]]
    lines = [
        f"# {manifest['model_id']} LLM 검증 결과",
        "",
        f"- 실행 시각: {manifest['started_at']}",
        f"- 모델: `{manifest['model_id']}`",
        f"- 실행 건수: {summary['total']}",
        f"- 통과: {summary['passed']}",
        f"- repair: {summary['repairs']}",
        (
            "- 최종 판정: "
            + (
                "**DRY RUN**"
                if summary["criteria"]["overall_passed"] is None  # type: ignore[index]
                else (
                    "**PASS**"
                    if summary["criteria"]["overall_passed"]  # type: ignore[index]
                    else "**FAIL**"
                )
            )
        ),
        "",
        "## 성능",
        "",
        f"- latency: `{json.dumps(summary['latency_seconds'], ensure_ascii=False)}`",
        f"- 평균 TTFT: `{summary['average_ttft_seconds']}` 초",
        f"- 생성 토큰: `{summary['generation_tokens']}`",
        (
            "- 호출별 completion tokens: "
            f"`{json.dumps(summary['completion_tokens_per_call'], ensure_ascii=False)}`"
        ),
        f"- finish reasons: `{json.dumps(summary['finish_reasons'], ensure_ascii=False)}`",
        "",
        "## 실패 사례",
        "",
    ]
    if failures:
        for item in failures:
            lines.append(
                f"- `{item['fixture_id']}` 반복 {item['repetition']}: "
                f"outcome={item['response']['outcome']}, "  # type: ignore[index]
                f"missing_terms={item['missing_terms']}, "
                f"missing_source_keys={item['missing_source_keys']}"
            )
    else:
        lines.append("- 없음")
    lines.extend([
        "",
        "## 한계",
        "",
        "- 법률 전문가 평가는 수행하지 않았다.",
        "- MCP 품질은 기존 `mcp/quality` 결과를 재사용했다.",
        "- model revision과 tokenizer hash는 server에서 별도 제공되지 않으면 미확인으로 기록한다.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


async def _run(args: argparse.Namespace) -> Path:
    suite_path = Path(args.suite).resolve()
    suite = load_evaluation_suite(suite_path)
    fixtures = resolve_evaluation_fixtures(
        suite,
        repository_root=REPOSITORY_ROOT,
    )
    if args.fixture:
        fixtures = [
            fixture
            for fixture in fixtures
            if fixture.overlay.fixture_id == args.fixture
        ]
        if not fixtures:
            raise ValueError(f"평가 fixture가 없습니다: {args.fixture}")
    settings = Settings(
        app_env="local",
        llm_provider="vllm",
        llm_model=args.model,
        llm_temperature=0,
        llm_top_p=1,
        llm_seed=args.seed,
        llm_max_completion_tokens=1000,
    )
    if settings.vllm_base_url is None or settings.vllm_api_key is None:
        raise ValueError("VLLM_BASE_URL과 VLLM_API_KEY가 필요합니다.")
    api_base = _api_base_url(settings.vllm_base_url)
    models = json.loads(_request_text(f"{api_base}/models", settings))
    model_ids = [item["id"] for item in models.get("data", [])]
    if args.model not in model_ids:
        raise ValueError(
            f"endpoint model과 평가 model이 다릅니다: {model_ids}"
        )
    server_base = api_base.removesuffix("/v1")
    version = json.loads(_request_text(f"{server_base}/version", settings))
    metrics_before = _request_text(f"{server_base}/metrics", settings)

    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else (
            API_ROOT
            / "evaluation/llm/outputs"
            / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        )
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "metrics-before.txt").write_text(
        metrics_before,
        encoding="utf-8",
    )

    model = RecordingChatModel(create_chat_model(settings))
    results: list[dict[str, object]] = []
    started_at = datetime.now(UTC)
    for fixture in fixtures:
        for repetition in range(1, args.repetitions + 1):
            review, clause_id = _build_review(fixture)
            runtime = SimpleNamespace(
                tools=(
                    FixtureGroundingTool(
                        fixture.overlay.fixture_id,
                        fixture.standard["category"],
                    ),
                )
            )
            record_start = len(model.records)
            started = time.monotonic()
            try:
                response = await generate_suggestion(
                    review,
                    SuggestionRequest(
                        user_clause_id=clause_id,
                        purpose=fixture.overlay.purpose,
                        inputs=fixture.overlay.provided_inputs,
                    ),
                    runtime=runtime,
                    model=model,  # type: ignore[arg-type]
                    settings=settings,
                )
            except ExternalServiceTimeoutError as error:
                elapsed = time.monotonic() - started
                attempts = model.records[record_start:]
                result = _assess_error_result(
                    fixture,
                    attempts=attempts,
                    elapsed_seconds=elapsed,
                    repetition=repetition,
                    error=error,
                )
            else:
                elapsed = time.monotonic() - started
                attempts = model.records[record_start:]
                result = _assess_result(
                    fixture,
                    response=response,
                    attempts=attempts,
                    elapsed_seconds=elapsed,
                    repetition=repetition,
                )
            results.append(result)
            print(
                json.dumps(
                    {
                        "fixture_id": result["fixture_id"],
                        "repetition": repetition,
                        "outcome": result["response"]["outcome"],  # type: ignore[index]
                        "passed": result["passed"],
                        "seconds": result["elapsed_seconds"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    metrics_after = _request_text(f"{server_base}/metrics", settings)
    (output_dir / "metrics-after.txt").write_text(
        metrics_after,
        encoding="utf-8",
    )
    summary = _build_summary(
        results,
        metrics_before=metrics_before,
        metrics_after=metrics_after,
    )
    manifest = {
        "schema_version": 1,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "model_id": args.model,
        "model_revision": "unresolved",
        "tokenizer_hash": "unresolved",
        "provider": "vllm",
        "vllm_version": version.get("version"),
        "generation": {
            "temperature": settings.llm_temperature,
            "top_p": settings.llm_top_p,
            "seed": settings.llm_seed,
            "max_completion_tokens": settings.llm_max_completion_tokens,
            "thinking": False,
            "repetitions": args.repetitions,
            "concurrency": 1,
        },
        "fixture_sha256": _sha256_file(suite_path),
        "prompt_sha256": sorted({
            str(record["prompt_sha256"]) for record in model.records
        }),
        "git": _git_metadata(),
        "runpod": _runpod_metadata(settings),
    }
    (output_dir / "evaluation_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (output_dir / "results.ndjson").open("w", encoding="utf-8") as file:
        for result in results:
            file.write(json.dumps(result, ensure_ascii=False) + "\n")
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_report(
        output_dir / "report.md",
        manifest=manifest,
        summary=summary,
        results=results,
    )
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--suite", default=str(DEFAULT_SUITE))
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--fixture")
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions는 1 이상이어야 합니다.")
    try:
        output_dir = asyncio.run(_run(args))
    except httpx.HTTPError as error:
        raise SystemExit(f"vLLM 평가 연결 실패: {type(error).__name__}") from error
    print(f"evaluation output: {output_dir}")


if __name__ == "__main__":
    main()
