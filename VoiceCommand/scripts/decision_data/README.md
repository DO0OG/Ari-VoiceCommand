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
`local_decision_direct_execution=false`이며, true로 바꾸더라도 Phase 5의 인자 파서와
안전 정책 검증 전에는 직접 실행하지 않는다. 판단은 메모리에만 보관하고 기존 호출을
진행한다. 플래그를 끄면 분류 모듈을 로드하지 않는다. 위험 작업에 새 실행 경로를
만들지 않는다. 직접 실행, 개인별 학습 및 실사용 발화 수집은 이번 범위에 포함하지 않는다.

## 초기 기준선 기록

아래 수치는 자료 확장 전 초기 기준선이며 현재 결과는 `evaluation.json`을 따른다.
당시에는 40개 스키마 중 의도 매핑에 있는 36개와 unknown을 학습했다.
1,136개 문장, 182개 family를 train 616 / calibration 263 / test 257로 분할했다.
고정한 test에서 accuracy 41.25%(ko 37.50%, en 40.00%, ja 46.43%), ECE 0.12157,
Brier 0.75518이다. 선택 정확도는 2/2, coverage 0.78%이며 직접 실행 허용의 근거로
사용할 수 없는 작은 표본이다. 추가 자료 수집과 독립 평가가 필요하다.
측정 시 warm p50/p95/p99는 0.049/0.074/0.100ms, 추가 steady RSS는 17.22MiB였다.
원시 수치는 `evaluation.json`, `benchmark_results.json`을 참고한다.
