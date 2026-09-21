"""Small, hand-written multilingual seed families for the Phase 0 benchmark.

Each tuple is ``(Korean, English, Japanese)``.  A family is the unit of
splitting; translations and generated STT-noise variants stay together so a
test example cannot be a paraphrase of a training example under another
language.
"""

from __future__ import annotations

from typing import Iterable


LanguageText = tuple[str, str, str]


# At least four distinct paraphrase families per built-in candidate.  The
# examples are deliberately short and concrete because this is a routing seed,
# not a claim of production language coverage.  Candidates that are reached
# most often by voice carry extra families covering dropped particles, casual
# endings and swapped app names.
TOOL_FAMILY_TEXTS: dict[str, tuple[LanguageText, ...]] = {
    "get_weather": (
        ("오늘 날씨 알려줘", "Tell me today's weather", "今日の天気を教えて"),
        ("밖에 비 와?", "Is it raining outside?", "外は雨？"),
        ("이번 주말 날씨 확인해줘", "Check the weekend weather", "週末の天気を確認して"),
        ("지금 기온이 몇 도야", "What is the temperature now?", "今の気温は何度？"),
        ("날씨 어때", "How is the weather", "天気どう"),
        ("오늘 추워?", "Is it cold today?", "今日寒い？"),
        ("내일 비 오려나", "Will it rain tomorrow", "明日雨降るかな"),
        ("바깥 날씨 좀 알려줄래", "Could you tell me the weather outside", "外の天気を教えてくれる"),
    ),
    "get_current_time": (
        ("지금 몇 시야", "What time is it now?", "今何時？"),
        ("현재 시간을 알려줘", "Tell me the current time", "現在時刻を教えて"),
        ("시계 좀 확인해줘", "Check the clock for me", "時計を確認して"),
        ("서울 시간으로 몇 시인지 말해줘", "What time is it in Seoul?", "ソウルは今何時？"),
        ("몇 시야", "What time", "何時"),
        ("시간 좀 알려줘", "Give me the time", "時間を教えて"),
        ("지금 시각 알려줘", "Tell me the time right now", "今の時刻を教えて"),
        ("몇 시인지 말해줄래", "Could you tell me what time it is", "何時か言ってくれる"),
    ),
    "web_search": (
        ("인터넷에서 고양이 사료를 찾아줘", "Search the web for cat food", "ネットで猫用フードを検索して"),
        ("이 주제 좀 검색해줘", "Look this topic up online", "この話題をネットで調べて"),
        ("최신 노트북 가격을 검색해줘", "Search for current laptop prices", "最新のノートパソコン価格を検索して"),
        ("브라우저로 관련 정보를 찾아봐", "Find information about it online", "ブラウザで関連情報を探して"),
        ("이거 검색해", "Search this", "これ検索して"),
        ("구글에 물어봐줘", "Ask Google about it", "Googleで調べて"),
        ("파이썬 강의 좀 찾아봐", "Look up Python lectures", "Python講座を探して"),
        ("인터넷에 이런 거 있는지 봐줘", "See whether this exists online", "ネットにこういうのがあるか見て"),
    ),
    "web_fetch": (
        ("이 URL 내용을 가져와줘", "Fetch the contents of this URL", "このURLの内容を取得して"),
        ("웹 페이지를 읽어줘", "Read this web page", "このウェブページを読んで"),
        ("링크를 열고 본문을 가져와", "Open the link and fetch the article", "リンクを開いて本文を取得して"),
        ("주소의 내용을 확인해줘", "Retrieve the content at this address", "このアドレスの内容を確認して"),
    ),
    "list_scheduled_tasks": (
        ("예약된 작업 목록 보여줘", "Show my scheduled tasks", "予約タスクの一覧を見せて"),
        ("스케줄 뭐가 등록됐는지 확인해줘", "List what is scheduled", "何が予約されているか確認して"),
        ("등록한 예약 작업을 알려줘", "Tell me my scheduled jobs", "登録した予約タスクを教えて"),
        ("예약 목록을 조회해", "Display the schedule list", "予約一覧を表示して"),
    ),
    "get_calendar_events": (
        ("오늘 일정 확인해줘", "Check today's calendar events", "今日のカレンダー予定を確認して"),
        ("이번 주 일정 보여줘", "Show my events for this week", "今週の予定を見せて"),
        ("캘린더에서 다음 약속을 찾아줘", "Find my next calendar appointment", "カレンダーから次の予定を探して"),
        ("내 회의 일정 알려줘", "Tell me my meeting schedule", "会議の予定を教えて"),
    ),
    "read_emails": (
        ("새 이메일 읽어줘", "Read my new emails", "新着メールを読んで"),
        ("받은 편지함 확인해줘", "Check my inbox", "受信トレイを確認して"),
        ("최근 메일 몇 개 보여줘", "Show me the latest emails", "最近のメールをいくつか見せて"),
        ("중요한 메일을 찾아 읽어줘", "Find and read the important emails", "重要なメールを探して読んで"),
    ),
    "read_file": (
        ("메모 파일 내용을 읽어줘", "Read the contents of the notes file", "メモファイルの内容を読んで"),
        ("이 파일을 열어서 보여줘", "Open and show this file", "このファイルを開いて見せて"),
        ("설정 파일을 읽어 확인해줘", "Read the config file", "設定ファイルを読んで"),
        ("문서 파일 내용을 알려줘", "Tell me what is in the document", "文書ファイルの内容を教えて"),
    ),
    "write_file": (
        ("새 파일에 이 내용을 저장해줘", "Write this content to a new file", "この内容を新しいファイルに書いて"),
        ("문서 파일을 만들어줘", "Create a document file", "文書ファイルを作って"),
        ("텍스트를 파일로 저장해", "Save this text to a file", "このテキストをファイルに保存して"),
        ("파일에 내용을 추가해줘", "Append this content to the file", "ファイルに内容を追加して"),
    ),
    "edit_file": (
        ("파일 안의 오타를 고쳐줘", "Fix the typo in the file", "ファイル内の誤字を直して"),
        ("이 문서의 문장을 바꿔줘", "Replace the sentence in this document", "この文書の文を置き換えて"),
        ("설정 파일에서 값을 수정해", "Change the value in the config file", "設定ファイルの値を変更して"),
        ("파일의 특정 문자열을 교체해줘", "Replace a string in the file", "ファイル内の文字列を置換して"),
    ),
    "list_directory": (
        ("다운로드 폴더 목록을 보여줘", "List the Downloads folder", "ダウンロードフォルダーを一覧表示して"),
        ("이 폴더 안에 뭐가 있는지 알려줘", "Show what is in this folder", "このフォルダーの中身を見せて"),
        ("현재 디렉터리 파일을 나열해", "List the files in the current directory", "現在のディレクトリのファイルを一覧にして"),
        ("폴더 내용을 확인해줘", "Check the directory contents", "フォルダーの内容を確認して"),
    ),
    "search_in_files": (
        ("프로젝트 파일에서 TODO를 찾아줘", "Search the project files for TODO", "プロジェクトのファイルからTODOを探して"),
        ("폴더 안에서 이 문자열을 검색해", "Search this folder for the string", "フォルダー内でこの文字列を検索して"),
        ("파이썬 파일에서 오류 문구를 찾아줘", "Find the error message in the Python files", "Pythonファイルからエラーメッセージを探して"),
        ("파일들에서 이름을 검색해줘", "Search the files for this name", "ファイルからこの名前を検索して"),
    ),
    "move_file": (
        ("파일을 다른 폴더로 옮겨줘", "Move the file to another folder", "ファイルを別のフォルダーに移して"),
        ("이 문서를 바탕화면으로 이동해", "Move this document to the desktop", "この文書をデスクトップへ移動して"),
        ("파일 이름을 바꿔줘", "Rename the file", "ファイル名を変更して"),
        ("폴더 사이에서 파일을 옮겨줘", "Move the file between folders", "フォルダー間でファイルを移動して"),
    ),
    "delete_file": (
        ("이 임시 파일을 삭제해줘", "Delete this temporary file", "この一時ファイルを削除して"),
        ("휴지통 없이 파일을 영구 삭제해줘", "Permanently delete the file without the recycle bin", "ゴミ箱を使わずファイルを完全に削除して"),
        ("오래된 문서를 삭제해", "Delete the old document", "古い文書を削除して"),
        ("이 폴더의 파일을 지워줘", "Delete the files in this folder", "このフォルダーのファイルを削除して"),
    ),
    "analyze_screenshot": (
        ("현재 화면을 보고 설명해줘", "Analyze what is on my screen", "今の画面を見て説明して"),
        ("스크린샷 속 오류를 분석해줘", "Analyze the error in the screenshot", "スクリーンショットのエラーを分析して"),
        ("화면에 보이는 내용을 읽어줘", "Read what is shown on the screen", "画面に表示された内容を読んで"),
        ("현재 화면을 분석해봐", "Inspect the current screen", "現在の画面を分析して"),
    ),
    "analyze_image_file": (
        ("이 이미지 파일을 분석해줘", "Analyze this image file", "この画像ファイルを分析して"),
        ("사진 속 내용을 설명해줘", "Describe what is in the picture", "写真の内容を説明して"),
        ("그림 파일을 보고 알려줘", "Look at the image and tell me about it", "画像を見て内容を教えて"),
        ("이미지에 있는 글자를 읽어줘", "Read the text in the image", "画像内の文字を読んで"),
    ),
    "launch_app": (
        ("크롬을 열어줘", "Open Chrome", "Chromeを開いて"),
        ("디스코드 좀 켜줘", "Launch Discord", "Discordを起動して"),
        ("계산기가 필요하니 사용할 수 있게 준비해줘", "I need the calculator; make it available please", "電卓を使いたいので準備をお願い"),
        ("메모장이 아직 안 켜졌네, 지금 띄워줘", "Notepad is not running yet; please bring it up", "メモ帳がまだ動いていないよ。使えるようにして"),
        ("크롬 열어줘", "Chrome, open it", "Chrome開いて"),
        ("네이버 웨일 띄워줘", "Bring up Naver Whale", "Naver Whaleを立ち上げて"),
        ("엑셀 실행해", "Run Excel", "Excelを実行して"),
        ("스팀 좀 실행시켜줘", "Please start Steam", "Steamを起動してくれる"),
    ),
    "close_app": (
        ("크롬을 닫아줘", "Close Chrome", "Chromeを閉じて"),
        ("디스코드 종료해", "Quit Discord", "Discordを終了して"),
        ("계산기는 이제 쓸 일이 없으니 종료해", "I am done using the calculator; exit it please", "電卓はもう使わないので終了をお願い"),
        ("메모장을 더 이상 실행된 상태로 두지 마", "Do not leave Notepad running", "メモ帳を動かしたままにしないで"),
        ("크롬 닫아", "Chrome, close it", "Chrome閉じて"),
        ("네이버 웨일 좀 닫아줘", "Please close Naver Whale", "Naver Whaleを閉じて"),
        ("엑셀 꺼줘", "Turn Excel off", "Excelを閉じて"),
        ("스팀 종료시켜줘", "Shut Steam down", "Steamを終了させて"),
    ),
    "get_running_apps": (
        ("실행 중인 앱 목록을 알려줘", "List the running applications", "起動中のアプリ一覧を教えて"),
        ("지금 켜진 프로그램을 보여줘", "Show the programs that are open", "今開いているプログラムを見せて"),
        ("실행 중인 프로세스를 확인해", "Check the running processes", "実行中のプロセスを確認して"),
        ("어떤 앱이 실행 중인지 알려줘", "Tell me which apps are running", "どのアプリが起動中か教えて"),
    ),
    "focus_window": (
        ("크롬 창으로 포커스해줘", "Focus the Chrome window", "Chromeのウィンドウにフォーカスして"),
        ("디스코드 창을 앞으로 가져와", "Bring the Discord window to the front", "Discordのウィンドウを前面に出して"),
        ("메모장 창을 활성화해", "Activate the Notepad window", "メモ帳のウィンドウをアクティブにして"),
        ("이 제목의 창에 포커스를 맞춰줘", "Focus the window with this title", "このタイトルのウィンドウにフォーカスして"),
        ("엑셀 창 띄워줘", "Bring the Excel window up", "Excelのウィンドウを出して"),
        ("스팀 창 앞으로 꺼내", "Pull the Steam window to the front", "Steamのウィンドウを前面に出して"),
        ("그 창 다시 보여줘", "Show that window again", "そのウィンドウをもう一度見せて"),
        ("네이버 웨일 창 선택해", "Select the Naver Whale window", "Naver Whaleのウィンドウを選んで"),
    ),
    "take_screenshot": (
        ("화면 캡처를 저장해줘", "Take and save a screenshot", "画面をキャプチャして保存して"),
        ("지금 화면을 스크린샷으로 찍어", "Capture the current screen", "今の画面をスクリーンショットして"),
        ("스크린샷 파일을 만들어줘", "Create a screenshot file", "スクリーンショットファイルを作って"),
        ("화면을 이미지로 저장해", "Save the screen as an image", "画面を画像として保存して"),
        ("화면 캡처해", "Capture the screen", "画面をキャプチャして"),
        ("스크린샷 찍어줘", "Take a screenshot", "スクリーンショット撮って"),
        ("지금 화면 좀 찍어", "Snap the screen now", "今の画面を撮って"),
        ("화면 그대로 저장해줘", "Save the screen as is", "画面をそのまま保存して"),
    ),
    "get_clipboard": (
        ("클립보드 내용을 보여줘", "Show the clipboard contents", "クリップボードの内容を見せて"),
        ("방금 복사한 내용을 읽어줘", "Read what I just copied", "さっきコピーした内容を読んで"),
        ("현재 클립보드를 확인해", "Check the current clipboard", "現在のクリップボードを確認して"),
        ("클립보드 텍스트를 가져와", "Get the clipboard text", "クリップボードのテキストを取得して"),
    ),
    "set_clipboard": (
        ("이 문장을 클립보드에 복사해줘", "Copy this sentence to the clipboard", "この文をクリップボードにコピーして"),
        ("클립보드에 텍스트를 넣어", "Put this text on the clipboard", "このテキストをクリップボードに入れて"),
        ("이 내용을 복사해줘", "Copy this content", "この内容をコピーして"),
        ("클립보드 값을 바꿔줘", "Replace the clipboard value", "クリップボードの内容を置き換えて"),
    ),
    "get_screen_status": (
        ("현재 화면 상태를 확인해줘", "Check the current screen status", "現在の画面状態を確認して"),
        ("전체 화면인지 알려줘", "Tell me whether this is fullscreen", "全画面表示か教えて"),
        ("작업 표시줄 위치를 확인해", "Check the taskbar position", "タスクバーの位置を確認して"),
        ("화면 환경을 점검해줘", "Inspect the display state", "画面の状態を調べて"),
    ),
    "execute_python_code": (
        ("파이썬 코드로 계산해줘", "Run this Python code", "このPythonコードを実行して"),
        ("파이썬 스크립트를 실행해", "Execute the Python script", "Pythonスクリプトを実行して"),
        ("코드로 파일을 처리해줘", "Process it with Python code", "コードで処理して"),
        ("파이썬을 사용해서 자동화해", "Automate this using Python", "Pythonを使って自動化して"),
    ),
    "execute_shell_command": (
        ("명령 프롬프트 명령을 실행해줘", "Run this shell command", "このシェルコマンドを実行して"),
        ("터미널에서 이 명령을 실행해", "Execute this command in the terminal", "ターミナルでこのコマンドを実行して"),
        ("CMD 명령어를 실행해줘", "Execute a CMD command", "CMDコマンドを実行して"),
        ("셸 명령으로 처리해", "Handle this with a shell command", "シェルコマンドで処理して"),
    ),
    "run_agent_task": (
        ("여러 단계 작업을 대신 처리해줘", "Handle this multi-step task for me", "複数手順の作業を代わりに処理して"),
        ("복잡한 목표를 끝까지 수행해", "Carry out this complex goal", "この複雑な目標を最後まで実行して"),
        ("자료를 찾아 정리해서 보고해줘", "Find the material, organize it, and report back", "資料を探して整理し報告して"),
        ("이 일을 알아서 진행해줘", "Take care of this task autonomously", "この仕事を自律的に進めて"),
    ),
    "delegate_to_subagent": (
        ("이 작업을 다른 에이전트에게 맡겨줘", "Delegate this task to another agent", "この作業を別のエージェントに任せて"),
        ("하위 에이전트에게 조사를 부탁해", "Ask a subagent to investigate", "サブエージェントに調査を頼んで"),
        ("이 목표를 전문 에이전트에게 넘겨", "Pass this goal to a specialist agent", "この目標を専門エージェントに渡して"),
        ("다른 에이전트가 처리하도록 위임해줘", "Have another agent handle it", "別のエージェントに処理を委任して"),
    ),
    "api_call": (
        ("외부 서비스 API를 호출해줘", "Call the external service API", "外部サービスのAPIを呼び出して"),
        ("이 API 작업을 실행해", "Perform this API operation", "このAPI操作を実行して"),
        ("서비스에 API 요청을 보내줘", "Send an API request to the service", "サービスにAPIリクエストを送って"),
        ("연동된 API를 사용해 데이터를 가져와", "Use the connected API to get the data", "接続されたAPIでデータを取得して"),
    ),
    "create_calendar_event": (
        ("내일 회의 일정을 캘린더에 추가해줘", "Add tomorrow's meeting to my calendar", "明日の会議をカレンダーに追加して"),
        ("금요일에 약속을 만들어줘", "Create an appointment for Friday", "金曜日に予定を作って"),
        ("캘린더에 새 이벤트를 등록해", "Create a new calendar event", "新しいカレンダー予定を登録して"),
        ("다음 주 일정에 미팅을 넣어줘", "Put a meeting on next week's calendar", "来週のカレンダーに会議を入れて"),
    ),
    "send_email": (
        ("이메일을 보내줘", "Send an email", "メールを送って"),
        ("팀에 회의 자료를 메일로 보내", "Email the meeting notes to the team", "チームに会議資料をメールで送って"),
        ("이 주소로 메시지를 보내줘", "Send a message to this email address", "このアドレスにメールを送って"),
        ("메일을 작성해서 보내", "Compose and send the email", "メールを作成して送って"),
    ),
    "generate_image": (
        ("고양이 그림을 만들어줘", "Generate an image of a cat", "猫の画像を生成して"),
        ("이 설명으로 이미지를 생성해", "Create an image from this description", "この説明で画像を生成して"),
        ("풍경 일러스트를 그려줘", "Make a landscape illustration", "風景のイラストを作って"),
        ("새 이미지를 만들어줘", "Generate a new image", "新しい画像を作って"),
    ),
    "set_timer": (
        ("5분 타이머를 설정해줘", "Set a five minute timer", "5分のタイマーを設定して"),
        ("10초 뒤에 알림해줘", "Set an alert for ten seconds", "10秒後に通知して"),
        ("한 시간 타이머 시작해", "Start a one hour timer", "1時間のタイマーを開始して"),
        ("요리 타이머를 20분으로 맞춰줘", "Set the cooking timer for twenty minutes", "料理タイマーを20分にして"),
    ),
    "cancel_timer": (
        ("타이머를 취소해줘", "Cancel the timer", "タイマーをキャンセルして"),
        ("진행 중인 알림을 멈춰", "Stop the active timer", "動いているタイマーを止めて"),
        ("최근 타이머를 지워줘", "Cancel the most recent timer", "最近のタイマーを取り消して"),
        ("요리 타이머를 취소해", "Cancel the cooking timer", "料理タイマーをキャンセルして"),
    ),
    "schedule_task": (
        ("30분 뒤에 컴퓨터를 종료하도록 예약해줘", "Schedule the computer to shut down in thirty minutes", "30分後にコンピューターを終了するよう予約して"),
        ("내일 아침에 파일을 저장하도록 예약해", "Schedule saving the file tomorrow morning", "明日の朝にファイルを保存するよう予約して"),
        ("오후 3시에 이 작업을 실행해줘", "Schedule this task for 3 PM", "午後3時にこの作業を実行するよう予約して"),
        ("나중에 이 목표를 실행하도록 설정해", "Schedule this goal to run later", "後でこの目標を実行するよう設定して"),
    ),
    "cancel_scheduled_task": (
        ("예약된 작업을 취소해줘", "Cancel the scheduled task", "予約タスクをキャンセルして"),
        ("등록한 예약 하나를 지워", "Remove one scheduled job", "登録した予約を一つ削除して"),
        ("스케줄 ID 작업을 취소해", "Cancel the task with this schedule ID", "このスケジュールIDのタスクを取り消して"),
        ("나중에 실행할 작업을 취소해줘", "Cancel the task that will run later", "後で実行するタスクをキャンセルして"),
    ),
}


