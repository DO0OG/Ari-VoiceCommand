# Ari Local Decision Engine 기획서

> **문서 목적:** TypeSafe AI의 Jev에서 얻을 수 있는 핵심 아이디어를 분석하고, Ari-VoiceCommand에 **무료·로컬·초경량·저지연** 형태로 적용할 수 있는 전용 Decision Engine을 설계한다.
>
> **작성 기준일:** 2026-09-21  
> **검토 대상 Ari 저장소:** `DO0OG/Ari-VoiceCommand`  
> **검토 기준 커밋:** `f7cc6d35d284bea5e6f42bca5076cb7280974b2a`

---

## 1. 결론 요약

Ari에 Jev 자체를 사용하는 것은 기술적으로 적합하지만, Jev는 현재 TypeSafe AI가 호스팅하는 **유료 API 기반 상용 모델**이며 로컬 가중치가 공개된 오픈소스 모델이 아니다. Ari가 지향하는 무료 배포, 오프라인 사용 가능성, 사용자별 API 비용 최소화라는 조건과는 맞지 않는다.

따라서 본 기획의 목표는 **Jev를 복제하는 것 자체가 아니라, Jev의 가장 유용한 동작 원리만 Ari에 맞게 재구현하는 것**이다.

핵심 목표는 다음과 같다.

- 입력 문장을 생성형 LLM으로 보내기 전에 **로컬에서 매우 빠르게 의도와 실행 경로를 판별**한다.
- 결과는 문자열 생성이 아니라 `choice + probabilities + confidence` 형태의 **구조화된 결정**으로 반환한다.
- 사용자의 GPU를 상시 점유하지 않는다.
- CPU에서도 체감하기 어려운 수준의 짧은 시간만 사용한다.
- 추가 모델 파일은 가능한 한 수 MB~수십 MB 수준으로 제한한다.
- 확신이 높은 단순 명령만 직접 실행하고, 애매하거나 복잡한 요청은 기존 Ari LLM/Agent로 넘긴다.
- 위험하거나 되돌리기 어려운 작업은 Decision Engine의 확률과 관계없이 **기존 SafetyChecker/확인 절차를 절대 우회하지 않는다.**

본 문서에서는 이 구성요소를 임시로 **Ari Local Decision Engine**, 내부 모델을 **Ari MicroJev / AriS1**이라고 부른다. 실제 제품명은 구현 단계에서 변경 가능하다.

---

# 2. Jev란 무엇인가

## 2.1 개요

TypeSafe AI는 2026년 9월 15일 첫 번째 **System One Model**인 **Jev**를 공개했다.

일반적인 LLM이 다음 토큰을 반복 생성해 최종 문자열을 만드는 구조라면, Jev는 소프트웨어 내부에서 필요한 **판단 자체**를 빠르게 수행하는 데 초점을 둔다.

일반 LLM의 대표 흐름:

```text
입력
 ↓
LLM
 ↓
토큰 생성 → 토큰 생성 → 토큰 생성 → ...
 ↓
JSON / 문장
 ↓
파싱
 ↓
실행
```

Jev가 지향하는 흐름:

```text
상태 + 질문 + 가능한 선택지
 ↓
System One Model
 ↓
선택지별 확률 / 점수
 ↓
프로그램이 즉시 분기
```

즉, 사람에게 읽힐 문장을 만드는 것이 목적이 아니라 **코드가 사용할 결정을 반환하는 모델**이다.

TypeSafe의 공식 설명은 이를 "unstructured state in, typed probabilistic decisions out"에 가까운 개념으로 설명한다.

## 2.2 Jev의 세 가지 주요 Primitive

### Choice

여러 후보 중 하나를 선택한다.

예시:

```text
입력: "디스코드 좀 켜줘"

launch_app       0.96
web_search       0.01
conversation     0.02
run_agent_task   0.01
```

Ari에서 가장 중요하게 사용할 기능이다.

### Noul

어떤 조건이 참인지에 대한 확률을 반환하는 binary decision 형태다.

예시:

```text
질문: 이 요청은 위험한 시스템 변경인가?

P(true) = 0.91
```

Ari에서는 향후 보조적인 risk/confirmation 판단에 활용할 수 있으나, **보안 결정의 최종 권한으로 사용해서는 안 된다.**

### Score

정해진 순서의 단계에 대한 확률 분포와 가중 점수를 반환한다.

예시:

```text
Low       0.05
Medium    0.16
High      0.61
Critical  0.18
```

Ari에서는 작업 복잡도, 긴급도, 개입 수준 같은 보조 신호로 확장 가능하다.

## 2.3 Jev의 장점

TypeSafe가 공개한 핵심 특징은 다음과 같다.

- 문자열을 생성하지 않는다.
- 정해진 타입 안에서만 답하므로 schema parsing 실패를 줄일 수 있다.
- 여러 질문을 한 번에 병렬적으로 판단하는 구조를 목표로 한다.
- 모든 Choice/Score 판단에서 확률/신뢰도 정보를 활용할 수 있다.
- System One 형태의 문제에서 매우 낮은 지연 시간을 목표로 한다.

TypeSafe가 공개한 서비스 수치는 end-to-end 약 **70~500ms** 범위이며, 이는 호스팅 API의 네트워크 시간까지 포함한 벤더 측 수치다.

## 2.4 Ari에서 Jev가 매력적이었던 이유

현재 Ari에는 이미 다음과 같은 도구와 명령이 존재한다.

