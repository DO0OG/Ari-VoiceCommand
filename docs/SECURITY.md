# 릴리스 파일 확인과 백신 검출 안내

내려받은 설치 파일을 확인하는 방법과 백신 검출에 대한 안내입니다.

## 공식 배포처

공식 파일은 [GitHub Releases](https://github.com/DO0OG/Ari-VoiceCommand/releases)에서만 배포합니다. 릴리스 자산은 다음과 같습니다.

- `Ari-Setup-<version>.exe`
- `update.json` (사전 배포판은 `update-beta.json`)
- `SHA256SUMS.txt`

## SHA-256으로 파일 확인

`SHA256SUMS.txt`는 `<소문자 16진 sha256>  Ari-Setup-<version>.exe` 한 줄입니다. 두 파일을 같은 폴더에 두고 PowerShell에서 실행하세요. `Get-FileHash`는 대문자로 출력하지만 `-eq`는 대소문자를 구분하지 않아 그대로 비교됩니다.

```powershell
$f = 'Ari-Setup-<version>.exe'
$expected = ((Get-Content .\SHA256SUMS.txt | Where-Object { $_ -like "*  $f" }) -split '\s+')[0]
if ((Get-FileHash .\$f -Algorithm SHA256).Hash -eq $expected) { '일치' } else { '불일치' }
```

`불일치`가 나오면 설치하지 말고 파일을 다시 받으세요.

## 빌드 출처 증명

v1.3.3 다음 릴리스부터 릴리스 자산(설치 파일, 업데이트 manifest, `SHA256SUMS.txt`)에 GitHub 빌드 출처 증명이 붙습니다. v1.3.3까지의 릴리스에는 없습니다. [GitHub CLI](https://cli.github.com/)로 확인합니다.

```powershell
gh attestation verify .\Ari-Setup-<version>.exe --repo DO0OG/Ari-VoiceCommand
```

이 증명은 파일이 이 저장소의 공개 워크플로에서 어느 커밋으로 빌드됐는지를 보여 줍니다.

## 이 확인들이 보증하지 않는 것

체크섬과 출처 증명은 파일이 공식 릴리스와 같고 공개 워크플로에서 만들어졌음을 보여 줄 뿐, 빌드 환경이나 의존성 전체가 안전하다는 보증은 아닙니다. Ari는 독립된 보안 감사를 받지 않았습니다.

## 코드 서명

설치 파일과 `Ari.exe`에는 아직 Authenticode 서명이 없습니다. 그래서 Windows SmartScreen이나 백신이 경고를 띄울 수 있습니다. 서명을 추진할 계획이며 진행 상황은 [이슈 #389](https://github.com/DO0OG/Ari-VoiceCommand/issues/389)에서 볼 수 있습니다.

## 백신 검출

`Ari.exe`는 Nuitka로 컴파일한 Python 프로그램이고 설치 파일은 Inno Setup으로 만듭니다. 서명이 없는 설치 파일이나 컴파일된 Python 프로그램은 휴리스틱·머신러닝 기반 검사에서 검출되는 경우가 있습니다.

v1.3.3 조사 요약입니다(자세한 근거는 [이슈 #386](https://github.com/DO0OG/Ari-VoiceCommand/issues/386)).

- 조사 시점에 공식 설치 파일은 VirusTotal 1/57이었습니다.
- 제보된 22/67 표본은 설치 파일에 따로 들어 있는 파일이 아니라, 설치 프로그램(Inno Setup) 로더가 메모리에 올라간 모습을 복원한 것으로 판단했습니다. 다만 원본 표본을 직접 받아 대조한 것은 아닙니다.

검출 결과는 시점과 제품에 따라 달라집니다. 이 문서는 백신 경고를 무시하라는 뜻이 아닙니다. 오탐 검토 요청과 릴리스별 점검은 [이슈 #390](https://github.com/DO0OG/Ari-VoiceCommand/issues/390)에서 진행합니다.

## 알리는 방법

- 의심스러운 검출 결과는 GitHub 이슈로 알려 주세요. 파일 이름과 버전, 파일을 받은 경로, SHA-256, 검사 서비스 결과 링크, 검출 이름을 함께 적어 주세요.
- 보안 취약점은 공개 이슈에 세부 내용을 적지 말고 저장소 Security 탭의 "Report a vulnerability"(비공개 신고)를 이용해 주세요.

<details>
<summary>English</summary>

# Verifying Release Files and Antivirus Detections

How to verify a downloaded installer, and notes on antivirus detections.

## Official distribution

Official files are distributed only through [GitHub Releases](https://github.com/DO0OG/Ari-VoiceCommand/releases). The release assets are:

- `Ari-Setup-<version>.exe`
- `update.json` (`update-beta.json` for pre-releases)
- `SHA256SUMS.txt`

## Verify with SHA-256

`SHA256SUMS.txt` holds one line: `<lowercase hex sha256>  Ari-Setup-<version>.exe`. Put both files in the same folder and run this in PowerShell. `Get-FileHash` prints uppercase, but `-eq` is case-insensitive, so the values compare correctly.

```powershell
$f = 'Ari-Setup-<version>.exe'
$expected = ((Get-Content .\SHA256SUMS.txt | Where-Object { $_ -like "*  $f" }) -split '\s+')[0]
if ((Get-FileHash .\$f -Algorithm SHA256).Hash -eq $expected) { 'match' } else { 'mismatch' }
```

If it prints `mismatch`, do not install the file; download it again.

## Build provenance attestation

Starting with the release after v1.3.3, the release assets (installer, update manifest, and `SHA256SUMS.txt`) carry a GitHub build provenance attestation. Releases up to v1.3.3 do not have one. Verify with the [GitHub CLI](https://cli.github.com/):

```powershell
gh attestation verify .\Ari-Setup-<version>.exe --repo DO0OG/Ari-VoiceCommand
```

The attestation shows which commit of this repository's public workflow built the file.

## What these checks do not guarantee

The checksum and attestation only show that a file matches the official release and was produced by the public workflow. They do not guarantee that the build environment or all dependencies are safe. Ari has not had an independent security audit.

## Code signing

The installer and `Ari.exe` do not have an Authenticode signature yet, so Windows SmartScreen or antivirus software may show a warning. Code signing is planned; progress is tracked in [issue #389](https://github.com/DO0OG/Ari-VoiceCommand/issues/389).

## Antivirus detections

`Ari.exe` is a Python program compiled with Nuitka, and the installer is built with Inno Setup. Unsigned installers and compiled Python programs are sometimes flagged by heuristic and machine-learning scanners.

Summary of the v1.3.3 investigation (details in [issue #386](https://github.com/DO0OG/Ari-VoiceCommand/issues/386)):

- At the time of the investigation, the official installer scored 1/57 on VirusTotal.
- We judged the reported 22/67 sample to be a reconstruction of the installer (Inno Setup) loader as it appears in memory, not a separate file inside the installer. The original sample was not available for a direct comparison.

Detection results vary by time and product. This document does not mean you should ignore antivirus warnings. False-positive review requests and per-release checks are tracked in [issue #390](https://github.com/DO0OG/Ari-VoiceCommand/issues/390).

## How to report

- For a suspicious detection, open a GitHub issue and include the file name and version, where you downloaded it, the SHA-256, a link to the scan result, and the detection name.
- For a security vulnerability, do not post details in a public issue; use "Report a vulnerability" (private report) in the repository's Security tab.

</details>

<details>
<summary>日本語</summary>

# リリースファイルの確認とウイルス対策ソフトの検出について

ダウンロードしたインストーラーの確認方法と、ウイルス対策ソフトの検出についての案内です。

## 公式の配布先

公式ファイルは [GitHub Releases](https://github.com/DO0OG/Ari-VoiceCommand/releases) でのみ配布しています。リリースアセットは次のとおりです。

- `Ari-Setup-<version>.exe`
- `update.json`(プレリリース版は `update-beta.json`)
- `SHA256SUMS.txt`

## SHA-256 によるファイル確認

`SHA256SUMS.txt` は `<小文字16進の sha256>  Ari-Setup-<version>.exe` の1行です。2つのファイルを同じフォルダーに置き、PowerShell で実行してください。`Get-FileHash` は大文字で出力しますが、`-eq` は大文字と小文字を区別しないため、そのまま比較できます。

```powershell
$f = 'Ari-Setup-<version>.exe'
$expected = ((Get-Content .\SHA256SUMS.txt | Where-Object { $_ -like "*  $f" }) -split '\s+')[0]
if ((Get-FileHash .\$f -Algorithm SHA256).Hash -eq $expected) { '一致' } else { '不一致' }
```

`不一致` と表示された場合はインストールせず、ファイルをダウンロードし直してください。

## ビルド由来の証明

v1.3.3 の次のリリースから、リリースアセット(インストーラー、更新マニフェスト、`SHA256SUMS.txt`)に GitHub のビルド由来の証明(attestation)が付きます。v1.3.3 までのリリースにはありません。[GitHub CLI](https://cli.github.com/) で確認します。

```powershell
gh attestation verify .\Ari-Setup-<version>.exe --repo DO0OG/Ari-VoiceCommand
```

この証明は、ファイルがこのリポジトリの公開ワークフローのどのコミットでビルドされたかを示します。

## これらの確認が保証しないこと

チェックサムとビルド由来の証明は、ファイルが公式リリースと同じであり、公開ワークフローで作られたことを示すだけで、ビルド環境や依存関係全体が安全であることの保証ではありません。Ari は独立したセキュリティ監査を受けていません。

## コード署名

インストーラーと `Ari.exe` にはまだ Authenticode 署名がありません。そのため Windows SmartScreen やウイルス対策ソフトが警告を表示することがあります。署名の導入を計画しており、状況は [issue #389](https://github.com/DO0OG/Ari-VoiceCommand/issues/389) で確認できます。

## ウイルス対策ソフトの検出

`Ari.exe` は Nuitka でコンパイルした Python プログラムで、インストーラーは Inno Setup で作成しています。署名のないインストーラーやコンパイルされた Python プログラムは、ヒューリスティックや機械学習ベースの検査で検出されることがあります。

v1.3.3 の調査の要約です(詳細は [issue #386](https://github.com/DO0OG/Ari-VoiceCommand/issues/386))。

- 調査時点で、公式インストーラーは VirusTotal で 1/57 でした。
- 報告のあった 22/67 のサンプルは、インストーラーに別途含まれるファイルではなく、インストーラー(Inno Setup)のローダーがメモリ上に展開された状態を復元したものと判断しました。ただし、元のサンプルを入手して照合したわけではありません。

検出結果は時期や製品によって異なります。この文書はウイルス対策ソフトの警告を無視してよいという意味ではありません。誤検出の審査依頼とリリースごとの点検は [issue #390](https://github.com/DO0OG/Ari-VoiceCommand/issues/390) で進めます。

## 報告方法

- 疑わしい検出結果は GitHub の issue で知らせてください。ファイル名とバージョン、入手した場所、SHA-256、検査サービスの結果へのリンク、検出名を併記してください。
- セキュリティ上の脆弱性は、公開 issue に詳細を書かず、リポジトリの Security タブの "Report a vulnerability"(非公開の報告)を利用してください。

</details>
