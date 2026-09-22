from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any


LANGUAGES = ("ko", "en", "ja")
DATASET_VERSION = "decision-gold-v1"
GOLD_DATA_PATH = Path(__file__).with_name("gold.jsonl")
_ROW_FIELDS = frozenset(
    {
        "id",
        "family_id",
        "template_id",
        "label",
        "text",
        "language",
        "bucket",
        "is_noise",
        "noise_type",
        "split",
        "evaluation_only",
        "dataset_version",
        "review_status",
    }
)


GOLD_FAMILIES: dict[str, tuple[dict[str, Any], ...]] = {
    "adjust_volume": (
        {
            "family": "raise_small",
            "bucket": "normal",
            "texts": {
                "ko": "볼륨을 조금 올려줘",
                "en": "Raise the volume a little",
                "ja": "音量を少し上げて",
            },
        },
        {
            "family": "meeting_level",
            "bucket": "contextual",
            "texts": {
                "ko": "회의가 시작됐으니 소리를 30으로 낮춰줘",
                "en": "The meeting is starting, so lower the volume to thirty",
                "ja": "会議が始まるので音量を30に下げて",
            },
        },
        {
            "family": "unmute_and_raise",
            "bucket": "hard_negative",
            "texts": {
                "ko": "음소거를 풀고 소리를 키워줘",
                "en": "Unmute the computer and turn the sound up",
                "ja": "ミュートを解除して音を上げて",
            },
        },
    ),
    "analyze_image_file": (
        {
            "family": "receipt_text",
            "bucket": "normal",
            "texts": {
                "ko": "이 영수증 사진에서 글자를 읽어줘",
                "en": "Read the text in this receipt photo",
                "ja": "このレシート写真の文字を読んで",
            },
        },
        {
            "family": "chart_description",
            "bucket": "contextual",
            "texts": {
                "ko": "PNG 파일에 있는 도표를 설명해줘",
                "en": "Describe the chart in the PNG file",
                "ja": "PNGファイルにあるグラフを説明して",
            },
        },
        {
            "family": "photo_activity",
            "bucket": "hard_negative",
            "texts": {
                "ko": "사진 속 강아지가 무엇을 하고 있는지 알려줘",
                "en": "Tell me what the dog in the photo is doing",
                "ja": "写真の犬が何をしているか教えて",
            },
        },
    ),
    "analyze_screenshot": (
        {
            "family": "screen_error",
            "bucket": "normal",
            "texts": {
                "ko": "지금 화면에 뜬 오류 메시지를 분석해줘",
                "en": "Analyze the error message showing on my screen",
                "ja": "今の画面に出ているエラーメッセージを分析して",
            },
        },
        {
            "family": "screen_controls",
            "bucket": "contextual",
            "texts": {
                "ko": "스크린샷에서 버튼 위치를 설명해줘",
                "en": "Explain where the buttons are in the screenshot",
                "ja": "スクリーンショットのボタンの位置を説明して",
            },
        },
        {
            "family": "desktop_contents",
            "bucket": "hard_negative",
            "texts": {
                "ko": "현재 바탕화면에 무엇이 보이는지 확인해줘",
                "en": "Check what is visible on the current desktop",
                "ja": "今のデスクトップに何が見えているか確認して",
            },
        },
    ),
    "api_call": (
        {
            "family": "order_cancel_request",
            "bucket": "high_risk",
            "texts": {
                "ko": "결제 서비스 API에 주문 취소 요청을 보내줘",
                "en": "Send an order cancellation request to the payment service API",
                "ja": "決済サービスのAPIに注文キャンセルをリクエストして",
            },
        },
        {
            "family": "crm_update",
            "bucket": "high_risk",
            "texts": {
                "ko": "회사 CRM API를 호출해서 고객 상태를 바꿔줘",
                "en": "Call the company CRM API and change the customer's status",
                "ja": "会社のCRM APIを呼び出して顧客の状態を変更して",
            },
        },
        {
            "family": "exchange_lookup",
            "bucket": "high_risk",
            "texts": {
                "ko": "외부 환율 API를 조회하고 결과를 가져와줘",
                "en": "Query the external exchange-rate API and bring back the result",
                "ja": "外部の為替APIを照会して結果を取得して",
            },
        },
    ),
    "cancel_scheduled_task": (
        {
            "family": "cancel_by_id",
            "bucket": "normal",
            "texts": {
                "ko": "예약 작업 ID 42를 취소해줘",
                "en": "Cancel scheduled task 42",
                "ja": "予約タスクID 42をキャンセルして",
            },
        },
        {
            "family": "cancel_backup",
            "bucket": "contextual",
            "texts": {
                "ko": "내일 실행될 백업 예약을 없애줘",
                "en": "Remove the backup scheduled for tomorrow",
                "ja": "明日実行されるバックアップの予約を取り消して",
            },
        },
        {
            "family": "cancel_report_job",
            "bucket": "hard_negative",
            "texts": {
                "ko": "등록된 작업 중 이메일 보고서 예약을 취소해줘",
                "en": "Cancel the scheduled email report among the registered jobs",
                "ja": "登録済みのタスクからメールレポートの予約をキャンセルして",
            },
        },
    ),
    "cancel_timer": (
        {
            "family": "cancel_countdown",
            "bucket": "normal",
            "texts": {
                "ko": "10분 타이머를 취소해줘",
                "en": "Cancel the ten-minute timer",
                "ja": "10分のタイマーをキャンセルして",
            },
        },
        {
            "family": "cancel_cooking",
            "bucket": "contextual",
            "texts": {
                "ko": "요리 타이머 멈춰줘",
                "en": "Stop the cooking timer",
                "ja": "料理用タイマーを止めて",
            },
        },
        {
            "family": "cancel_recent_timer",
            "bucket": "hard_negative",
            "texts": {
                "ko": "방금 설정한 카운트다운을 지워줘",
                "en": "Delete the countdown I just set",
                "ja": "さっき設定したカウントダウンを消して",
            },
        },
    ),
    "close_app": (
        {
            "family": "close_browser",
            "bucket": "hard_negative",
            "texts": {
                "ko": "크롬 창을 닫아줘",
                "en": "Close the Chrome window",
                "ja": "Chromeのウィンドウを閉じて",
            },
        },
        {
            "family": "quit_chat_app",
            "bucket": "contextual",
            "texts": {
                "ko": "사용 중인 슬랙을 종료해줘",
                "en": "Quit Slack, which I am done using",
                "ja": "使い終わったSlackを終了して",
            },
        },
        {
            "family": "close_game",
            "bucket": "hard_negative",
            "texts": {
                "ko": "게임 끝났으니 스팀을 꺼줘",
                "en": "The game is over, so close Steam",
                "ja": "ゲームが終わったのでSteamを閉じて",
            },
        },
    ),
    "create_calendar_event": (
        {
            "family": "dentist_appointment",
            "bucket": "normal",
            "texts": {
                "ko": "금요일 오후 세 시에 치과 예약을 캘린더에 추가해줘",
                "en": "Add a dentist appointment to the calendar for Friday at three in the afternoon",
                "ja": "金曜日の午後3時に歯医者の予定をカレンダーに追加して",
            },
        },
        {
            "family": "team_meeting",
            "bucket": "contextual",
            "texts": {
                "ko": "다음 주 월요일 오전에 팀 회의 일정을 만들어줘",
                "en": "Create a team meeting on the calendar next Monday morning",
                "ja": "来週月曜の午前にチーム会議の予定を作って",
            },
        },
        {
            "family": "evening_plan",
            "bucket": "hard_negative",
            "texts": {
                "ko": "6월 12일 저녁 약속을 일정으로 등록해줘",
                "en": "Put my evening appointment on June twelfth into the calendar",
                "ja": "6月12日の夜の約束を予定として登録して",
            },
        },
    ),
    "delegate_to_subagent": (
        {
            "family": "hand_off_task",
            "bucket": "high_risk",
            "texts": {
                "ko": "이 작업을 다른 실행 담당에게 맡겨줘",
                "en": "Hand this task to another execution specialist",
                "ja": "この作業を別の実行担当に任せて",
            },
        },
        {
            "family": "delegate_research",
            "bucket": "high_risk",
            "texts": {
                "ko": "복잡한 조사 과정을 하위 담당에게 위임해줘",
                "en": "Delegate the complicated research process to a subordinate worker",
                "ja": "複雑な調査の手順を下位担当に委任して",
            },
        },
        {
            "family": "pass_file_review",
            "bucket": "high_risk",
            "texts": {
                "ko": "파일 검토를 별도 작업자에게 넘겨줘",
                "en": "Pass the file review to a separate worker",
                "ja": "ファイルの確認を別の担当者に引き渡して",
            },
        },
    ),
    "delete_file": (
        {
            "family": "remove_archive",
            "bucket": "high_risk",
            "texts": {
                "ko": "다운로드 폴더의 오래된 압축 파일을 삭제해줘",
                "en": "Delete the old archive files in the Downloads folder",
                "ja": "ダウンロードフォルダーの古い圧縮ファイルを削除して",
            },
        },
        {
            "family": "permanent_document_delete",
            "bucket": "high_risk",
            "texts": {
                "ko": "이 문서를 휴지통으로 보내지 말고 완전히 지워줘",
                "en": "Permanently delete this document without sending it to the recycle bin",
                "ja": "この文書をゴミ箱に入れず完全に削除して",
            },
        },
        {
            "family": "duplicate_photo_delete",
            "bucket": "high_risk",
            "texts": {
                "ko": "중복 사진 세 장을 골라서 삭제해줘",
                "en": "Pick the three duplicate photos and delete them",
                "ja": "重複している写真を3枚選んで削除して",
            },
        },
    ),
    "edit_file": (
        {
            "family": "change_port",
            "bucket": "high_risk",
            "texts": {
                "ko": "설정 파일의 포트 번호를 8080으로 바꿔줘",
                "en": "Change the port number in the configuration file to 8080",
                "ja": "設定ファイルのポート番号を8080に変更して",
            },
        },
        {
            "family": "revise_paragraph",
            "bucket": "high_risk",
            "texts": {
                "ko": "초안에서 두 번째 문단을 수정해줘",
                "en": "Revise the second paragraph in the draft",
                "ja": "下書きの2段落目を修正して",
            },
        },
        {
            "family": "fix_source_typo",
            "bucket": "high_risk",
            "texts": {
                "ko": "코드 파일의 오타를 고쳐서 저장해줘",
                "en": "Fix the typo in the code file and save it",
                "ja": "コードファイルの誤字を直して保存して",
            },
        },
    ),
    "execute_python_code": (
        {
            "family": "batch_rename_python",
            "bucket": "high_risk",
            "texts": {
                "ko": "파이썬으로 이 폴더의 파일명을 일괄 변경해줘",
                "en": "Use Python to rename all the files in this folder",
                "ja": "Pythonでこのフォルダーのファイル名を一括変更して",
            },
        },
        {
            "family": "run_snippet",
            "bucket": "high_risk",
            "texts": {
                "ko": "다음 Python 코드를 실행해서 결과를 보여줘",
                "en": "Run the following Python code and show me the result",
                "ja": "次のPythonコードを実行して結果を見せて",
            },
        },
        {
            "family": "process_csv",
            "bucket": "high_risk",
            "texts": {
                "ko": "파이썬 스크립트로 CSV를 가공해줘",
                "en": "Process the CSV with a Python script",
                "ja": "PythonスクリプトでCSVを加工して",
            },
        },
    ),
    "execute_shell_command": (
        {
            "family": "powershell_directory",
            "bucket": "high_risk",
            "texts": {
                "ko": "PowerShell에서 현재 디렉터리를 출력해줘",
                "en": "Print the current directory in PowerShell",
                "ja": "PowerShellで現在のディレクトリを表示して",
            },
        },
        {
            "family": "terminal_service_status",
            "bucket": "high_risk",
            "texts": {
                "ko": "터미널 명령으로 이 서비스 상태를 확인해줘",
                "en": "Check this service status with a terminal command",
                "ja": "ターミナルコマンドでこのサービスの状態を確認して",
            },
        },
        {
            "family": "compress_logs",
            "bucket": "high_risk",
            "texts": {
                "ko": "셸 명령을 실행해서 로그를 압축해줘",
                "en": "Run a shell command to compress the logs",
                "ja": "シェルコマンドを実行してログを圧縮して",
            },
        },
    ),
    "focus_window": (
        {
            "family": "focus_browser",
            "bucket": "hard_negative",
            "texts": {
                "ko": "이미 열려 있는 크롬 창을 앞으로 가져와줘",
                "en": "Bring the already open Chrome window to the front",
                "ja": "すでに開いているChromeのウィンドウを前面に出して",
            },
        },
        {
            "family": "focus_chat",
            "bucket": "contextual",
            "texts": {
                "ko": "슬랙 창에 포커스를 맞춰줘",
                "en": "Put focus on the Slack window",
                "ja": "Slackのウィンドウにフォーカスして",
            },
        },
        {
            "family": "focus_spreadsheet",
            "bucket": "hard_negative",
            "texts": {
                "ko": "작업 중인 스프레드시트 창을 활성화해줘",
                "en": "Activate the spreadsheet window I am working in",
                "ja": "作業中のスプレッドシートのウィンドウをアクティブにして",
            },
        },
    ),
    "generate_image": (
        {
            "family": "seaside_illustration",
            "bucket": "normal",
            "texts": {
                "ko": "노을 진 바닷가 일러스트를 만들어줘",
                "en": "Create an illustration of a beach at sunset",
                "ja": "夕焼けの海辺のイラストを作って",
            },
        },
        {
            "family": "reading_cat",
            "bucket": "contextual",
            "texts": {
                "ko": "고양이가 책 읽는 장면을 그려줘",
                "en": "Draw a scene of a cat reading a book",
                "ja": "猫が本を読んでいる場面を描いて",
            },
        },
        {
            "family": "minimal_logo",
            "bucket": "hard_negative",
            "texts": {
                "ko": "파란색 미니멀 로고 이미지를 생성해줘",
                "en": "Generate a blue minimal logo image",
                "ja": "青いミニマルなロゴ画像を生成して",
            },
        },
    ),
    "get_calendar_events": (
        {
            "family": "today_schedule",
            "bucket": "normal",
            "texts": {
                "ko": "오늘 오후 일정만 보여줘",
                "en": "Show only my events for this afternoon",
                "ja": "今日の午後の予定だけ見せて",
            },
        },
        {
            "family": "next_meeting",
            "bucket": "contextual",
            "texts": {
                "ko": "이번 달 첫 회의가 언제인지 알려줘",
                "en": "Tell me when the first meeting this month is",
                "ja": "今月最初の会議がいつか教えて",
            },
        },
        {
            "family": "tomorrow_appointment",
            "bucket": "hard_negative",
            "texts": {
                "ko": "캘린더에서 내일 약속을 확인해줘",
                "en": "Check tomorrow's appointment on my calendar",
                "ja": "カレンダーで明日の予定を確認して",
            },
        },
    ),
    "get_clipboard": (
        {
            "family": "show_clipboard",
            "bucket": "normal",
            "texts": {
                "ko": "클립보드에 지금 어떤 글자가 들어 있는지 보여줘",
                "en": "Show me what text is currently in the clipboard",
                "ja": "クリップボードに今どんな文字が入っているか見せて",
            },
        },
        {
            "family": "read_recent_copy",
            "bucket": "contextual",
            "texts": {
                "ko": "조금 전에 복사해둔 내용을 읽어줘",
                "en": "Read the content I just copied",
                "ja": "先ほどコピーした内容を読み上げて",
            },
        },
        {
            "family": "inspect_clipboard_text",
            "bucket": "hard_negative",
            "texts": {
                "ko": "현재 클립보드 텍스트를 확인해줘",
                "en": "Inspect the current clipboard text",
                "ja": "現在のクリップボードのテキストを確認して",
            },
        },
    ),
    "get_current_time": (
        {
            "family": "current_clock",
            "bucket": "normal",
            "texts": {
                "ko": "지금 시각을 알려줘",
                "en": "Give me the time right now",
                "ja": "現在の時刻を知らせて",
            },
        },
        {
            "family": "seoul_time",
            "bucket": "contextual",
            "texts": {
                "ko": "도쿄는 현재 몇 시인지 말해줘",
                "en": "Tell me what time it is in Tokyo right now",
                "ja": "東京は今何時か教えて",
            },
        },
        {
            "family": "check_clock",
            "bucket": "hard_negative",
            "texts": {
                "ko": "시계 확인해서 시간을 알려줘",
                "en": "Check the clock and tell me the time",
                "ja": "時計を確認して時刻を教えて",
            },
        },
    ),
    "get_running_apps": (
        {
            "family": "running_programs",
            "bucket": "normal",
            "texts": {
                "ko": "현재 실행 중인 프로그램 목록을 보여줘",
                "en": "Show the list of programs currently running",
                "ja": "現在実行中のプログラム一覧を見せて",
            },
        },
        {
            "family": "open_apps",
            "bucket": "contextual",
            "texts": {
                "ko": "열려 있는 앱을 모두 확인해줘",
                "en": "Check all the apps that are open",
                "ja": "開いているアプリをすべて確認して",
            },
        },
        {
            "family": "background_apps",
            "bucket": "hard_negative",
            "texts": {
                "ko": "백그라운드에서 돌아가는 앱이 무엇인지 알려줘",
                "en": "Tell me which apps are running in the background",
                "ja": "バックグラウンドで動いているアプリを教えて",
            },
        },
    ),
    "get_screen_status": (
        {
            "family": "taskbar_position",
            "bucket": "normal",
            "texts": {
                "ko": "작업 표시줄이 화면 어디에 있는지 확인해줘",
                "en": "Check where the taskbar is positioned on the screen",
                "ja": "タスクバーが画面のどこにあるか確認して",
            },
        },
        {
            "family": "fullscreen_state",
            "bucket": "contextual",
            "texts": {
                "ko": "지금 전체 화면 모드인지 알려줘",
                "en": "Tell me whether the screen is in full-screen mode",
                "ja": "今フルスクリーンモードかどうか教えて",
            },
        },
        {
            "family": "desktop_layout",
            "bucket": "hard_negative",
            "texts": {
                "ko": "현재 화면 배치 상태를 점검해줘",
                "en": "Check the current screen layout state",
                "ja": "現在の画面レイアウトの状態を点検して",
            },
        },
    ),
    "get_weather": (
        {
            "family": "city_weather",
            "bucket": "normal",
            "texts": {
                "ko": "오늘 부산 날씨 알려줘",
                "en": "Tell me today's weather in Busan",
                "ja": "今日の釜山の天気を教えて",
            },
        },
        {
            "family": "rain_forecast",
            "bucket": "contextual",
            "texts": {
                "ko": "내일 아침 비가 올지 확인해줘",
                "en": "Check whether it will rain tomorrow morning",
                "ja": "明日の朝に雨が降るか確認して",
            },
        },
        {
            "family": "outside_temperature",
            "bucket": "hard_negative",
            "texts": {
                "ko": "지금 밖의 기온이 어떤지 알려줘",
                "en": "Tell me what the temperature is like outside now",
                "ja": "今の外の気温がどのくらいか教えて",
            },
        },
    ),
    "launch_app": (
        {
            "family": "open_browser",
            "bucket": "hard_negative",
            "texts": {
                "ko": "크롬을 새로 열어줘",
                "en": "Open a fresh Chrome window",
                "ja": "Chromeを新しく開いて",
            },
        },
        {
            "family": "start_chat_app",
            "bucket": "contextual",
            "texts": {
                "ko": "디스코드 실행해서 쓸 수 있게 해줘",
                "en": "Launch Discord so I can use it",
                "ja": "Discordを起動して使えるようにして",
            },
        },
        {
            "family": "start_game",
            "bucket": "hard_negative",
            "texts": {
                "ko": "스팀을 띄워줘",
                "en": "Bring the Steam client up",
                "ja": "Steamをそろそろ立ち上げてもらえる",
            },
        },
    ),
    "list_directory": (
        {
            "family": "documents_listing",
            "bucket": "normal",
            "texts": {
                "ko": "문서 폴더 안의 파일 목록을 나열해줘",
                "en": "List the files inside the Documents folder",
                "ja": "ドキュメントフォルダー内のファイル一覧を出して",
            },
        },
        {
            "family": "desktop_items",
            "bucket": "contextual",
            "texts": {
                "ko": "바탕화면에 있는 항목을 보여줘",
                "en": "Show the items on the desktop",
                "ja": "デスクトップにある項目を見せて",
            },
        },
        {
            "family": "recursive_directory",
            "bucket": "hard_negative",
            "texts": {
                "ko": "현재 디렉터리의 하위 폴더까지 확인해줘",
                "en": "Inspect the current directory including its subfolders",
                "ja": "現在のディレクトリをサブフォルダーまで確認して",
            },
        },
    ),
    "list_scheduled_tasks": (
        {
            "family": "all_schedules",
            "bucket": "normal",
            "texts": {
                "ko": "예약된 작업을 전부 보여줘",
                "en": "Show all the scheduled tasks",
                "ja": "予約されているタスクを全部見せて",
            },
        },
        {
            "family": "automatic_jobs",
            "bucket": "contextual",
            "texts": {
                "ko": "자동으로 실행되도록 등록된 작업이 뭐야",
                "en": "What tasks are registered to run automatically",
                "ja": "自動実行するよう登録されたタスクは何？",
            },
        },
        {
            "family": "next_run_time",
            "bucket": "hard_negative",
            "texts": {
                "ko": "스케줄 목록에서 다음 실행 시간을 확인해줘",
                "en": "Check the next run time in the schedule list",
                "ja": "スケジュール一覧で次の実行時刻を確認して",
            },
        },
    ),
    "mcp_call": (
        {
            "family": "document_search_endpoint",
            "bucket": "high_risk",
            "texts": {
                "ko": "MCP 서버의 문서 검색 도구를 호출해줘",
                "en": "Call the document-search capability on the MCP server",
                "ja": "MCPサーバーの文書検索機能を呼び出して",
            },
        },
        {
            "family": "product_lookup_endpoint",
            "bucket": "high_risk",
            "texts": {
                "ko": "지정한 MCP 엔드포인트에 상품 조회 요청을 보내줘",
                "en": "Send a product lookup request to the specified MCP endpoint",
                "ja": "指定したMCPエンドポイントに商品検索のリクエストを送って",
            },
        },
        {
            "family": "json_arguments",
            "bucket": "high_risk",
            "texts": {
                "ko": "MCP 호출에 이 JSON 인자를 전달해줘",
                "en": "Pass this JSON argument to the MCP call",
                "ja": "このJSON引数をMCPの呼び出しに渡して",
            },
        },
    ),
    "move_file": (
        {
            "family": "archive_report",
            "bucket": "normal",
            "texts": {
                "ko": "보고서 파일을 보관 폴더로 옮겨줘",
                "en": "Move the report file to the archive folder",
                "ja": "レポートファイルを保管フォルダーに移して",
            },
        },
        {
            "family": "sort_photos",
            "bucket": "contextual",
            "texts": {
                "ko": "사진을 날짜별 폴더로 이동해줘",
                "en": "Move the photos into folders by date",
                "ja": "写真を日付ごとのフォルダーに移動して",
            },
        },
        {
            "family": "preserve_filename",
            "bucket": "hard_negative",
            "texts": {
                "ko": "이름을 바꾸지 말고 파일을 다른 디렉터리로 옮겨줘",
                "en": "Move the file to another directory without renaming it",
                "ja": "名前を変えずにファイルを別のディレクトリへ移して",
            },
        },
    ),
    "play_youtube": (
        {
            "family": "rain_sounds",
            "bucket": "normal",
            "texts": {
                "ko": "유튜브에서 빗소리 영상을 재생해줘",
                "en": "Play a rain-sounds video on YouTube",
                "ja": "YouTubeで雨音の動画を再生して",
            },
        },
        {
            "family": "artist_song",
            "bucket": "contextual",
            "texts": {
                "ko": "이 가수의 신곡을 유튜브로 찾아서 틀어줘",
                "en": "Find this singer's latest song on YouTube and play it",
                "ja": "この歌手の新曲をYouTubeで探して再生して",
            },
        },
        {
            "family": "stretch_video",
            "bucket": "hard_negative",
            "texts": {
                "ko": "유튜브로 20분짜리 스트레칭 영상을 틀어줘",
                "en": "Play a twenty-minute stretching video on YouTube",
                "ja": "YouTubeで20分のストレッチ動画を流して",
            },
        },
    ),
    "read_emails": (
        {
            "family": "new_inbox",
            "bucket": "normal",
            "texts": {
                "ko": "받은 편지함에서 새 메일을 읽어줘",
                "en": "Read the new messages in my inbox",
                "ja": "受信トレイの新着メールを読んで",
            },
        },
        {
            "family": "work_mail",
            "bucket": "contextual",
            "texts": {
                "ko": "오늘 도착한 업무 메일을 확인해줘",
                "en": "Check the work emails that arrived today",
                "ja": "今日届いた仕事のメールを確認して",
            },
        },
        {
            "family": "attachment_mail",
            "bucket": "hard_negative",
            "texts": {
                "ko": "첨부파일이 있는 이메일 내용을 보여줘",
                "en": "Show me the contents of emails that have attachments",
                "ja": "添付ファイルがあるメールの内容を見せて",
            },
        },
    ),
    "read_file": (
        {
            "family": "read_readme",
            "bucket": "normal",
            "texts": {
                "ko": "README 파일을 열어서 내용을 읽어줘",
                "en": "Open the README file and read its contents",
                "ja": "READMEファイルを開いて内容を読んで",
            },
        },
        {
            "family": "read_json_config",
            "bucket": "contextual",
            "texts": {
                "ko": "이 JSON 설정 파일의 내용을 보여줘",
                "en": "Show me the contents of this JSON configuration file",
                "ja": "このJSON設定ファイルの内容を見せて",
            },
        },
        {
            "family": "read_meeting_notes",
            "bucket": "hard_negative",
            "texts": {
                "ko": "회의록 문서를 읽고 어떤 내용인지 알려줘",
                "en": "Read the meeting-notes document and tell me what it says",
                "ja": "議事録を読んでどんな内容か教えて",
            },
        },
    ),
    "run_agent_task": (
        {
            "family": "compare_files",
            "bucket": "high_risk",
            "texts": {
                "ko": "여러 파일을 비교해서 결과를 정리하는 작업을 맡아줘",
                "en": "Handle a task that compares several files and organizes the results",
                "ja": "複数のファイルを比較して結果を整理する作業を任せて",
            },
        },
        {
            "family": "research_summary",
            "bucket": "high_risk",
            "texts": {
                "ko": "웹 자료를 조사하고 요약문까지 작성해줘",
                "en": "Research web material and write a summary as well",
                "ja": "ウェブ資料を調査して要約まで作成して",
            },
        },
        {
            "family": "project_review_plan",
            "bucket": "high_risk",
            "texts": {
                "ko": "프로젝트 상태를 점검하고 필요한 수정 계획을 세워줘",
                "en": "Review the project status and make a plan for the needed changes",
                "ja": "プロジェクトの状態を確認して必要な修正計画を立てて",
            },
        },
    ),
    "schedule_task": (
        {
            "family": "delayed_backup",
            "bucket": "hard_negative",
            "texts": {
                "ko": "한 시간 뒤에 백업을 실행하도록 예약해줘",
                "en": "Schedule the backup to run in one hour",
                "ja": "1時間後にバックアップを実行するよう予約して",
            },
        },
        {
            "family": "morning_status",
            "bucket": "contextual",
            "texts": {
                "ko": "내일 오전 아홉 시에 컴퓨터 상태를 확인하게 해줘",
                "en": "Have the computer status checked tomorrow at nine in the morning",
                "ja": "明日の午前9時にパソコンの状態を確認するようにして",
            },
        },
        {
            "family": "after_work_report",
            "bucket": "hard_negative",
            "texts": {
                "ko": "퇴근 후에 보고서를 저장하도록 작업을 예약해줘",
                "en": "Schedule a task to save the report after work",
                "ja": "退勤後にレポートを保存するようタスクを予約して",
            },
        },
    ),
    "search_in_files": (
        {
            "family": "todo_source",
            "bucket": "normal",
            "texts": {
                "ko": "소스 코드 전체에서 TODO 주석을 찾아줘",
                "en": "Find TODO comments throughout the source code",
                "ja": "ソースコード全体からTODOコメントを探して",
            },
        },
        {
            "family": "error_phrase",
            "bucket": "contextual",
            "texts": {
                "ko": "프로젝트 파일 중에 이 오류 문구가 있는 곳을 검색해줘",
                "en": "Search the project files for places containing this error message",
                "ja": "プロジェクトファイルからこのエラーメッセージがある場所を検索して",
            },
        },
        {
            "family": "meeting_word",
            "bucket": "hard_negative",
            "texts": {
                "ko": "폴더 안의 문서에서 회의라는 단어를 찾아줘",
                "en": "Find the word meeting in the documents inside the folder",
                "ja": "フォルダー内の文書から会議という単語を探して",
            },
        },
    ),
    "send_email": (
        {
            "family": "delay_notice",
            "bucket": "high_risk",
            "texts": {
                "ko": "팀장에게 지연 사유를 이메일로 보내줘",
                "en": "Send the reason for the delay to my manager by email",
                "ja": "遅延の理由を上司にメールで送って",
            },
        },
        {
            "family": "attach_meeting_material",
            "bucket": "high_risk",
            "texts": {
                "ko": "이 주소로 회의 자료를 첨부해 메일을 보내줘",
                "en": "Email the meeting material as an attachment to this address",
                "ja": "このアドレスに会議資料を添付してメールを送って",
            },
        },
        {
            "family": "weekend_confirmation",
            "bucket": "high_risk",
            "texts": {
                "ko": "친구에게 주말 약속을 확인하는 이메일을 작성해서 보내줘",
                "en": "Write and send an email to my friend confirming our weekend plan",
                "ja": "友達に週末の約束を確認するメールを書いて送って",
            },
        },
    ),
    "set_clipboard": (
        {
            "family": "copy_sentence",
            "bucket": "hard_negative",
            "texts": {
                "ko": "이 문장을 클립보드로 복사해둬",
                "en": "Put this sentence onto the clipboard",
                "ja": "この文章をクリップボードに入れて",
            },
        },
        {
            "family": "copy_address",
            "bucket": "contextual",
            "texts": {
                "ko": "방금 만든 주소를 클립보드에 넣어줘",
                "en": "Put the address I just made into the clipboard",
                "ja": "さっき作ったアドレスをクリップボードに入れて",
            },
        },
        {
            "family": "replace_clipboard",
            "bucket": "hard_negative",
            "texts": {
                "ko": "클립보드 내용을 새 텍스트로 바꿔줘",
                "en": "Replace the clipboard contents with new text",
                "ja": "クリップボードの内容を新しいテキストに置き換えて",
            },
        },
    ),
    "set_timer": (
        {
            "family": "simple_minutes",
            "bucket": "hard_negative",
            "texts": {
                "ko": "25분짜리로 타이머 하나 걸어줘",
                "en": "Set a timer for twenty-five minutes",
                "ja": "25分だけタイマーを仕掛けておいて",
            },
        },
        {
            "family": "cooking_minutes",
            "bucket": "contextual",
            "texts": {
                "ko": "차 끓이는 타이머를 7분으로 맞춰줘",
                "en": "Set a seven-minute timer for brewing tea",
                "ja": "お茶をいれるタイマーを7分に合わせて",
            },
        },
        {
            "family": "named_seconds",
            "bucket": "hard_negative",
            "texts": {
                "ko": "이름을 운동으로 해서 45초 카운트다운을 시작해줘",
                "en": "Start a forty-five-second countdown named workout",
                "ja": "運動という名前で45秒のカウントダウンを始めて",
            },
        },
    ),
    "shutdown_computer": (
        {
            "family": "immediate_shutdown",
            "bucket": "high_risk",
            "texts": {
                "ko": "컴퓨터를 지금 종료해줘",
                "en": "Shut down the computer now",
                "ja": "今すぐパソコンを終了して",
            },
        },
        {
            "family": "after_saving",
            "bucket": "high_risk",
            "texts": {
                "ko": "작업을 저장했으니 PC 전원을 꺼줘",
                "en": "I saved my work, so turn off the PC",
                "ja": "作業を保存したのでPCの電源を切って",
            },
        },
        {
            "family": "leave_work",
            "bucket": "high_risk",
            "texts": {
                "ko": "이제 퇴근하니 컴퓨터를 끄도록 해줘",
                "en": "I am leaving work now, so turn off the computer",
                "ja": "もう帰るのでパソコンを切っておいて",
            },
        },
    ),
    "take_screenshot": (
        {
            "family": "save_screen_image",
            "bucket": "hard_negative",
            "texts": {
                "ko": "현재 화면을 이미지 파일로 캡처해줘",
                "en": "Capture the current screen as an image file",
                "ja": "現在の画面を画像ファイルとしてキャプチャして",
            },
        },
        {
            "family": "full_monitor",
            "bucket": "contextual",
            "texts": {
                "ko": "전체 모니터 화면을 저장해줘",
                "en": "Save the entire monitor screen",
                "ja": "モニター全体の画面を保存して",
            },
        },
        {
            "family": "record_visible_screen",
            "bucket": "hard_negative",
            "texts": {
                "ko": "지금 보이는 화면을 사진으로 남겨줘",
                "en": "Keep a picture of what is visible on the screen now",
                "ja": "今見えている画面を写真として残して",
            },
        },
    ),
    "web_fetch": (
        {
            "family": "link_body",
            "bucket": "normal",
            "texts": {
                "ko": "이 링크의 본문을 가져와줘",
                "en": "Fetch the body of this link",
                "ja": "このリンクの本文を取得して",
            },
        },
        {
            "family": "url_document",
            "bucket": "contextual",
            "texts": {
                "ko": "URL에 있는 문서를 열어 내용을 읽어줘",
                "en": "Open the document at this URL and read its contents",
                "ja": "URLにある文書を開いて内容を読んで",
            },
        },
        {
            "family": "html_content",
            "bucket": "hard_negative",
            "texts": {
                "ko": "페이지 주소에서 HTML 내용을 받아와줘",
                "en": "Retrieve the HTML content from the page address",
                "ja": "ページのアドレスからHTMLの内容を取得して",
            },
        },
    ),
    "web_search": (
        {
            "family": "dinner_ideas",
            "bucket": "normal",
            "texts": {
                "ko": "인터넷에서 저녁 메뉴 추천을 찾아줘",
                "en": "Find dinner recommendations on the internet",
                "ja": "インターネットで夕食のおすすめを探して",
            },
        },
        {
            "family": "product_price",
            "bucket": "contextual",
            "texts": {
                "ko": "온라인으로 이 제품의 최신 가격을 검색해줘",
                "en": "Search online for the latest price of this product",
                "ja": "オンラインでこの製品の最新価格を検索して",
            },
        },
        {
            "family": "python_example",
            "bucket": "hard_negative",
            "texts": {
                "ko": "웹에서 파이썬 비동기 예제를 찾아봐",
                "en": "Look for a Python asynchronous example on the web",
                "ja": "ウェブでPythonの非同期処理の例を探して",
            },
        },
    ),
    "write_file": (
        {
            "family": "new_text_file",
            "bucket": "high_risk",
            "texts": {
                "ko": "새 텍스트 파일에 이 내용을 기록해줘",
                "en": "Write this content into a new text file",
                "ja": "この内容を新しいテキストファイルに書いて",
            },
        },
        {
            "family": "save_csv_result",
            "bucket": "high_risk",
            "texts": {
                "ko": "결과를 CSV 파일로 저장해줘",
                "en": "Save the results as a CSV file",
                "ja": "結果をCSVファイルとして保存して",
            },
        },
        {
            "family": "write_note_path",
            "bucket": "high_risk",
            "texts": {
                "ko": "지정한 경로에 메모를 새로 작성해줘",
                "en": "Write a new note at the specified path",
                "ja": "指定したパスに新しいメモを書いて",
            },
        },
    ),
    "unknown_or_complex": (
        {
            "family": "conversation",
            "bucket": "conversation",
            "texts": {
                "ko": "오늘 좀 지쳤는데 잠깐 이야기해줄래?",
                "en": "I had a tiring day; can you talk with me for a while?",
                "ja": "今日は疲れたので少し話してくれる？",
            },
        },
        {
            "family": "knowledge_question",
            "bucket": "knowledge_question",
            "texts": {
                "ko": "양자 컴퓨팅은 어떻게 작동해?",
                "en": "How does quantum computing work?",
                "ja": "量子コンピューターはどう動くの？",
            },
        },
        {
            "family": "multi_intent",
            "bucket": "multi_intent",
            "texts": {
                "ko": "크롬을 켜고 유튜브에서 재즈를 찾아 재생해줘",
                "en": "Open Chrome, find jazz on YouTube, and play it",
                "ja": "Chromeを開いてYouTubeでジャズを探して再生して",
            },
        },
    ),
}