```text
play_youtube
set_timer
cancel_timer
get_weather
adjust_volume
get_current_time
shutdown_computer
get_screen_status
execute_python_code
execute_shell_command
run_agent_task
delegate_to_subagent
web_search
web_fetch
mcp_call
api_call
read_file
write_file
edit_file
list_directory
search_in_files
move_file
delete_file
analyze_screenshot
analyze_image_file
launch_app
close_app
get_running_apps
focus_window
take_screenshot
get_clipboard
set_clipboard
get_calendar_events
create_calendar_event
send_email
read_emails
generate_image
schedule_task
list_scheduled_tasks
cancel_scheduled_task
```

> 위 목록은 `VoiceCommand/agent/tool_schemas.py`의 `CORE_TOOL_SCHEMAS`에 실제 등록된 39개 tool 이름과 일치한다.

즉 Ari는 이미 **"사용자 문장 → 정해진 tool 중 무엇을 사용할지 선택"**이라는 Jev에 매우 잘 맞는 문제를 가지고 있다.

현재 이런 판단을 LLM function calling으로 처리하면 짧은 명령에도 모델 호출, tool schema 처리, JSON 생성/파싱 등의 비용이 발생할 수 있다.

Jev 계열 decision layer가 앞단에 있으면 다음처럼 단순화할 수 있다.

```text
STT
 ↓
Decision Engine
 ├─ 확실한 단순 명령 → 즉시 실행
 └─ 애매/복합 요청 → 기존 LLM / Agent
```

---

# 3. Jev 자체를 사용하지 않는 이유

## 3.1 유료 API

Jev는 현재 TypeSafe AI의 호스팅 API로 제공된다.

공개 가격은 입력 **$0.042 / 1M tokens** 수준이며 출력은 별도 과금하지 않는다고 안내되어 있다.

단가 자체는 매우 낮지만 Ari의 제품 방향에서는 문제가 다르다.

- 사용자마다 TypeSafe API 키를 준비해야 한다.
- 인터넷 연결이 필수다.
- 무료/오프라인 배포라는 Ari의 장점이 약해진다.
- 외부 서비스 정책, 장애, 가격 변경에 영향을 받는다.
- 짧은 PC 명령을 판별하는 기능을 위해 외부 API에 의존하게 된다.

따라서 **Jev API를 기본 기능으로 넣는 것은 채택하지 않는다.**

## 3.2 Jev 모델 자체는 오픈 웨이트가 아님

현재 Jev의 모델 가중치나 학습 코드는 공개되어 있지 않다.

공식 SDK가 오픈소스로 공개되어 있더라도, SDK는 API client일 뿐 Jev 모델을 로컬에서 실행하게 해주는 것은 아니다.

---

# 4. 조사한 오픈소스 / 로컬 대안

Jev 공개 직후 유사한 구조를 구현하려는 오픈소스 프로젝트들이 빠르게 등장했다. 아직 상당수가 2026년 9월 중순 이후 막 만들어진 연구 프로젝트이므로, README 수치와 자체 벤치마크는 **독립 검증된 사실로 간주하지 않고 참고 자료로만 사용**해야 한다.

## 4.1 `vinnylarouge/jevlike`

- 라이선스: MIT
- Python >= 3.10
- 목적: `context + N개의 가변 text option → 각 option probability`
- 한 번의 forward pass로 후보를 평가
- 기본 구현은 매우 작은 byte embedding + option attention head
- pretrained transformer를 선택적으로 frozen encoder로 사용할 수 있음

기본 TinyScorer 구성은 다음과 같다.

```text
byte embedding
+ positional embedding
+ option representation
+ option → context attention
+ score
```

기본 설정은 대략:

```text
width = 64
rank = 64
context = 192 byte tokens
option = 32 byte tokens
```

이 구조는 파라미터 수 자체가 매우 작다. 단순 계산으로 기본 tiny scorer는 수만 개 수준의 학습 파라미터로 구성할 수 있다.

### 장점

- 극도로 작게 만들 수 있다.
- CPU 추론이 매우 빠르다.
- 동적인 후보 목록을 사용할 수 있다.
- Jev와 유사한 "후보를 한 번에 점수화"하는 형태를 구현하기 좋다.

### 단점

- 저자도 raw byte encoder가 의미 이해에 약하다고 명시한다.
- 한국어/일본어처럼 UTF-8 multi-byte 문자가 많은 언어에서는 특히 학습 데이터 의존성이 높아질 수 있다.
- Jev의 실제 구조를 복제한 것이 아니라 연구용 starter다.

### Ari에서의 의미

**"Jev 같은 인터페이스는 거대한 모델 없이도 가능하다"**는 가장 중요한 근거다.

---

## 4.2 `olanotolu/jevbetter`

현재 Ari 목표에 가장 직접적으로 참고할 가치가 높은 프로젝트 중 하나다.

- 라이선스: MIT
- Python >= 3.10
- one-pass option scorer
- raw byte 대신 **hashed character n-gram** 사용
- 작은 2-layer Transformer context encoder
- option끼리 서로 비교하는 rival-aware attention
- gated MLP scorer
- validation 기반 temperature scaling

구조:

```text
텍스트
 ↓
Unicode character 3~6 gram
 ↓
stable hash bucket
 ↓
small embedding
 ↓
2-layer tiny transformer
 ↓
option mixer / cross attention
 ↓
gated scorer
 ↓
softmax + calibrated temperature
```

### 왜 Ari에 더 적합한가

