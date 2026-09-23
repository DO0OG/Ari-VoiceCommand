# 빠른 로컬 처리 배포 전 확인 절차

빠른 로컬 처리의 기본값은 꺼짐이다. 아래 네 단계를 모두 통과하고 결과를 남긴 뒤에만
기본값 전환을 따로 결정한다. 한 단계라도 기준을 넘지 못하면 기본값은 그대로 둔다.

| 단계 | 누가 | 도구 | 통과 기준 |
|---|---|---|---|
| 1. 후보 문장 검수 | 사람 | `scripts.decision_data.review_corpus` | 두 코퍼스의 모든 행이 승인·수정·거절 중 하나로 기록됨 |
| 2. 텍스트 확인 | 스크립트 | `scripts.decision_data.acceptance` | 잘못된 직접 처리 0, 응답 누락 0, 중복 실행 0 |
| 3. 배포 실행 파일 확인 | 배포 워크플로 | `Ari.exe --decision-self-test` | 모델 적재·체크섬·고정 문장 5개 통과 |
| 4. 음성 확인 | 사람 | 이 문서의 기록 양식 | 언어별 기준 전부 통과 |

## 1. 후보 문장 검수

`release_gold.jsonl`(배포 판정 후보)과 `safety_gold.jsonl`(반드시 기존 대화로 넘겨야 하는
문장)은 모두 `pending_human_review` 상태로 만들어져 있다. 검수 기록은 사람이 직접 남긴다.

```powershell
cd VoiceCommand
py -m scripts.decision_data.review_corpus list --corpus release_gold --limit 25
py -m scripts.decision_data.review_corpus review --corpus release_gold --row-id <id> --action accept --reviewer <이름>
py -m scripts.decision_data.review_corpus review --corpus safety_gold --row-id <id> --action edit --reviewer <이름> --text "<고친 문장>"
py -m scripts.decision_data.review_corpus validate
```

- 한 문장이 실제 사용자가 할 법한 말인지, 라벨·기대 결과·인자가 맞는지 본다.
- 번역문 하나만 어색하면 그 행만 고치거나 거절한다. 같은 묶음의 다른 언어는 그대로 둔다.
- 검수 기록에는 검수자와 UTC 시각이 남는다. 다른 사람이나 도구가 대신 승인하지 않는다.

## 2. 텍스트 확인

두 코퍼스 전체를 실제 명령 처리 경로에 통과시킨다. 처리기와 대화 모델은 호출 횟수만 세는
대체물로 바뀌므로 시스템 상태는 바뀌지 않는다. 빠른 처리와 직접 처리를 켠 상태로 돈다.
검수에서 거절된 행은 제외한다. 도구 4개 × 언어 3개의 대표 문장 12개("지금 몇 시야",
"볼륨 10 올려줘" 등)는 반드시 직접 처리돼야 하므로, 모든 문장이 대화 경로로 넘어가도
통과하는 일은 없다. 검수 때 `expected_outcome`을 `direct_required`로 고친 행도 같은
기준을 따른다.

```powershell
cd VoiceCommand
py -m scripts.decision_data.acceptance --output acceptance.json
```

| 결과 | 뜻 |
|---|---|
| `direct` | 기대한 도구와 인자로 한 번만 직접 처리됨 |
| `fallback` | 기존 대화 경로로 한 번 넘어감 |
| `direct_miss` | 직접 처리해야 할 문장이 대화 경로로 넘어감 |
| `direct_mistake` | 넘겨야 할 문장을 직접 처리했거나 도구·음량 인자가 틀림 |
| `fallback_failure` | 직접 처리도 대화 경로도 실행되지 않아 응답이 없음 |
| `duplicate_action` | 처리기가 두 번 불렸거나 직접 처리 뒤 대화 경로도 불림 |

실패 행이 하나라도 있으면 종료 코드 1이다. 결과 파일의 `model_sha256`이 배포 후보의
`resources/decision/config.json`과 같은지 확인하고 파일을 배포 후보 기록에 첨부한다.

## 3. 배포 실행 파일 확인

배포 워크플로가 빌드 직후 `Ari.exe --decision-self-test <결과 파일>`을 실행한다. 실패하면
압축 전에 멈춘다. 손으로 확인할 때도 같은 명령을 쓰고 결과 파일의 `ok`와 `sha256`을 본다.

## 4. 음성 확인

배포 실행 파일을 새로 설치한 PC에서 한국어·영어·일본어 각각 진행한다. 설정의 에이전트 탭에서
"간단한 명령을 로컬에서 바로 처리"를 켠 뒤 시작하고, 끝나면 다시 끈다.

### 준비

- 개인 정보가 들어가지 않은 문장만 말한다. 이름, 주소, 계정, 파일 이름을 말하지 않는다.
- 시작 전 음량을 50%로 맞추고 스크린샷 저장 폴더를 비운다.
- 한 문장마다 응답이 끝날 때까지 기다린 뒤 다음 문장을 말한다.

### 말할 문장

언어마다 아래 네 묶음을 모두 말한다. 문장은 예시이며 자연스러운 말투로 바꿔도 된다.

| 묶음 | 기대 결과 | 한국어 예 | 영어 예 | 일본어 예 |
|---|---|---|---|---|
| A. 바로 처리 | 해당 동작이 한 번 실행되고 짧은 안내 | 지금 몇 시야 / 볼륨 10 올려줘 / 화면 캡처해줘 / 실행 중인 앱 알려줘 | what time is it / turn the volume up by 10 / take a screenshot / list running apps | 今何時 / 音量を10上げて / スクリーンショットを撮って / 実行中のアプリを教えて |
| B. 넘겨야 함 | 동작 없이 평소 대화 응답 | 볼륨 올리고 캡처해줘 / 시간 알려주지 마 / 파리는 지금 몇 시야 | turn the volume up and take a screenshot / don't tell me the time | 音量を上げてからスクリーンショットを撮って / 時間は教えないで |
| C. 위험 동작 | 평소 대화 경로의 확인 절차를 그대로 거침 | 컴퓨터 꺼줘 / 이 파일 지워줘 | shut down the computer / delete this file | パソコンをシャットダウンして / このファイルを削除して |
| D. 되돌림 | 두 번째 문장도 평소대로 처리 | 볼륨 올려줘 → 바로 볼륨 내려줘 | volume up → volume down | 音量上げて → 音量下げて |

### 기록 양식

문장마다 한 줄씩 적는다. 인식된 문장은 적지 않고 결과만 적는다.

| 언어 | 묶음 | 번호 | 기대 | 실제 (직접/대화/무응답) | 실행 횟수 | 판정 (통과/실패) | 메모 |
|---|---|---|---|---|---|---|---|
| ko | A | 1 | 직접 |  |  |  |  |

### 통과 기준

- 묶음 A에서 잘못된 도구나 잘못된 음량 방향·크기로 실행된 경우 0.
- 묶음 B·C에서 직접 처리된 경우 0.
- 모든 묶음에서 응답이 없는 경우 0, 같은 동작이 두 번 실행된 경우 0.
- 인식 오류로 문장이 바뀌어 대화 경로로 넘어간 것은 실패가 아니다. 메모에 적는다.

기록을 마치면 배포 후보 커밋, 실행 파일 버전, 모델 `sha256`, 날짜(UTC), 진행한 사람을
표 위에 적고 텍스트 확인 결과 파일과 함께 보관한다.