HARD_NEGATIVE_FAMILIES: tuple[tuple[str, str, LanguageText], ...] = (
    ("web_search", "launch-word-search", ("크롬이 자꾸 꺼지는 이유를 검색해줘", "Search why Chrome keeps closing", "Chromeが何度も終了する理由を検索して")),
    ("unknown_or_complex", "web-word-open", ("크롬을 열어서 검색해줘", "Open Chrome and search", "Chromeを開いて検索して")),
    ("unknown_or_complex", "web-word-complex", ("크롬 문제를 전부 확인해서 고쳐줘", "Check and fix all the Chrome problems", "Chromeの問題を全部確認して直して")),
    ("search_in_files", "search-word-file", ("파일에서 TODO를 찾아서 보여줘", "Find TODO in the file and show it", "ファイルからTODOを探して見せて")),
    ("read_file", "read-word-content", ("파일 내용을 그대로 읽어줘", "Read the file contents verbatim", "ファイルの内容をそのまま読んで")),
    ("edit_file", "edit-word-save", ("기존 파일의 오타를 고쳐서 저장해줘", "Fix the typo in the existing file and save it", "既存ファイルの誤字を直して保存して")),
    ("write_file", "write-word-change", ("새 문서를 만들어서 내용을 써줘", "Create a new document and write the content", "新しい文書を作って内容を書いて")),
    ("unknown_or_complex", "calendar-create-word", ("캘린더에 회의를 추가하고 기존 일정을 보여줘", "Add a meeting and show the existing calendar events", "会議を追加して既存の予定を見せて")),
    ("unknown_or_complex", "calendar-read-word", ("내일 일정이 있는지 확인하고 새 약속도 만들어줘", "Check tomorrow's events and create an appointment", "明日の予定を確認して新しい約束も作って")),
    ("unknown_or_complex", "screen-analyze-word", ("스크린샷을 찍고 화면 오류를 분석해줘", "Take a screenshot and analyze the screen error", "スクリーンショットを撮って画面のエラーを分析して")),
    ("take_screenshot", "screen-save-word", ("화면을 분석하지 말고 캡처 파일만 저장해줘", "Save only a screen capture without analyzing it", "分析せず画面キャプチャだけ保存して")),
    ("set_clipboard", "clipboard-copy-word", ("클립보드 내용을 읽지 말고 이 문장을 복사해줘", "Do not read the clipboard; copy this sentence", "クリップボードを読まずこの文をコピーして")),
    ("get_clipboard", "clipboard-read-word", ("복사된 클립보드 내용을 확인해줘", "Check the copied clipboard contents", "コピーしたクリップボードの内容を確認して")),
    ("schedule_task", "timer-schedule-word", ("타이머가 아니라 내일 작업을 예약해줘", "Schedule a task for tomorrow, not a timer", "タイマーではなく明日の作業を予約して")),
    ("set_timer", "schedule-timer-word", ("작업 예약 말고 5분 타이머를 맞춰줘", "Set a five minute timer instead of scheduling a task", "作業予約ではなく5分のタイマーを設定して")),
    ("unknown_or_complex", "shell-agent-word", ("터미널 명령이 아니라 여러 단계 작업을 맡겨줘", "Delegate the multi-step task instead of running a shell command", "シェルコマンドではなく複数手順の作業を任せて")),
    ("execute_shell_command", "agent-shell-word", ("에이전트 말고 이 터미널 명령만 실행해줘", "Run only this terminal command, not an agent task", "エージェントではなくこのターミナルコマンドだけ実行して")),
    ("web_search", "weather-search-word", ("날씨를 알려주는 방법을 인터넷에서 검색해줘", "Search the web for how weather forecasts work", "天気予報の仕組みをネットで検索して")),
    ("get_weather", "weather-direct-word", ("검색하지 말고 지금 날씨만 알려줘", "Do not search; just tell me the current weather", "検索せず今の天気だけ教えて")),
)