`char_ngrams()`는 Python Unicode 문자열 단위로 3~6글자 n-gram을 만든 뒤 UTF-8로 hash한다.

따라서 영어만을 전제로 하는 BERT vocabulary와 달리 구조적으로는 다음을 모두 입력으로 받을 수 있다.

```text
크롬 열어줘
open chrome
Chromeを開いて
```

물론 **한국어/일본어 성능이 이미 검증되었다는 뜻은 아니다.** 실제 Ari 데이터로 평가해야 한다. 그러나 byte-level starter보다 multilingual Ari용으로 발전시키기 훨씬 좋은 출발점이다.

### 공개 자체 벤치마크

저자 README의 synthetic hard-menu benchmark에서는:

```text
jevlike    top-1 0.873 / ECE 0.0367 / 4608 menus/sec
jevbetter  top-1 0.916 / ECE 0.0182 /   40 menus/sec
```

이라고 보고한다.

주의:

- 자체 synthetic benchmark이다.
- 800개의 held-out 메뉴라는 작은 평가다.
- Ari 음성명령 품질을 의미하지 않는다.
- 40 menus/sec는 평균 약 25ms/menu에 해당하지만 시스템·CPU에 따라 달라진다.

### Ari에서의 의미

**Ari MicroJev의 연구 기반으로 가장 유용한 프로젝트.**

단, 코드를 그대로 복사하기보다 아이디어를 참고하여 Ari 요구사항에 맞춘 더 작은 구성을 따로 벤치하는 것이 바람직하다.

---

## 4.3 CUA-S1 / CUA-S1-FORMS

Cua 진영에서 매우 작은 specialist System One 모델을 연구하고 있다.

외부 소개 자료에는 약 **706k parameters**와 50ms 수준의 폼 처리 사례가 소개되었으나, 현재 `trycua/cua` 저장소의 공식 Model Card는 소스 구성요소에 대해 **가중치 및 성능 claim을 현재 배포하지 않는 research profile**이라고 명시하고 있다.

따라서 현재 시점에서는 해당 수치를 Ari 설계 근거로 직접 사용하면 안 된다.

그러나 중요한 개념적 시사점은 있다.

> 좁은 도메인에 특화하면 System One 형태의 모델을 sub-million 수준까지 작게 만드는 것이 연구 대상이 되고 있다.

Ari의 명령 routing 역시 일반 언어 이해 전체가 아니라 제한된 도메인이므로 이 접근과 방향이 맞다.

---

## 4.4 `wfzyx/von`

- 395M parameters
- 약 1.5GB 모델
- Apache-2.0
- Choice / Noul / Score 구현
- TypeSafe `/v1/systemone` 호환을 목표
- ModernBERT 기반

System One replica로서는 흥미롭지만 Ari의 "거의 리소스를 쓰지 않는 상시 resident router" 목적에는 너무 크다.

또한 현재 모델은 영어 중심이며 Python >=3.12 요구가 Ari Python 3.11 baseline과 맞지 않는다.

**결론: Ari 기본 라우터 후보에서는 제외. 벤치마크 비교용으로만 참고.**

---

## 4.5 `jaredpalmer/kev`

- Qwen2.5-0.5B + LoRA + small pointer head
- 생성 없이 prefill-only decision
- Choice / Noul / Score
- `/v1/systemone` 호환
- 연구 checkpoint 공개

흥미로운 구조지만 0.5B backbone 자체를 메모리에 유지해야 하므로 Ari의 초경량 목표에는 무겁다.

공개 checkpoint도 영어 중심이다.

**결론: 구조 연구용 참고. 기본 탑재 후보에서는 제외.**

---

## 4.6 NanoJev / LitJev / systemone-lite / Qwen 기반 재현

이 계열은 대체로 0.5B~수B 규모 Qwen/Gemma 모델을 이용하여 token generation 없이 logits/readout을 직접 사용하는 방식이다.

장점:

- Jev에 가까운 범용 의미 판단 능력
- pretrained multilingual knowledge 활용 가능

단점:

- 수백 MB~수 GB RAM/VRAM
- 모델 로딩 비용
- 상시 resident desktop assistant에는 부담

**결론: Ari의 "사용자 PC 리소스를 거의 사용하지 않는 기본 기능"과는 맞지 않음.**

---

## 4.7 GLiNER2.x multilingual 계열

GLiNER 계열은 상대적으로 성숙한 classification/extraction 기반이다. 다국어 모델도 존재해 Ari 언어 범위에 유리하다.

하지만 수백 M parameter 모델을 상시 올려둘 필요가 생기므로 MicroJev 목표에는 크다.

**결론: 정확도 비교용 upper baseline으로는 가치가 있으나 기본 채택은 보류.**

---

# 5. 최종 목표: Ari 전용 초경량 System One Layer

## 5.1 범용 Jev를 만들지 않는다

가장 중요한 설계 원칙이다.

Ari가 알아야 할 세계는 제한되어 있다.

예:

```text
앱 실행
앱 종료
창 포커스
볼륨
타이머
시간
날씨
유튜브
웹 검색
파일 읽기/쓰기
스크린샷
클립보드
캘린더
메일
에이전트 위임
일반 대화
복합 요청
```

따라서 수십억 개의 인터넷 지식을 기억할 필요가 없다.

Ari Decision Engine의 임무는:

> "이 문장의 의미를 완전히 이해해서 답변하라"가 아니라  
> **"이 요청은 Ari 내부의 어느 경로로 보내야 하는가?"**

