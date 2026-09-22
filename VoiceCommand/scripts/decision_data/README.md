# 로컬 분류 기준선

Python 3.11, NumPy와 psutil을 사용한다. 추가 설치나 외부 호출은 없다.
아래 명령은 `VoiceCommand/`에서 실행한다.

```powershell
.venv/Scripts/python.exe -m scripts.decision_data.build_dataset --output scripts/decision_data/dataset.jsonl
.venv/Scripts/python.exe -m scripts.decision_data.train
.venv/Scripts/python.exe -m scripts.decision_data.evaluate
.venv/Scripts/python.exe -m scripts.decision_data.evaluate --gold
.venv/Scripts/python.exe -m scripts.decision_data.benchmark
```

`seed_data.py`와 `expanded_data.py`는 한·영·일 예문과 슬롯 확장 규칙을 담는다.
번역, 동일 문형, 엔티티 교체, 말투와 음성인식 오류 변형을 같은 family에 묶어
train/calibration/test로 나눈다. 실제 발화 분포를
대표하지 않으며 test 수치를 보고 자료나 임계값을 조정하지 않는다.

`gold.jsonl`은 별도로 보관하는 평가 전용 자료다. 기본 생성·학습·보정 경로에
포함하지 않으며, 예약된 문장이나 family가 학습 입력에 섞이면 계산 전에 거부한다.
`--gold`는 별도 평가 결과를 기록한다. `pending_human_review` 상태는 아직 사람이
검토하지 않았다는 뜻이며, 검토가 끝나기 전에는 최종 품질 인증 자료로 취급하지 않는다.

학습은 train만 사용하며 calibration의 NLL로 temperature를 정한다. 문자 2~5 gram,
NFKC/casefold, CRC32, L2 정규화는 배포 코드의 함수를 그대로 사용한다.
`resources/decision/`의 `weights.npz`와 `config.json`만 배포한다. 설정에는 버전,
학습 자료 해시, 보정 버전, 가중치 SHA-256이 들어 있다. 파일 누락이나 손상 후에는
반복 로드를 시도하지 않으므로 파일을 복원했다면 앱을 재시작한다.

`candidate_snapshot.json`의 후보 목록은 명시적 registry를 따른다.
의도 매핑과 스키마는 누락 진단용으로 함께 기록한다. 평가 JSON에는 언어별 정확도,
10개 reliability bin, ECE, multiclass Brier(클래스별 제곱 오차 합의 평균), 혼동 행렬,
bucket별 결과와 오선택 수가 들어 있다. Selective accuracy는 신뢰도 0.92 이상,
1·2위 차이 0.30 이상이며 unknown이 아닌 예측에 대해 계산한다. 선택이 없으면
`null`로 표시한다. 기존 복합 요청 규칙을 적용한 선택 지표도 따로 기록한다.
직접 실행 정책까지 적용한 지표는 `with_direct_policy_gate`에 분리해 기록한다.
평가 명령은 기존 matplotlib로 같은 이름의 PNG reliability diagram도 생성한다.

벤치마크는 새 프로세스에서 실행한다. 추가 RSS는 NumPy 및 분류 모듈 import 전부터
가중치 로드와 반복 추론 후까지의 차이다. 지연 측정은 한·영·일 짧은 입력 3개를
순환하며 30회 예열 후 1,000회를 측정한다. 다른 CPU 환경의 성능을 보장하지 않는다.

이번 범위는 후보 정책과 자료 확장이다. `local_decision_engine_enabled=true`,
`local_decision_backend=linear`, `local_decision_threshold=0.92`가 기본값이다.
`local_decision_mode`는 `off` / `shadow` / `fast` / `adaptive`이며 기본값은 `shadow`다.
설정 키가 없거나 값이 잘못되어도 `shadow`로 처리한다. `off`는 분류를 건너뛴다.
`local_decision_direct_execution` 기본값은 false다. 직접 처리는 모드가 `fast` 또는
`adaptive`이고 이 설정이 true일 때만 열리며, 그때도 허용 후보(시간, 실행 앱 목록,
스크린샷, 음량)이면서 의미 해석기가 인자와 의도를 확정하고 모순이나 남은 동작이
없어야 한다. 하나라도 어긋나면 기존 호출을 진행한다. 직접 처리는 기존 처리기를
그대로 호출하고 응답은 번역된 고정 문구를 쓰므로 대화 호출이 생기지 않는다.
플래그를 끄면 분류 모듈을 로드하지 않는다. 위험 작업에 새 실행 경로를 만들지 않는다.
개인별 학습 및 실사용 발화 수집은 이번 범위에 포함하지 않는다.