def _registry_labels() -> tuple[str, ...]:
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from agent.decision.candidates import candidate_names

    return tuple(candidate_names())


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _validate_literal_source() -> None:
    registry = set(_registry_labels())
    source = set(GOLD_FAMILIES)
    if source != registry:
        missing = sorted(registry - source)
        extra = sorted(source - registry)
        raise ValueError(f"gold labels differ from registry: missing={missing}, extra={extra}")
    for label in _registry_labels():
        families = GOLD_FAMILIES[label]
        if len(families) < 3:
            raise ValueError(f"gold label needs three families: {label}")
        seen_families: set[str] = set()
        for family in families:
            name = str(family.get("family", ""))
            if not name or name in seen_families:
                raise ValueError(f"duplicate or empty family: {label}:{name}")
            seen_families.add(name)
            if set(family.get("texts", {})) != set(LANGUAGES):
                raise ValueError(f"family languages differ: {label}:{name}")
            if not str(family.get("bucket", "")):
                raise ValueError(f"family bucket is empty: {label}:{name}")
            if any(not isinstance(family["texts"][language], str) or not family["texts"][language].strip()
                   for language in LANGUAGES):
                raise ValueError(f"family text is empty: {label}:{name}")


def _rows_from_families() -> list[dict[str, Any]]:
    _validate_literal_source()
    rows: list[dict[str, Any]] = []
    for label in _registry_labels():
        for family in GOLD_FAMILIES[label]:
            family_id = f"gold.{label}.{family['family']}"
            for language in LANGUAGES:
                rows.append(
                    {
                        "id": f"gold:{label}:{family['family']}:{language}",
                        "family_id": family_id,
                        "template_id": family_id,
                        "label": label,
                        "text": family["texts"][language],
                        "language": language,
                        "bucket": family["bucket"],
                        "is_noise": False,
                        "noise_type": None,
                        "split": "gold",
                        "evaluation_only": True,
                        "dataset_version": DATASET_VERSION,
                        "review_status": "pending_human_review",
                    }
                )
    return rows