이다.

이 차이를 이용해 모델을 극단적으로 줄인다.

---

# 6. 권장 아키텍처

```text
                         ┌─────────────────────────┐
                         │        User Voice       │
                         └────────────┬────────────┘
                                      ↓
                                    STT
                                      ↓
                         ┌─────────────────────────┐
                         │  1. Existing Fast Rules │
                         │ Command.matches / parser │
                         └────────────┬────────────┘
                              matched │ not matched
                                 ↓    │
                          direct cmd  ↓
                         ┌─────────────────────────┐
                         │ 2. Ari Decision Engine  │
                         │  local / CPU / tiny     │
                         │ choice + probability    │
                         └────────────┬────────────┘
                                      ↓
                             Confidence/Risk Gate
                         ┌────────────┴────────────┐
                         ↓                         ↓
                  high confidence            low confidence
                  simple request             complex / unclear
                         ↓                         ↓
                  deterministic             Existing Ari LLM
                  argument parser          chat_with_tools()
                         ↓                         ↓
                   SafetyChecker              Agent/Tools
                         ↓                         ↓
                     execution                 execution
```

---

# 7. 3단계 판단 계층

## Stage 1 — Deterministic Fast Rules

현재 Ari가 이미 잘 처리하는 정확한 명령은 ML까지 갈 필요가 없다.

예:

```text
"5분 타이머"
"볼륨 올려"
"지금 몇 시야"
```

이 단계의 비용은 사실상 0에 가깝다.

기존 `CommandRegistry`의 command `matches()` 구조를 유지한다.

## Stage 2 — Ari MicroJev

Stage 1에서 놓친 자연스러운 표현을 처리한다.

예:

```text
"소리 좀만 작게 해줄래?"
"디코 켜줄 수 있어?"
"잠깐 화면 하나 찍어줘"
"인터넷에서 이거 찾아봐"
```

결과 예:

```json
{
  "choice": "adjust_volume",
  "probabilities": {
    "adjust_volume": 0.963,
    "conversation": 0.017,
    "run_agent_task": 0.012,
    "web_search": 0.008
  },
  "confidence": 0.946,
  "latency_ms": 3.2
}
```

## Stage 3 — Existing LLM / Agent

다음 요청은 MicroJev에서 직접 처리하지 않는다.

```text
"크롬 열어서 어제 보던 자료 찾고 세 줄로 정리해줘"
"다운로드 폴더 정리해서 중복 파일 지워줘"
"이 오류 화면 보고 원인 알아봐"
"최근 뉴스 찾아서 내 프로젝트에 영향 있는지 분석해줘"
```

MicroJev는 이를 `run_agent_task`, `web_search + complex`, `conversation/unknown` 등으로 라우팅하고 기존 Ari의 지능을 그대로 사용한다.

---

# 8. Ari MicroJev 모델 설계

## 8.1 MVP: 가장 작은 baseline부터 시작

첫 구현부터 tiny transformer를 넣지 않는다.

먼저 아래 두 모델을 동일 데이터로 비교한다.

### Baseline A — Character n-gram + Linear Classifier

예:

```text
character 2~5 gram
→ hashing / TF-IDF
→ Logistic Regression 또는 linear softmax
→ probability calibration
```

장점:

- 수 MB 수준 가능
- GPU 불필요
- CPU inference가 거의 순간적
- scikit-learn 학습 후 pure NumPy/ONNX로 추론 가능
- 한국어/영어/일본어를 vocabulary 없이 처리 가능

단점:

- 완전히 새로운 표현의 의미 일반화에는 한계
- dynamic plugin tool description에는 약함

### Baseline B — AriS1 One-pass Option Scorer

`jevbetter`의 연구 방향을 참고한다.

권장 초기 구조:

```text
hashed Unicode char n-grams
 ↓
small embedding
 ↓
1~2 layer tiny encoder
 ↓
option representation
 ↓
option↔option / option↔context scoring
 ↓
softmax
 ↓
temperature calibration
```

초기에는 `jevbetter` 기본 128 width보다 더 작은 구성도 벤치한다.

예:

```text
width        48 / 64 / 96
layers       1 / 2
heads        2 / 4
hash buckets 8k / 16k / 32k
context      128~256 features
```

목표는 정확도가 충분한 **가장 작은 모델**을 선택하는 것이다.

---

# 9. 리소스 목표

최종 수치는 실제 Ari 데이터셋 벤치마크 후 확정한다.

## 필수 목표

### 기본 실행 환경

- CPU only
- GPU 사용 기본값: **OFF**
- CUDA 모델 로딩 금지
- background 지속 연산 없음

### 모델 크기

**Preferred:**

```text
<= 20 MB
```

**Hard target:**

```text
<= 50 MB
```

50MB를 넘어가면 기본 탑재 여부를 재검토한다.

### 메모리

모델 자체 메모리뿐 아니라 inference runtime overhead까지 측정한다.

권장 목표:

```text
추가 steady-state RSS <= 50 MB preferred
<= 100 MB acceptable
```

PyTorch 때문에 runtime overhead가 지나치게 커지면 최종 배포 모델은:

- ONNX Runtime
- pure NumPy
- 직접 구현한 compact scorer

중 하나로 전환한다.

### 지연 시간

Warm inference 목표:

```text
p50 <= 5 ms preferred
p95 <= 20 ms target
p99 <= 40 ms acceptable
```

단, 사용자 하드웨어 스펙별로 별도 측정한다.

