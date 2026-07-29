# LLM 검증 결과 - RedHatAI Qwen3.5 9B FP8 dynamic

- 상태: 경량 운영 적합성 검증 통과
- 실행일: 2026-07-28
- 공통 규격: [LLM 검증](LLM%20검증.md)
- 모델: `RedHatAI/Qwen3.5-9B-FP8-dynamic`
- provider: `vllm`
- 로컬 실행 ID: `20260728T065141Z`
- 이전 512-token 실행 ID: `20260728T040708Z`

## 1. 결론

1000-token 상한에서도 부트캠프 프로젝트 범위의 자동 hard gate와 대표
Suggestions 생성 평가를 16/16으로 통과했다. 모든 18회 실제 모델 호출이
`finish_reason=stop`으로 끝났고 최대 completion token은 255였다. 이 결과는
법률 전문가 검토나 통계적으로 충분한 모델 품질 증명을 뜻하지 않지만 현재
WorkShield의 제한된 생성 역할과 데모 운영 후보로 사용할 수 있다는 판단이다.

| 항목 | 결과 |
| --- | ---: |
| MCP 참조 fixture | 8개 |
| 반복 | 각 2회 |
| 총 평가 | 16회 |
| 통과 | 16/16 |
| hard gate 실패 | 0 |
| repair | 2 |
| 최종 판정 | PASS |

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

모델 revision과 tokenizer hash는 endpoint와 runpodctl metadata만으로 확인할
수 없어 `unresolved`로 기록했다. image도 digest가 아니라 `latest` tag이므로
완전한 재현성은 확보되지 않았다. 다음 배포부터 model revision과 image
digest를 고정하는 것을 권장한다.

## 3. Fixture

MCP 품질평가를 다시 실행하지 않고
`mcp/quality/fixtures/v5/v5_sw_freelance.json`의 case를 참조했다.

| 범주 | MCP case |
| --- | --- |
| 책임·손해배상 | `v5-sw-18` |
| 대금·지급 | `v5-sw-09` |
| 계약 해지 | `v5-sw-12` |
| 지식재산권 | `v5-sw-06` |
| 비밀유지 | `v5-sw-15` |
| 업무 범위 | `v5-sw-03` |
| 수치 grounding | `v5-sw-27` |
| 프롬프트 인젝션 | `v5-sw-21` |

API overlay에는 purpose, provided input, 필수 문구와 source key만 두었다.
사용자 조항과 표준조항은 MCP fixture와 표준조항 DB에서 읽었다.

## 4. 안전성 결과

- JSON Schema와 Pydantic 최종 성공: 16/16
- 허용되지 않은 source key: 0
- 근거 없는 수치 생성: 0
- 합법·위법·불법 단정: 0
- 실제 내부 ID 노출: 0
- 최종 중국어·러시아어 문자: 0
- 프롬프트 인젝션 지시 이행: 0
- 요청당 추가 시도 1회 초과: 0

수치 fixture는 표준조항의 10일 대신 `provided_inputs`의 30일을 사용했고
새로운 수치를 만들지 않았다. 프롬프트 인젝션 fixture는 `source_id`와
러시아어 출력을 요구하는 purpose 안의 지시를 따르지 않았다.

## 5. Repair 관측

손해배상 fixture의 최초 응답 2건에서 `major_changes`에 중국어 `免责`가
포함됐다. backend가 이를 언어 이상으로 감지하고 고정 repair prompt를 한
번 적용했다. 두 최종 응답은 중국어 없이 정상 생성됐으며 전체 호출 상한
2회를 지켰다.

이 모델은 해당 문맥에서 중국어 혼입 경향이 있으므로 언어 hard gate와
repair를 제거하면 안 된다.

## 6. 성능

| 지표 | 결과 |
| --- | ---: |
| 전체 latency p50 | 7.102초 |
| 전체 latency p95 | 16.416초 |
| 최대 latency | 16.416초 |
| 평균 TTFT | 0.367초 |
| 생성 토큰 | 3,072 |
| completion token p50 | 165 |
| completion token p95 | 255 |
| completion token max | 255 |
| `finish_reason=stop` | 18/18 |

repair가 발생한 두 손해배상 요청이 가장 느렸다. 콜드 스타트는 이미 실행
중인 Pod를 사용했기 때문에 이번 결과에 포함하지 않았다.

### 6.1 이전 512-token 평가와 비교

| 항목 | 512 tokens | 1000 tokens |
| --- | ---: | ---: |
| 통과 | 16/16 | 16/16 |
| repair | 2 | 2 |
| latency p50 | 6.890초 | 7.102초 |
| latency p95 | 11.849초 | 16.416초 |
| 생성 토큰 | 3,128 | 3,072 |
| completion token 최대 | 미수집 | 255 |

두 평가 모두 동일하게 통과했으며 1000-token 실행에서도 모델은 상한까지
생성하지 않았다. latency 차이는 repair 응답과 Pod 실행 환경 변동을 포함하므로
token 상한만의 영향으로 단정하지 않는다. 관측된 최대값이 255이므로 현재
Suggestions 범위에서는 운영 상한 512로도 충분하다.

## 7. 비전문가 출력 점검

자동 gate 통과 후 16개 최종 문구를 개발 관점에서 확인했다.

- 책임·해지·비밀유지·업무범위 문구는 표준조항 내용을 반영했다.
- 지급 문구는 사용자 조항만으로 충분해 `SRC_USER`만 선택했다.
- 지식재산권 문구는 사용자 조항과 표준조항을 함께 사용했다.
- 두 반복의 최종 문구는 대부분 동일했고 `major_changes`의 상세도만 일부 달랐다.
- 최종 문구에서 혼합 언어와 내부 ID는 확인되지 않았다.
- Gemma에서 관측된 독립 문자 `n` 줄바꿈 오염은 확인되지 않았다.

법률 전문가 평가는 수행하지 않았으며 Subagent에 의한 별도 품질 채점도
필요하지 않다고 판단해 생략했다.

## 8. 한계와 후속 작업

- 8개 fixture, 16회 결과이므로 실제 실패율 0%를 증명하지 않는다.
- 합성 grounding을 사용했으며 법령 내용의 전문적 타당성을 평가하지 않았다.
- model revision, tokenizer hash, image digest가 고정되지 않았다.
- RunPod Pod의 콜드 로드 시간과 장시간 soak test는 측정하지 않았다.

운영 중에는 다음을 유지한다.

1. thinking OFF
2. JSON Schema structured output
3. 언어·수치·법률 단정·ID hard gate
4. 구조·언어 오류에만 repair 최대 1회
5. LLM timeout과 repair 비율 관측
6. 운영 `max_completion_tokens`는 512를 유지하고 출력 분포 변화 시 재검토

다른 모델이나 artifact 비교는 이 후보가 실제 데모에서 응답시간 또는 문구
품질 기준을 충족하지 못할 때만 수행한다.
