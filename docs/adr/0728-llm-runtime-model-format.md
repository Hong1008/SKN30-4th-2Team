# 0728 한국어 LLM 런타임과 모델 포맷 선택

* 상태: Accepted
* 결정일: 2026-07-28

## 1. 배경

Suggestions 후보 모델을 자체 인프라에서 검증하기 위해 Ollama,
vLLM, llama.cpp 기반 실행 방식을 비교했다.

초기 후보로 Qwen3.5 9B의 GGUF 양자화 모델을 공식
`vllm/vllm-openai:latest` 이미지에서 실행하려 했다. 그러나 검증
과정에서 다음과 같은 단계별 호환성 문제가 확인됐다.

1. GGUF 저장소에는 vLLM이 모델 구조를 확인할 수 있는 Hugging Face
   `config.json`이 없어 별도의 `--hf-config-path`가 필요했다.
2. 최신 vLLM 코어는 `gguf` 양자화 방식을 직접 포함하지 않아
   `vllm-gguf-plugin` 설치가 필요했다.
3. 플러그인 설치 후 GGUF 로더는 등록됐지만 Qwen3.5의
   `qwen3_5` 모델 유형에 대한 가중치 이름 매핑이 없어 모델 로딩이
   중단됐다.

실제 오류는 다음과 같았다.

```text
RuntimeError: Unknown gguf model_type: qwen3_5
```

이는 vLLM이 Qwen3.5 아키텍처 자체를 지원하는지와, 외부 GGUF
플러그인이 해당 모델의 GGUF 가중치 구조를 지원하는지가 별개의
호환성 문제임을 보여준다.

한국어 후보 모델로는 다음 모델을 추가로 검토했다.

* `LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct`
* `LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct-AWQ`
* `kakaocorp/kanana-1.5-8b-instruct-2505`
* `RedHatAI/Qwen3.5-9B-FP8-dynamic`

EXAONE 3.5 원본 모델은 현재 사용한 vLLM·Transformers 조합에서
저장소의 커스텀 Python 구현을 불러오기 위해
`--trust-remote-code`가 필요했다.

이 옵션을 추가한 뒤에는 모델 다운로드 단계까지 진행됐으나, 모델
조각을 재구성하는 과정에서 컨테이너 저장공간이 부족해 다음 오류가
발생했다.

```text
File reconstruction error:
IO Error: No space left on device (os error 28)
```

따라서 런타임 선택뿐 아니라 모델 파일 형식, 원격 코드 실행 정책,
Hugging Face 캐시 저장공간도 함께 운영 기준으로 결정할 필요가 있다.

## 2. 결정

GPU 기반 OpenAI-compatible API 운영의 기본 런타임은 vLLM으로 한다.

단, vLLM에서는 GGUF보다 Hugging Face Safetensors 기반 모델과
vLLM이 네이티브로 지원하는 양자화 형식을 우선한다.

GGUF 모델은 llama.cpp 또는 Ollama의 실행 영역으로 분리한다.

### 2.1 런타임 역할

각 런타임의 사용 경계를 다음과 같이 정한다.

| 런타임         | 주요 사용 목적                                   |
| ----------- | ------------------------------------------ |
| vLLM        | GPU 서버에서 다중 요청을 처리하는 OpenAI-compatible API |
| llama.cpp   | GGUF 모델 직접 실행, CPU·GPU 혼합 실행, 세부 메모리 제어    |
| Ollama      | 개인·개발 환경에서 GGUF 모델을 간단히 설치하고 실행            |
| 외부 provider | 대형 모델 품질 비교와 자체 인프라의 기준선 검증                |

Suggestions의 자체 호스팅 운영 후보는 vLLM을 기준으로 평가한다.

개발자의 로컬 실험이나 단일 사용자 검증에서 GGUF가 필요한 경우에는
Ollama 또는 llama.cpp를 사용한다.

### 2.2 vLLM 모델 포맷

vLLM 운영 모델은 다음 형식을 우선한다.

* Safetensors BF16
* FP8
* AWQ
* GPTQ
* compressed-tensors
* 그 밖에 vLLM이 네이티브로 지원하는 양자화 형식

Qwen3.5 9B급 후보 중에서는 다음과 같은 vLLM용 체크포인트를
우선 검증한다.

```text
RedHatAI/Qwen3.5-9B-FP8-dynamic
```

한국어 특화 후보로는 다음 모델을 우선 검증한다.