### CPU 사용

상시 polling 금지.

명령이 들어온 순간에만 1회 inference하고 즉시 idle 상태로 돌아간다.

---

# 10. 왜 GPU를 쓰지 않는가

Ari는 게임·작업 중 항상 켜둘 수 있는 desktop assistant다.

이 상황에서 음성 명령 router를 위해:

```text
VRAM 500 MB~1GB+
```

를 상시 점유하는 것은 제품적으로 좋지 않다.

특히 게임 사용자는 VRAM 여유가 중요하다.

따라서 Decision Engine은 **GPU가 있어도 CPU를 기본으로 사용**한다.

향후 사용자가 직접 "고성능 routing" 옵션을 켤 경우에만 별도 backend를 허용할 수 있다.

---

# 11. 입력/출력 API

Ari 내부 API를 Jev와 비슷하게 설계하면 향후 backend 교체가 쉽다.

```python
DecisionEngine.choice(
    state="디스코드 좀 켜줘",
    instruction="Select the Ari action that best matches the request.",
    choices={
        "launch_app": "Open an installed desktop application",
        "web_search": "Search the web for information",
        "conversation": "Respond conversationally without an action",
        "run_agent_task": "Perform a multi-step autonomous computer task",
    },
)
```

응답:

```python
DecisionResult(
    choice="launch_app",
    probabilities={...},
    confidence=0.96,
    margin=0.92,
    source="ari_s1",
    latency_ms=3.1,
)
```

## MVP에서 구현할 primitive

1. `choice()` — 필수
2. `noul()` — Phase 2
3. `score()` — Phase 3

Ari의 첫 목적은 tool/intent routing이므로 Choice만으로 충분히 검증 가능하다.

---

# 12. Confidence 설계

## 중요한 원칙

raw softmax 최고값을 그대로 신뢰해서는 안 된다.

`0.99`가 실제 99% 정답률을 의미하도록 만들려면 calibration이 필요하다.

따라서 validation set으로 최소한 다음을 수행한다.

- Temperature Scaling
- ECE(Expected Calibration Error) 측정
- Brier Score
- reliability diagram

가능하면 위험도별 threshold를 따로 둔다.

## 초기 정책 예시

### 낮은 위험 / 쉽게 되돌릴 수 있음

예:

```text
launch_app
focus_window
get_current_time
get_weather
take_screenshot
```

조건 예:

```text
calibrated_probability >= 0.92
AND top1-top2 margin >= 0.30
```

이면 fast path 허용을 검토한다.

### 중간 위험

예:

```text
set_clipboard
schedule_task
write_file
```

Decision Engine은 routing까지만 하고 기존 안전 정책을 반드시 통과한다.

### 높은 위험 / 비가역

예:

```text
delete_file
send_email
shutdown_computer
execute_shell_command
execute_python_code
계정/권한 변경
외부 전송
```

**Decision Engine confidence만으로 자동 승인 금지.**

반드시 기존:

```text
SafetyChecker
ConfirmationManager
허용 경로
도구별 policy
```

를 그대로 통과한다.

---

# 13. Unknown / Abstain 반드시 지원

AriS1에는 실제 action 외에 항상 다음 후보가 있어야 한다.

```text
unknown_or_complex
```

또는 정책상 별도의 abstain gate를 둔다.

잘못된 직접 실행보다 LLM으로 넘기는 것이 훨씬 안전하다.

따라서 목표는 단순한 전체 accuracy가 아니다.

가장 중요한 metric은:

> **High-confidence로 직접 실행한 요청 중 얼마나 정확했는가?**

이다.

이를 selective accuracy라고 본다.

---

# 14. 데이터셋 설계

모델 품질의 대부분은 데이터셋이 결정한다.

## 14.1 언어

Ari 지원 언어 기준:

```text
Korean
English
Japanese
```

각 intent에 세 언어 데이터를 균형 있게 넣는다.

## 14.2 데이터 유형

### 명확한 문장

```text
크롬 열어줘
Open Chrome
Chromeを開いて
```

### 자연스러운 구어체

```text
크롬 좀 켜줄래?
디코 한번 띄워봐
소리 약간만 줄여줘
```

### STT 오류를 흉내낸 데이터

```text
크롬 열어 줘 → 크롬 여러줘
디스코드 켜줘 → 디스코드 겨줘
```

실제 Ari STT 로그에서 **사용자가 명시적으로 opt-in한 익명 샘플만** 활용하는 방향도 향후 고려할 수 있다.

### hard negative

```text
"크롬 열어줘"
→ launch_app

"크롬이 왜 자꾸 꺼지는지 검색해줘"
→ web_search

"크롬 관련 문제를 전부 확인해서 고쳐줘"
→ run_agent_task
```

서로 비슷한 단어를 쓰지만 action은 다른 데이터가 반드시 많아야 한다.

### 복합 요청

```text
"유튜브 켜고 재즈 검색해서 재생해줘"
```

이런 요청은 억지로 하나의 fast action에 맞추지 않고:

```text
complex_agent_task
```

로 보내는 학습이 필요하다.

---

# 15. 데이터 누수 방지

단순 random sentence split을 사용하면 비슷한 template가 train/test에 동시에 들어가 성능이 과대평가될 수 있다.

예:

```text
train: 크롬 열어줘
test: 디스코드 열어줘
```

이런 split은 너무 쉽다.

따라서 template/paraphrase family 단위로 split한다.

```text
train family
validation family
test family
```