def _validate_rows(rows: list[dict[str, Any]]) -> None:
    registry = set(_registry_labels())
    if not rows:
        raise ValueError("gold dataset is empty")
    if any(set(row) != _ROW_FIELDS for row in rows):
        raise ValueError("gold row fields differ from the required schema")
    if any(not str(row["id"]).startswith("gold:") for row in rows):
        raise ValueError("gold row id has an invalid prefix")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("gold row ids are not unique")
    if set(row["label"] for row in rows) != registry:
        raise ValueError("gold labels differ from registry")
    if any(
        row["split"] != "gold"
        or row["evaluation_only"] is not True
        or row["dataset_version"] != DATASET_VERSION
        or row["review_status"] != "pending_human_review"
        or row["is_noise"] is not False
        or row["noise_type"] is not None
        for row in rows
    ):
        raise ValueError("gold metadata is invalid")
    family_rows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        family_rows.setdefault(str(row["family_id"]), []).append(row)
        if row["template_id"] != row["family_id"]:
            raise ValueError("template and family ids must match")
        if row["language"] not in LANGUAGES or not str(row["text"]).strip():
            raise ValueError("gold row language or text is invalid")
    if any(len(family) != len(LANGUAGES) for family in family_rows.values()):
        raise ValueError("each gold family must have one row per language")
    if len({_normalize(str(row["text"])) for row in rows}) < 300:
        raise ValueError("gold dataset needs at least 300 normalized unique texts")


def build_gold_examples() -> list[dict[str, Any]]:
    if not GOLD_DATA_PATH.is_file():
        raise FileNotFoundError(f"gold dataset is missing: {GOLD_DATA_PATH}")
    rows = [
        json.loads(line)
        for line in GOLD_DATA_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    _validate_rows(rows)
    expected = _rows_from_families()
    if rows != expected:
        raise ValueError("gold.jsonl does not match the literal gold source")
    return rows


def write_gold_dataset(path: str | Path = GOLD_DATA_PATH) -> list[dict[str, Any]]:
    rows = _rows_from_families()
    _validate_rows(rows)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=GOLD_DATA_PATH)
    args = parser.parse_args(argv)
    rows = write_gold_dataset(args.output)
    print(json.dumps({"output": str(args.output), "rows": len(rows),
                      "labels": len({row['label'] for row in rows}),
                      "families": len({row['family_id'] for row in rows})}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