```text
LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct
LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct-AWQ
kakaocorp/kanana-1.5-8b-instruct-2505
```

메모리와 디스크 제약이 있는 환경에서는 BF16 원본보다 공식 AWQ,
FP8 또는 검증된 compressed-tensors 체크포인트를 우선한다.

### 2.3 GGUF 사용 경계

현재 vLLM 운영 경로에서는 GGUF를 사용하지 않는다.

vLLM의 GGUF 지원 여부는 다음 세 조건에 동시에 의존한다.

1. vLLM이 모델 아키텍처를 지원함
2. GGUF 플러그인이 현재 vLLM 버전과 호환됨
3. GGUF 플러그인이 해당 모델 유형의 가중치 이름 매핑을 지원함

Qwen3.5는 첫 번째 조건은 충족했지만 세 번째 조건을 충족하지 못했다.

따라서 Qwen3.5 GGUF를 사용해야 하는 경우 다음 런타임을 사용한다.

```text
직접 제어와 서버 실행: llama.cpp
간단한 로컬 모델 관리: Ollama
```

vLLM에서 GGUF 플러그인에 별도 패치를 적용해 운영하는 방식은 현재
채택하지 않는다.

### 2.4 EXAONE 원격 코드 실행

현재 검증 환경에서 EXAONE 3.5는 다음 옵션을 사용한다.

```text
--trust-remote-code
```

예시는 다음과 같다.

```bash
vllm serve LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct \
  --trust-remote-code \
  --host 0.0.0.0 \
  --dtype bfloat16 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.9
```

`--trust-remote-code`는 Hugging Face 저장소의 Python 코드를
컨테이너에서 실행하도록 허용한다.

따라서 운영 환경에서는 다음 조건을 적용한다.

* 공식 조직 저장소만 허용한다.
* 모델 저장소와 실행 코드를 검토한다.
* 움직이는 기본 브랜치 대신 검증한 revision을 고정한다.
* 모델 revision과 code revision을 가능한 경우 함께 고정한다.
* 허용된 모델 저장소를 배포 설정의 allowlist로 관리한다.

커뮤니티가 재배포하거나 임의로 변환한 EXAONE 체크포인트에는
`--trust-remote-code`를 기본 허용하지 않는다.

### 2.5 모델 캐시와 영구 저장공간

Hugging Face 모델 캐시는 컨테이너의 임시 루트 파일시스템에 저장하지
않는다.

다음 경로 중 하나에 영구 볼륨을 마운트한다.

```text
/root/.cache/huggingface
```

또는:

```text
/models/huggingface
```

별도 경로를 사용하는 경우 환경 변수와 vLLM 옵션을 명시한다.

```text
HF_HOME=/models/huggingface
```

```text
--download-dir /models/huggingface/hub
```

EXAONE 3.5 7.8B BF16과 같은 8B급 BF16 모델은 가중치 외에도 다운로드
조각, Xet 재구성 캐시, 임시 파일을 사용한다.

운영 기준은 다음과 같다.

* 단일 8B급 BF16 모델당 최소 40GB의 여유 공간을 확보한다.
* 여러 모델을 교체 검증하는 Pod는 80GB 이상의 모델 캐시 볼륨을
  권장한다.
* 디스크 용량뿐 아니라 inode 사용량도 모니터링한다.
* 실패한 `.incomplete` 파일과 사용하지 않는 모델 캐시를 정기적으로
  정리한다.
* Pod 재시작 시 동일 모델을 다시 다운로드하지 않도록 영구 볼륨을
  사용한다.

디스크를 확장할 수 없는 환경에서는 BF16 대신 AWQ 또는 FP8 모델을
사용한다.

### 2.6 1차 후보 모델

Suggestions 후보 모델의 1차 검증 순서는 다음과 같이 정한다.

| 우선순위 | 모델                                         | 목적               |
| ---- | ------------------------------------------ | ---------------- |
| 1    | `LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct-AWQ` | 한국어 품질과 자원 효율 검증 |
| 2    | `RedHatAI/Qwen3.5-9B-FP8-dynamic`          | 범용 추론·구조화 출력 기준선 |
| 3    | `LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct`     | BF16 원본 품질 비교    |
| 4    | `kakaocorp/kanana-1.5-8b-instruct-2505`    | 한국어·영어 범용 대화 비교  |

이 우선순위는 모델 품질 승인이 아니라 실행 가능성과 비용을 고려한
검증 순서다.