최종 test set은 학습/threshold 설정 과정에서 절대 사용하지 않는다.

---

# 16. 현재 Ari 코드와 통합 위치

현재 `CommandRegistry`는 priority 순으로 명령을 검사하고 마지막에 `AICommand`가 fallback 역할을 한다.

현재:

```text
CommandRegistry
 ├ LearningCommand
 ├ YoutubeCommand
 ├ TimerCommand
 ├ WeatherCommand
 ├ VolumeCommand
 ├ SystemCommand
 ├ TimeCommand
 ├ CalculatorCommand
 ├ MemoryCommand
 └ AICommand(matches=True)
```

권장 통합은 **기존 deterministic command 뒤, 실제 LLM tool call 직전**이다.

즉:

```text
CommandRegistry deterministic match
 ↓ 실패
AICommand
 ↓
LocalDecisionEngine.try_fast_path(text)
 ├ successful safe decision → direct handler/parser
 └ abstain → 기존 chat_with_tools()
```

이 방식의 장점:

- 현재 동작을 거의 깨지 않는다.
- local engine을 완전히 비활성화하면 기존 Ari와 동일하게 동작한다.
- 문제가 생겨도 LLM fallback이 항상 남는다.

## 16.1 이미 존재하는 라우팅 자산 재사용

새로 만들기 전에 아래 두 모듈을 먼저 확인하고 재사용·확장한다. 중복 구현은 금지한다.

- `VoiceCommand/agent/tool_selection.py`
  `_TOOL_NAMES_BY_INTENT`가 이미 intent(`conversation`/`memory`/`web`/`file`/`vision`/`automation`/`schedule`) 단위로
  tool 집합을 정의한다. Decision Engine의 후보 집합(candidate registry)은 이 매핑을 단일 출처로 삼아 파생시키고,
  별도의 하드코딩 목록을 새로 만들지 않는다.
- `VoiceCommand/agent/llm_router.py`
  `LLMRouter`가 한/영/일 키워드 기반 task 분류를 이미 수행한다. Stage 1 deterministic rule은 이 키워드 자산을
  재사용하며, 동일한 키워드 테이블을 Decision Engine 쪽에 복제하지 않는다.

또한 사용자에게 노출되는 문자열이 새로 생기면 `docs/CONTRIBUTING.md`의 i18n 규칙에 따라
ko/en/ja 카탈로그에 동일한 msgid로 등록해야 한다. Decision Engine의 내부 로그·디버그 문자열은 번역 대상이 아니다.

---

# 17. Argument 추출은 별도 문제

Jev-like classifier가 `set_timer`를 골랐다고 해서 시간 값까지 모델로 생성하게 만들 필요는 없다.

예:

```text
"30분 뒤 컴퓨터 꺼줘"
```

Decision:

```text
schedule_task
```

> `schedule_shutdown`이라는 tool은 존재하지 않는다. 즉시 종료는 `shutdown_computer`, 지연 종료는 `schedule_task`가 담당하므로 후보 집합은 실제 tool 이름을 그대로 사용한다.

Argument:

```text
30분
```

은 기존 deterministic parser/regex를 사용한다.

원칙:

```text
판단 → ML
정확한 숫자/날짜/경로 → 코드 parser
문장 생성 → 기존 LLM
```

이 조합이 가장 안정적이다.

---

# 18. Plugin Tool 지원

Ari의 plugin system은 runtime에 새로운 tool schema를 등록할 수 있다.

따라서 장기적으로는 static intent classifier보다 **dynamic option scorer**가 더 매력적이다.

예:

```text
plugin 설치
 ↓
plugin tool description 추가
 ↓
AriS1 choice candidate 자동 추가
```

하지만 MVP에서는 안전하게 진행한다.

### Phase 1

built-in intent만 Local Decision Engine 적용.

plugin tool은 기존 LLM routing 유지.

### Phase 2

AriS1이 candidate description을 읽고 unseen option도 평가할 수 있는지 별도 benchmark.

성능이 검증되면 plugin tool까지 확대.

---

# 19. 권장 파일 구조

```text
VoiceCommand/
  agent/
    decision/
      __init__.py
      engine.py
      result.py
      policy.py
      rule_router.py
      local_scorer.py
      calibration.py
      candidate_registry.py

  resources/
    decision/
      ari_s1.onnx            # 최종 선택 시
      ari_s1_config.json
      ari_s1.sha256

  scripts/
    decision_data/
      build_dataset.py
      generate_candidates.py
      split_dataset.py
      evaluate.py
      benchmark.py

  tests/
    test_decision_engine.py
```

경로 주의사항:

- 저장소 최상위는 `Ari-VoiceCommand/`이고, 애플리케이션 패키지 루트이자 `sys.path` 기준 디렉터리는 `VoiceCommand/`다.
  따라서 위 트리는 모두 `VoiceCommand/` 하위이며, import 경로는 `agent.decision.engine` 형태가 된다
  (기존 코드가 `from agent.tool_schemas import ...`를 쓰는 것과 동일한 규칙).
- `VoiceCommand/resources/`는 현재 존재하지 않으므로 새로 만든다. 저장소 최상위에 `tools/` 디렉터리는 없으며,
  기존 보조 스크립트는 `VoiceCommand/scripts/`(`extract_strings.py`, `compile_po.py`)에 모여 있으므로 학습·평가 스크립트도 그 아래에 둔다.