UNKNOWN_FAMILIES: dict[str, tuple[LanguageText, ...]] = {
    "compound": (
        ("유튜브를 켜고 재즈를 검색해서 재생해줘", "Open YouTube, search for jazz, and play it", "YouTubeを開いてジャズを検索して再生して"),
        ("크롬을 열고 메일을 확인한 뒤 요약해줘", "Open Chrome, check my email, and summarize it", "Chromeを開いてメールを確認し要約して"),
        ("파일을 찾아서 수정하고 동료에게 보내줘", "Find the file, edit it, and send it to my colleague", "ファイルを探して編集し同僚に送って"),
        ("화면을 캡처하고 오류 원인을 분석해서 고쳐줘", "Capture the screen, diagnose the error, and fix it", "画面をキャプチャしてエラーを分析し直して"),
        ("날씨를 보고 일정에 맞춰 알림을 설정해줘", "Check the weather and set an alert based on my schedule", "天気を確認して予定に合わせて通知を設定して"),
        ("폴더를 정리하고 중복 파일을 찾아 삭제해줘", "Organize the folder and find and delete duplicates", "フォルダーを整理して重複ファイルを探し削除して"),
    ),
    "conversation": (
        ("오늘 기분은 어때?", "How are you feeling today?", "今日はどんな気分？"),
        ("재미있는 이야기 해줘", "Tell me something interesting", "面白い話をして"),
        ("나랑 잠깐 이야기할래", "Will you chat with me for a moment?", "少し話してくれる？"),
        ("고마워", "Thank you", "ありがとう"),
        ("오늘 하루가 힘들었어", "Today was a difficult day", "今日は大変な一日だった"),
    ),
    "knowledge": (
        ("블랙홀은 어떻게 만들어져?", "How are black holes formed?", "ブラックホールはどうやってできるの？"),
        ("파이썬 데코레이터가 뭐야?", "What is a Python decorator?", "Pythonのデコレーターって何？"),
        ("이 문장을 영어로 번역해줘", "Translate this sentence into English", "この文を英語に翻訳して"),
        ("태양계 행성을 설명해줘", "Explain the planets in the solar system", "太陽系の惑星を説明して"),
        ("이 코드의 원리를 자세히 알려줘", "Explain how this code works in detail", "このコードの仕組みを詳しく教えて"),
    ),
    "ambiguous": (
        ("그거 좀 처리해줘", "Please handle that", "それを処理して"),
        ("아까 말한 걸 해줘", "Do the thing I mentioned earlier", "さっき言ったことをやって"),
        ("이것 좀 정리해줘", "Please sort this out", "これを整理して"),
        ("적당히 해줘", "Just take care of it", "適当にやって"),
        ("열어줘", "Open it", "開いて"),
    ),
}