모델 최종 채택은 Suggestions 스키마 준수율, 한국어 제안 품질,
지연시간, 처리량, GPU 메모리, 장문 입력 안정성을 별도로 측정한 뒤
결정한다.

## 3. 검증

이번 세션에서는 공식 `vllm/vllm-openai:latest` 이미지와
커스텀 GGUF 플러그인 이미지를 사용해 다음 동작을 확인했다.

### 3.1 Qwen3.5 GGUF

초기 실행에서는 GGUF 저장소를 Hugging Face 모델 구성으로 해석하지
못했다.

```text
Invalid repository ID or local directory specified:
'unsloth/Qwen3.5-9B-GGUF'
```

원본 모델 설정을 지정한 뒤에는 아키텍처를 인식했다.

```text
Resolved architecture: Qwen3_5ForConditionalGeneration
```

그러나 공식 vLLM 이미지에는 GGUF 양자화 방식이 등록되지 않았다.

```text
Unknown quantization method: gguf
```

`vllm-gguf-plugin` 설치 후에는 GGUF 로더와 설정 파서가 등록됐다.

```text
Registered model loader GGUFModelLoader
Registered config parser GGUFConfigParser
```

최종적으로 Qwen3.5 가중치 이름 매핑이 없어 중단됐다.

```text
RuntimeError: Unknown gguf model_type: qwen3_5
```

이를 통해 Qwen3.5 GGUF는 현재 사용한 vLLM과 플러그인 조합에서
실행할 수 없음을 확인했다.

### 3.2 EXAONE 3.5

원본 EXAONE 모델을 기본 설정으로 실행하면 저장소의 커스텀 코드를
허용하라는 오류가 발생했다.

```text
Please pass the argument trust_remote_code=True
to allow custom code to be run.
```

CLI에 다음 플래그를 추가한 뒤 모델 다운로드와 엔진 초기화가 다음
단계로 진행됐다.

```text
--trust-remote-code
```

따라서 현재 검증 환경에서는 EXAONE 3.5 실행에 해당 옵션이 필요함을
확인했다.

### 3.3 저장공간

EXAONE 모델 다운로드 중 파일 재구성 단계에서 다음 오류가 발생했다.

```text
File reconstruction error:
IO Error: No space left on device (os error 28)
```

이는 GPU 메모리 부족이 아니라 Hugging Face 캐시가 저장되는 컨테이너
파일시스템의 디스크 또는 inode 부족이다.

이번 검증은 런타임·포맷·배포 조건 확인이며, 각 후보 모델의
Suggestions 품질 승인을 뜻하지 않는다.

## 4. 결과

### 긍정적 결과

* vLLM과 GGUF 런타임의 책임 범위를 명확히 분리했다.
* 모델 아키텍처 지원과 파일 포맷 지원을 혼동하지 않게 됐다.
* GGUF 플러그인 호환성에 의존하는 운영 위험을 제거했다.
* 한국어 모델을 vLLM 네이티브 형식으로 비교할 수 있게 됐다.
* EXAONE의 원격 코드 실행 조건을 배포 계약에 반영할 수 있다.
* 모델 캐시를 영구 볼륨에 배치해 재다운로드와 임시 디스크 장애를
  방지할 수 있다.
* BF16, FP8, AWQ 모델을 동일한 OpenAI-compatible API에서 비교할 수
  있다.
* Qwen3.5 9B와 EXAONE·Kanana 8B급 모델을 유사한 운영 조건에서
  평가할 수 있다.

### 비용과 한계

* 런타임별로 별도의 컨테이너 이미지와 배포 설정을 관리해야 한다.
* vLLM용 모델과 로컬 GGUF 모델의 결과가 양자화 방식 때문에 직접
  동일하지 않을 수 있다.
* `--trust-remote-code`를 사용하는 모델은 코드 검토와 revision
  고정이 필요하다.
* 모델 캐시를 위한 영구 볼륨 비용이 추가된다.
* FP8은 GPU 세대와 커널 지원에 따라 성능 이점이 달라진다.
* AWQ는 메모리를 줄이지만 BF16 원본 대비 품질 저하 가능성을 별도로
  측정해야 한다.
* 8B급 모델이 Suggestions 구조화 출력과 한국어 법률 문구 품질 기준을
  충족한다는 보장은 아직 없다.
* 하나의 후보가 실행에 성공해도 동시 요청 처리량과 장문 컨텍스트
  안정성은 별도 부하 테스트가 필요하다.