- 테스트는 기존 `VoiceCommand/tests/` 규칙(`test_*.py`, `conftest.py` 공유)을 따른다.
- 모델 리소스를 배포에 포함하려면 `VoiceCommand/build_exe.py`의 번들 대상에 `resources/decision/`을 추가해야 한다.

모델 학습 코드는 실행 프로그램과 분리한다.

사용자 PC에는 inference에 필요한 최소 파일만 배포한다.

---

# 20. PyTorch를 최종 런타임에서 피하는 이유

연구 단계에서는 PyTorch가 편하다.

하지만 모델이 10MB인데 torch runtime 때문에 수백 MB 메모리가 늘어나면 목표를 잃는다.

따라서:

```text
연구/학습: PyTorch
        ↓
모델 확정
        ↓
ONNX / NumPy / custom runtime 변환
        ↓
Ari 배포
```

을 우선 검토한다.

Ari가 다른 기능 때문에 이미 torch를 사용하는 환경이라 하더라도 Decision Engine이 **torch GPU context를 활성화해서는 안 된다.**

---

# 21. 모델 파일 안전성

외부 모델 파일을 자동 다운로드해 pickle 형태로 로드하면 공급망 위험이 생긴다.

따라서 최종 배포는 가능한 한:

- ONNX
- safetensors
- raw numeric weights + JSON

중 하나를 사용한다.

그리고:

```text
모델 version
SHA-256
training dataset version
calibration version
```

을 함께 기록한다.

자동 다운로드 기능이 있다면 hash 검증 후 로드한다.

---

# 22. Benchmark 계획

## 22.1 정확도

언어별:

```text
ko accuracy
en accuracy
ja accuracy
```

intent별 confusion matrix도 필수다.

## 22.2 Selective Accuracy

threshold보다 높은 명령만 자동 처리했을 때:

```text
coverage
selective accuracy
false-direct count
```

을 측정한다.

Ari에서는 전체 accuracy보다 이 수치가 중요하다.

## 22.3 복합 요청 감지

별도 test bucket:

```text
single action
multi action
conversation
knowledge question
agent task
ambiguous request
```

복합 요청을 단일 action으로 잘못 보내는 비율을 추적한다.

## 22.4 STT Noise

실제 음성비서 특성상 clean text benchmark만으로 부족하다.

다음 변형을 생성한다.

- 띄어쓰기 오류
- 조사 누락
- 유사 발음
- 숫자 표기 차이
- 영어 앱 이름의 한글 transcription

## 22.5 성능

각 환경에서:

```text
cold start
warm p50
warm p95
warm p99
peak RSS
steady RSS
CPU time
model load time
```

측정.

최소 테스트 하드웨어 그룹:

```text
저사양 노트북 CPU
보급형 데스크톱 CPU
현 개발 PC급 CPU
GPU 없음 모드
```

---

# 23. 초기 채택 기준

아래는 목표치이며 실제 데이터 기반으로 조정한다.

### Fast path 선택 품질

```text
High-confidence selective accuracy >= 99%
```

되돌리기 어려운 action에서는 이 수치와 관계없이 safety gate 유지.

### Coverage

첫 버전부터 모든 문장을 fast path로 보내는 것을 목표로 하지 않는다.

예:

```text
30~60%의 단순 요청만 fast path
나머지는 LLM fallback
```

이어도 성공이다.

정확한 것만 빠르게 처리하는 것이 목적이다.

### 리소스

```text
model <= 50 MB
GPU = 0 MB
background CPU ~= 0
warm p95 <= 20~30 ms
```

목표를 넘으면 모델 축소 또는 fallback 비중을 높인다.

---

# 24. 구현 단계

## Phase 0 — Benchmark harness

먼저 코드보다 데이터/평가기를 만든다.

- 현재 built-in tool 목록 snapshot
- 한/영/일 seed dataset
- hard negative dataset
- compound request dataset
- latency/RSS benchmark harness
- calibration metric

**산출물:** 기준점

---

## Phase 1 — Linear Micro Router

Character n-gram + linear model을 구현한다.

목적:

> Ari 문제 자체가 얼마나 쉬운지 확인

이게 충분히 높은 selective accuracy를 보이면 더 복잡한 모델이 필요 없을 수도 있다.

---

## Phase 2 — AriS1 Tiny Option Scorer

Linear baseline이 부족한 문장들을 대상으로 Jev-like dynamic scorer를 구현한다.

- hashed char n-gram
- small encoder
- option descriptions
- one-pass probabilities
- temperature scaling

Linear과 동일 test set으로 비교한다.

---

## Phase 3 — Ari Integration

기능 플래그:

```json
{
  "local_decision_engine_enabled": true,
  "local_decision_backend": "linear",
  "local_decision_threshold": 0.92,
  "local_decision_direct_execution": true
}
```

이 플래그는 `VoiceCommand/ari_settings.template.json`에 기본값과 함께 추가하고,
설정 로더(`ConfigManager`)가 기존 키와 동일한 방식으로 읽도록 한다.
템플릿에 없는 키를 코드에서만 참조하면 신규 설치 환경에서 기본값이 누락된다.

기본값은 초기 베타 동안 direct execution을 보수적으로 설정할 수 있다.
`local_decision_direct_execution`의 초기 기본값은 `false`로 두고, Phase 4 shadow mode 결과가
채택 기준을 만족한 뒤에 `true`로 전환한다.

---

## Phase 4 — Shadow Mode

바로 실행하지 않고 기존 LLM 결과와 비교한다.

```text
MicroJev prediction
vs
실제로 실행된 command
```