def _family(label: str, index: int, texts: LanguageText, bucket: str = "single_action") -> dict:
    return {
        "family_id": f"{label}.{bucket}.{index:02d}",
        "label": label,
        "bucket": bucket,
        "texts": {"ko": texts[0], "en": texts[1], "ja": texts[2]},
    }


def seed_families() -> list[dict]:
    """Return all hand-written family records in stable order."""

    families: list[dict] = []
    for label in sorted(TOOL_FAMILY_TEXTS):
        for index, texts in enumerate(TOOL_FAMILY_TEXTS[label], start=1):
            family = _family(label, index, texts)
            # App names are slots in one request template, and dropping the
            # object particle does not change the template either.  Keep those
            # variants together so a slot swap cannot leak between train and
            # test -- and so the spoken short form trains next to its parent.
            if label in {"launch_app", "close_app"} and index in {1, 2, 5, 6}:
                family["family_id"] = f"{label}.single.app_slot"
            families.append(family)

    for index, (label, slug, texts) in enumerate(HARD_NEGATIVE_FAMILIES, start=1):
        families.append(_family(label, index, texts, f"hard_negative_{slug}"))

    for bucket in sorted(UNKNOWN_FAMILIES):
        for index, texts in enumerate(UNKNOWN_FAMILIES[bucket], start=1):
            families.append(_family("unknown_or_complex", index, texts, bucket))
    return families


def seed_labels() -> set[str]:
    return {family["label"] for family in seed_families()}


def iter_seed_families() -> Iterable[dict]:
    yield from seed_families()