## 5. 검토한 대안

### 5.1 vLLM에서 GGUF를 계속 사용

채택하지 않았다.

Qwen3.5 아키텍처는 vLLM이 인식했지만 GGUF 플러그인이
`qwen3_5` 모델 유형의 가중치 매핑을 지원하지 않았다.

외부 플러그인의 모델별 지원 상황에 따라 운영 가능 여부가 달라지고,
vLLM 버전 변경 시 플러그인 호환성을 별도로 검증해야 한다.

### 5.2 모든 모델을 Ollama로 운영

채택하지 않았다.

Ollama는 로컬 개발과 소규모 실행에는 편리하지만, 다중 요청의
처리량과 GPU 서버 운영에서는 vLLM의 배칭·KV 캐시·분산 실행 기능을
활용하기 어렵다.

Ollama는 개발자 로컬 검증과 GGUF 편의 실행 용도로 유지한다.

### 5.3 모든 모델을 llama.cpp로 운영

채택하지 않았다.

llama.cpp는 GGUF와 CPU·GPU 혼합 실행에 적합하지만, Suggestions
서비스의 기본 OpenAI-compatible GPU API 운영과 다중 요청 처리에는
vLLM을 우선한다.

llama.cpp는 GGUF 모델을 반드시 사용해야 하는 검증 환경에 한정한다.

### 5.4 EXAONE의 `trust_remote_code` 사용 금지

채택하지 않았다.

현재 EXAONE 3.5 원본 모델은 검증 환경에서 저장소의 커스텀 구현을
필요로 한다. 공식 저장소와 고정 revision에 한해 원격 코드 실행을
허용하는 것이 한국어 후보 모델 검증에 더 적절하다.

단, 임의의 커뮤니티 저장소에는 허용하지 않는다.

### 5.5 컨테이너 임시 디스크에 모델 캐시 저장

채택하지 않았다.

모델 다운로드와 파일 재구성 중 임시 공간이 추가로 필요하며, Pod
재시작 시 모델을 다시 받아야 한다. 실제 검증에서도
`No space left on device`로 엔진 초기화가 중단됐다.

### 5.6 BF16 모델만 평가

채택하지 않았다.

BF16은 원본 품질 기준선으로 필요하지만, 8B급에서도 가중치와 KV 캐시,
임시 다운로드 공간을 고려하면 비용이 커진다.

운영 후보는 AWQ와 FP8을 함께 평가하고 BF16은 품질 기준선으로
사용한다.

## 6. 재검토 조건

다음 상황에서 이 결정을 다시 검토한다.

* vLLM 또는 공식 GGUF 플러그인이 Qwen3.5 `qwen3_5` 모델 유형을
  안정적으로 지원함
* GGUF가 vLLM 코어에 다시 통합되고 운영 수준의 회귀 테스트가 제공됨
* Ollama 또는 llama.cpp가 필요한 동시 요청 처리량을 충족함
* vLLM 네이티브 한국어 모델이 Suggestions 품질 기준을 충족하지 못함
* EXAONE이 `trust_remote_code` 없이 vLLM 네이티브 구현으로 안정적으로
  로딩됨
* 원격 코드 실행을 허용할 수 없는 보안 요구사항이 도입됨
* 모델 캐시 비용이 운영 예산 기준을 초과함
* 항목별 모델을 별도 런타임에 배치하는 것이 더 효율적이라고 확인됨
* 16GB 이하 GPU를 기본 운영 환경으로 사용하게 됨
* 모델 크기보다 네트워크 지연이나 provider 안정성이 더 중요한
  요구사항으로 변경됨

## 7. 결정 범위

이 ADR은 Suggestions 후보 모델을 실행하기 위한 런타임, 모델 파일
형식, 양자화, 원격 코드 실행과 모델 캐시 저장공간 정책을 결정한다.

다음 항목은 별도 결정 대상이다.

* Suggestions 최종 운영 모델
* 모델별 한국어 문구 품질 승인
* 구조화 출력 성공률 기준
* GPU 종류와 RunPod 인스턴스 크기
* Pod와 Serverless 사용 경계
* 최대 동시 요청 수와 autoscaling 정책
* provider 장애 시 fallback 순서
* 모델별 라이선스와 상업적 사용 조건
* 프롬프트와 sampling parameter
* 사용자에게 공개하는 모델명과 provider 정보