사용자에게 영향을 주지 않는 상태로 accuracy를 수집한다.

개인정보 보호를 위해 raw 문장은 기본적으로 외부 서버에 전송하지 않는다.

---

## Phase 5 — Safe Fast Path

검증된 low-risk action부터 직접 실행.

예:

```text
get_current_time
get_weather
launch_app
focus_window
adjust_volume
take_screenshot
```

단계적으로 확대한다.

---

## Phase 6 — Plugin dynamic routing

동적 plugin option까지 scorer가 처리 가능한지 검증.

성능이 충분하지 않으면 plugin은 계속 기존 LLM으로 보낸다.

---

# 25. 실패 시 fallback 원칙

Decision Engine은 **Ari가 동작하기 위한 필수 dependency가 아니다.**

다음 상황은 모두 자동 fallback한다.

```text
model file missing
model checksum mismatch
load error
inference exception
confidence low
unknown class
argument parser failure
multi-intent detected
unsupported plugin
```

fallback:

```text
기존 Ari AICommand / LLMProvider
```

따라서 새로운 기능 때문에 기존 사용자 경험이 깨지지 않아야 한다.

---

# 26. 최종 권장안

현재 조사 결과를 기준으로 가장 합리적인 개발 순서는 다음과 같다.

```text
1. 기존 CommandRegistry rule 유지
            ↓
2. Character n-gram Linear Router 제작
            ↓
3. Ari 한/영/일 실제 데이터에서 검증
            ↓
4. 충분하면 그대로 채택
            ↓ 부족하면
5. jevbetter-inspired AriS1 one-pass scorer 제작
            ↓
6. Calibration + Confidence Gate
            ↓
7. Low-risk command fast path
            ↓
8. 복잡한 요청은 기존 LLM/Agent
```

즉 처음부터 300M~600M 모델을 넣지 않는다.

**Ari의 제한된 작업 공간을 최대한 이용하여 "Jev의 UX 효과"를 수 MB~수십 MB 모델로 얻는 것**이 핵심이다.

---

# 27. 조사 자료

## 공식 Jev / TypeSafe

- TypeSafe AI — Introducing System One Models & Jev  
  https://typesafe.ai/blog/introducing-system-one-models-and-jev
- TypeSafe AI  
  https://typesafe.ai/

## Open/local research

- `vinnylarouge/jevlike`  
  https://github.com/vinnylarouge/jevlike
- `olanotolu/jevbetter`  
  https://github.com/olanotolu/jevbetter
- `wfzyx/von`  
  https://github.com/wfzyx/von
- `jaredpalmer/kev`  
  https://github.com/jaredpalmer/kev
- `zhengxuyu/litjev`  
  https://github.com/zhengxuyu/litjev
- `trycua/cua` — CUA-S1 research family  
  https://github.com/trycua/cua/tree/main/libs/cua-s1
- Jev reproductions/community research tracker  
  https://github.com/AnotiaWang/awesome-jev
  
주의: 이 영역의 프로젝트는 Jev 공개 직후 만들어진 초기 연구가 많다. README에 표시된 성능은 해당 프로젝트 저자의 자체 측정인 경우가 많으므로 Ari 채택 전 반드시 동일한 Ari benchmark로 재측정해야 한다.

---

# 28. Ari 코드 참고 위치

검토 기준 commit: `f7cc6d35d284bea5e6f42bca5076cb7280974b2a`

- LLM router  
  https://github.com/DO0OG/Ari-VoiceCommand/blob/f7cc6d35d284bea5e6f42bca5076cb7280974b2a/VoiceCommand/agent/llm_router.py
- LLM provider / tool calling  
  https://github.com/DO0OG/Ari-VoiceCommand/blob/f7cc6d35d284bea5e6f42bca5076cb7280974b2a/VoiceCommand/agent/llm_provider.py
- AICommand dispatch  
  https://github.com/DO0OG/Ari-VoiceCommand/blob/f7cc6d35d284bea5e6f42bca5076cb7280974b2a/VoiceCommand/commands/ai_command.py
- CommandRegistry  
  https://github.com/DO0OG/Ari-VoiceCommand/blob/f7cc6d35d284bea5e6f42bca5076cb7280974b2a/VoiceCommand/commands/command_registry.py
- Tool schemas  
  https://github.com/DO0OG/Ari-VoiceCommand/blob/f7cc6d35d284bea5e6f42bca5076cb7280974b2a/VoiceCommand/agent/tool_schemas.py
- Tool selection  
  https://github.com/DO0OG/Ari-VoiceCommand/blob/f7cc6d35d284bea5e6f42bca5076cb7280974b2a/VoiceCommand/agent/tool_selection.py
- SafetyChecker  
  https://github.com/DO0OG/Ari-VoiceCommand/blob/f7cc6d35d284bea5e6f42bca5076cb7280974b2a/VoiceCommand/agent/safety_checker.py

---

# 29. 최종 한 문장

**Ari에 필요한 것은 "무료 Jev 복제품"이 아니라, Jev의 구조화된 빠른 판단·확률·abstain 개념을 가져와 Ari의 제한된 명령 공간에 특화한 초경량 로컬 Decision Engine이다.**

이 방식이 성공하면 단순 음성 명령은 거의 즉시 처리하면서도 GPU를 점유하지 않고, 어려운 요청에서만 기존 LLM/Agent를 사용하게 되어 Ari의 반응 속도와 비용, 오프라인성 모두 개선할 수 있다.
