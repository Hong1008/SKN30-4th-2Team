# LLM 검증 결과 - LGAI EXAONE 3.5 7.8B Instruct AWQ

- 상태: 경량 운영 적합성 검증 실패
- 실행일: 2026-07-28
- 공통 규격: [LLM 검증](LLM%20검증.md)
- 모델: `LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct-AWQ`
- provider: `vllm`
- dry-run ID: `20260728T060842Z`
- 전체 평가 ID: `20260728T060924Z`

## 1. 결론

책임 fixture dry-run은 2/2 통과해 전체 평가 가치가 있다고 판단했다. 그러나
동일 설정으로 8개 fixture를 각 2회 실행한 결과 책임 2건만 통과하고 나머지
14건은 모두 1000-token 상한에서 구조화 응답을 끝내지 못했다.

통과 기준인 15/16에 미달하고 hard gate도 실패했으므로 현재 WorkShield 운영
모델로 채택하지 않는다.

| 항목 | dry-run | 전체 평가 |
| --- | ---: | ---: |
| fixture | 1개 | 8개 |
| 실행 | 2회 | 16회 |
| 통과 | 2/2 | 2/16 |
| `finish_reason=stop` | 2 | 2 |
| `finish_reason=length` | 0 | 14 |
| repair | 0 | 0 |
| 최종 판정 | 전체 평가 진행 | FAIL |

## 2. 실행 조건

| 항목 | 값 |
| --- | --- |
| vLLM | `0.26.0` |
| GPU | NVIDIA A40 1장 |
| image | `vllm/vllm-openai:latest` |
| temperature | `0` |
| top_p | `1` |
| seed | `42` |
| max completion tokens | `1000` |
| thinking | OFF |
| concurrency | 1 |
| fixture hash | `6fc9fe3b781962e9799475f73aae7fbcee52589e6176d59840555db7cb8f38c4` |

모델 revision, tokenizer hash, image digest는 확인하지 못했다.

## 3. Dry-run

책임·손해배상 fixture는 두 번 모두 동일하게 정상 종료했다.

| 항목 | 반복 1 | 반복 2 |
| --- | ---: | ---: |
| prompt tokens | 714 | 714 |
| completion tokens | 217 | 217 |
| total tokens | 931 | 931 |
| finish reason | `stop` | `stop` |
| latency | 7.105초 | 4.063초 |
| 결과 | PASS | PASS |

응답은 `귀책`과 `손해`를 포함하고 `SRC_USER`, `SRC_STANDARD`를 사용했다.
다만 줄바꿈 표현으로 올바르지 않은 HTML 형태인 `</br>`를 사용했다.

## 4. 전체 평가

| 항목 | 결과 |
| --- | ---: |
| 총 실행 | 16 |
| 통과 | 2 |
| 실패 | 14 |
| `LLM_OUTPUT_INVALID` | 14 |
| 생성 토큰 | 14,434 |
| 호출별 completion token p50 | 1,000 |
| 호출별 completion token p95 | 1,000 |
| 호출별 completion token max | 1,000 |

책임 fixture 2건만 각각 217 tokens에서 `stop`으로 끝났다. 다음 7개
fixture의 두 반복은 모두 정확히 1000 tokens에서 `length`로 종료됐다.

- 대금·지급
- 계약 해지
- 지식재산권
- 비밀유지
- 업무 범위
- 수치 grounding
- 프롬프트 인젝션

실패 호출의 prompt 길이는 704~1,266 tokens로 분포했다. 가장 짧은 축에
속하는 지급 prompt도 실패했으므로 단순히 입력이 길어서 발생한 현상으로
보기 어렵다. fixture 내용에 따라 JSON Schema guided generation을 종료하는
안정성이 크게 달라지는 것으로 판단한다.

## 5. 안전성 해석

14건의 불완전 응답은 서비스에서 모두 `LLM_OUTPUT_INVALID`로 차단됐다.
불완전한 JSON을 사용자 결과로 반환하거나 이어 쓰기 repair를 수행하지
않았으므로 fail-closed 동작은 정상이다.

- 허용되지 않은 source key가 최종 반환된 사례: 0
- 내부 ID가 최종 반환된 사례: 0
- 혼합 언어가 최종 반환된 사례: 0
- 근거 없는 수치가 최종 반환된 사례: 0
- 요청당 추가 시도 1회 초과: 0

다만 14건은 유효한 최종 출력 자체가 없으므로 모델의 안전성이 입증된 것이
아니라 backend가 실패 결과를 차단한 것으로 해석해야 한다.

## 6. 성능

| 지표 | 결과 |
| --- | ---: |
| 전체 latency p50 | 17.433초 |
| 전체 latency p95 | 18.307초 |
| 최대 latency | 18.307초 |
| 평균 TTFT | 0.086초 |
| 생성 토큰 | 14,434 |

TTFT는 짧지만 대부분의 요청이 출력 상한까지 생성되어 전체 latency와 토큰
사용량이 증가했다. 정상 종료율이 낮아 운영 성능 비교 후보로 보기 어렵다.

## 7. 판단과 후속 작업

AWQ 모델은 책임 fixture만으로는 유망해 보였으나 전체 범주에서는 종료
안정성이 부족했다. 상한을 1000보다 더 높이는 것은 Suggestions 문구의 기대
길이에 비해 비용과 latency만 늘릴 가능성이 높아 권장하지 않는다.

재검토하려면 다음을 별도 실험으로 다룬다.

1. EXAONE 전용 chat template이 vLLM JSON Schema 출력을 올바르게 종료하는지 확인
2. schema 필드별 최대 길이와 간결한 출력 지시 추가
3. 부분 completion을 로컬에서만 캡처해 반복 또는 공백 생성 패턴 분석
4. 수정 후 dry-run을 책임 외에 지급·해지 fixture까지 포함

현재 운영 후보는 기존 전체 평가를 통과한
`RedHatAI/Qwen3.5-9B-FP8-dynamic`을 유지한다.

## 8. 한계

- 8개 fixture, 16회 결과이므로 실제 실패율을 통계적으로 증명하지 않는다.
- 합성 grounding을 사용했으며 법률 내용의 전문적 타당성을 평가하지 않았다.
- 법률 전문가 및 Subagent 품질 평가는 수행하지 않았다.
- model revision, tokenizer hash, image digest가 고정되지 않았다.
- 콜드 스타트와 장시간 soak test는 측정하지 않았다.
