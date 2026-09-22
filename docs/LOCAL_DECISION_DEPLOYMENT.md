# 로컬 판정 자원 배포 기록

## 배포 판정

`fc1cc4e` 이후 숫자 표현 변형을 포함한 증강 자료로 가중치를 새로 생성해
`VoiceCommand/resources/decision/`에 반영했다. 임계값과 margin은 바꾸지 않았다.

이 배포 판정에 사용한 평가는 사용자가 제공한 재학습 결과다. 이 기록을 작성하면서
전체 평가를 다시 실행하지 않았다.

| 항목 | 결과 |
| --- | ---: |
| 전체 false_direct_count | 0 |
| 전체 selected | 1,665 |
| 전체 coverage | 0.4900 |
| 전체 accuracy | 0.8049 |
| 전체 ECE | 0.0451 |
| 전체 Brier | 0.2532 |
| 기존 규칙 적용 false_direct_count | 0 |
| 기존 규칙 적용 selected | 1,564 |
| 기존 규칙 적용 coverage | 0.4603 |
| 직접 실행 정책 적용 false_direct_count | 0 |
| 직접 실행 정책 적용 selected | 1,560 |
| 직접 실행 정책 적용 coverage | 0.4591 |
| 직접 실행 정책 적용 selective accuracy | 1.0000 |
| unknown 오선택 수 | 0 |

언어별 정확도는 한국어 0.8005, 영어 0.8579, 일본어 0.7843이었다. 직접 실행 정책을
통과한 오선택이 0건이고 unknown 오선택도 0건이므로 현재 배포본을 증강 구성으로
교체했다.

직전 증강 구성과 비교하면 정확도는 0.8070에서 0.8049로 0.21%p 낮아졌고,
coverage는 0.4968에서 0.4900으로 0.68%p 낮아졌다. ECE는 0.0410에서 0.0451로
0.0041 높아졌다. 모두 허용한 변동 범위 안이며, false_direct_count를 1에서 0으로
낮춘 결과를 우선해 배포를 결정했다.

## 생성 결과

| 항목 | 값 |
| --- | --- |
| 자료 버전 | `decision-dataset-v2` |
| 증강 사용 | `true` |
| 보정 방식 | `temperature-nll-v1` |
| temperature | `0.9753445989443437` |
| 학습 / 보정 / 시험 행 수 | `8565 / 4543 / 3398` |
| 사용 행 수 | `10155` |
| 후보 수 | `41` |
| 학습 자료 SHA-256 | `0063cc0c2daa2011c83288717502b7fa94dc0391910994648abf3d23db5ec928` |
| 가중치 SHA-256 | `1e45779eb67f3ae77f13476c01dd2e451f17b1b0047e2976726711b1431fccbd` |

`config.json`의 가중치 SHA-256과 실제 `weights.npz`의 SHA-256이 일치하고, 후보 41개,
버킷 8,192개, 보정값 양수 조건을 확인했다. 생성 중 런타임 쓰기 경로는 임시 디렉터리로
격리했다.

## 단계 경계

Phase 1은 정책과 호출 배선 기준으로 완료로 판정한다. 허용 목록, 영구 금지 목록,
`off`·`shadow`·`fast`·`adaptive` 모드와 기본 `shadow` 값이 연결되어 있다.

직접 실행 자체는 Phase 5 경계에 둔다. 현재 판정 결과는 메모리에 보관하고, 인자 해석과
안전 정책 검증이 끝나기 전에는 판정만으로 실행하지 않는다. 따라서 이번 배포는 판정
품질 자료와 판정 자원을 갱신한 것이며 기존 실행 경로의 안전 절차를 우회하지 않는다.

## 검증

다음 명령을 Python 3.11 실행 파일로 수행했다.

```text
C:\Users\AJH\AppData\Local\Programs\Python\Python311\python.exe -m unittest discover -t . -s tests -p "test_*.py"
```

결과는 `Ran 577 tests in 17.763s`, `OK (skipped=1)`, 종료 코드 0이었다.
`ARI_APP_DATA_DIR`는 임시 경로로 격리했고 검증 후 삭제했다. `.ari_runtime` 전후 지문은
`38524ee8aa8a1ed8d5be3c643ad451c50f8e367a12aab9839c25d222901bdde8`로 동일했다.