## 초기 기준선 기록

아래 수치는 자료 확장 전 초기 기준선이며 현재 결과는 `evaluation.json`을 따른다.
당시에는 40개 스키마 중 의도 매핑에 있는 36개와 unknown을 학습했다.
1,136개 문장, 182개 family를 train 616 / calibration 263 / test 257로 분할했다.
고정한 test에서 accuracy 41.25%(ko 37.50%, en 40.00%, ja 46.43%), ECE 0.12157,
Brier 0.75518이다. 선택 정확도는 2/2, coverage 0.78%이며 직접 실행 허용의 근거로
사용할 수 없는 작은 표본이다. 추가 자료 수집과 독립 평가가 필요하다.
측정 시 warm p50/p95/p99는 0.049/0.074/0.100ms, 추가 steady RSS는 17.22MiB였다.
원시 수치는 `evaluation.json`, `benchmark_results.json`을 참고한다.

## Phase 3 실험 기록

아래 결과는 숫자 표현 변형을 마지막으로 반영하기 전 고정 자료에 대한 과거
실험 기록이다. 결과 파일은 저장소 루트의
`.omc/handoffs/resume/phase3/current_experiments.json`이며,
16,506행, 356 family를 사용했다. 직접 실행 정책의 `false_direct_count`가 0이
아니면 후보를 채택하지 않는 규칙을 적용했다.

| 구성 | 정확도 | ECE | NLL | 정책 적용 coverage | false_direct_count |
| --- | ---: | ---: | ---: | ---: | ---: |
| 기준 문자 n-gram | 0.798742 | 0.065386 | 0.904483 | 0.464151 | 43 |
| word unigram/bigram | 0.781761 | 0.050265 | 0.942281 | 0.444654 | 39 |
| 숫자·시간 신호 | 0.806289 | 0.043631 | 0.848291 | 0.518239 | 34 |
| 문장 길이·명령형 신호 | 0.779874 | 0.068607 | 0.952971 | 0.445912 | 44 |

숫자·시간 신호는 일반 지표가 좋아졌지만 안전 기준을 충족하지 못했고, 나머지
구성도 같은 이유로 제외했다. 표의 수치는 calibration 분할 결과이며, 같은 과거
실험의 별도 held-out 분할에서는 기준 구성의 `false_direct_count=1`이었다.
두 수치는 서로 다른 평가 분할의 결과이므로 혼용하지 않는다. 현재 구성은 기존 문자 n-gram과 전역
temperature 보정을 유지하며, 임계값과 margin은 바꾸지 않는다. 위 기록의
held-out 결과는 최신 재학습 결과와 혼용하지 않는다.

이번 비교에서 측정한 특징은 word unigram/bigram, 숫자·시간 신호, 문장 길이·
명령형 신호 세 가지다. URL, 파일 경로, 앱 별칭, 개체 신호는 별도로 측정하지
않았으므로 채택 여부를 단정하지 않는다.

## 2-A 범위와 문맥 한계

변형 생성기는 조사 생략, 종결어미와 높임말, 어순 도치, 축약, 채움말과 요청
완충, 반복, 붙여쓰기와 과분리, 문장부호 소실, 숫자 표기, 외래어 표기, 연음·
종성·소리 혼동을 지원한다. 변형은 원문과 같은 family에 묶고, 의미가 뒤집히는
충돌은 생성 결과에서 제외한다.

`그거 좀 꺼줘`처럼 대상이 문장에 없는 표현을 대상으로 추정하는 변형은 추가하지
않는다. `그 크롬 그거 좀 켜줘`처럼 대상은 있으나 세 변환을 한 번에 겹치는 표현은
현재 생성기의 최대 두 변환 조합 범위 밖이므로 무조건 확장하지 않는다.
