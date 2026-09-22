"""Deterministic multilingual family generation for the expanded dataset."""

from __future__ import annotations

from itertools import product
from string import Formatter
from typing import Iterable, Mapping

try:
    from .seed_data import LanguageText
except ImportError:  # Direct module execution.
    from seed_data import LanguageText


FamilyRecord = dict[str, object]
SlotValues = Mapping[str, tuple[LanguageText, ...]]

FAST_LABELS: tuple[str, ...] = (
    "get_current_time",
    "get_weather",
    "adjust_volume",
    "set_timer",
    "cancel_timer",
    "launch_app",
    "focus_window",
    "get_running_apps",
    "play_youtube",
    "take_screenshot",
)

HARD_NEGATIVE_PAIRS: tuple[tuple[str, str], ...] = (
    ("launch_app", "focus_window"),
    ("focus_window", "close_app"),
    ("launch_app", "close_app"),
    ("take_screenshot", "analyze_screenshot"),
    ("search_in_files", "web_search"),
    ("read_file", "read_emails"),
    ("schedule_task", "set_timer"),
    ("set_clipboard", "write_file"),
    ("get_weather", "get_calendar_events"),
)


APP_SLOTS: tuple[LanguageText, ...] = (
    ("크롬", "Chrome", "Chrome"),
    ("디스코드", "Discord", "Discord"),
    ("메모장", "Notepad", "メモ帳"),
    ("계산기", "Calculator", "電卓"),
    ("네이버 웨일", "Naver Whale", "Naver Whale"),
    ("엑셀", "Excel", "Excel"),
    ("스팀", "Steam", "Steam"),
    ("VS 코드", "VS Code", "VS Code"),
)

APP_ALIAS_SLOTS: tuple[LanguageText, ...] = (
    ("크롬", "Chrome", "クローム"),
    ("디코", "Discord", "ディスコード"),
    ("메모장", "Notepad", "メモ帳"),
    ("계산기", "Calculator", "電卓"),
    ("웨일", "Naver Whale", "ウェイル"),
    ("엑셀", "Excel", "エクセル"),
    ("스팀", "Steam", "スチーム"),
    ("브코", "VS Code", "VS Code"),
)

WEATHER_SLOTS: tuple[LanguageText, ...] = (
    ("서울", "Seoul", "ソウル"),
    ("부산", "Busan", "釜山"),
    ("도쿄", "Tokyo", "東京"),
    ("뉴욕", "New York", "ニューヨーク"),
    ("런던", "London", "ロンドン"),
    ("집 근처", "near home", "自宅の近く"),
)

TIMEZONE_SLOTS: tuple[LanguageText, ...] = (
    ("서울", "Seoul", "ソウル"),
    ("런던", "London", "ロンドン"),
    ("뉴욕", "New York", "ニューヨーク"),
    ("도쿄", "Tokyo", "東京"),
)

VOLUME_LEVELS: tuple[LanguageText, ...] = (
    ("20", "20", "20"),
    ("40", "40", "40"),
    ("50", "50", "50"),
    ("70", "70", "70"),
    ("최대", "maximum", "最大"),
)

VOLUME_DELTAS: tuple[LanguageText, ...] = (
    ("5", "five", "5"),
    ("10", "ten", "10"),
    ("15", "fifteen", "15"),
    ("20", "twenty", "20"),
)

DURATION_SLOTS: tuple[LanguageText, ...] = (
    ("5분", "five minutes", "5分"),
    ("10분", "ten minutes", "10分"),
    ("15분", "fifteen minutes", "15分"),
    ("30분", "thirty minutes", "30分"),
    ("1시간", "one hour", "1時間"),
    ("20초", "twenty seconds", "20秒"),
)

TIMER_SLOTS: tuple[LanguageText, ...] = (
    ("요리 타이머", "cooking timer", "料理タイマー"),
    ("공부 타이머", "study timer", "勉強タイマー"),
    ("첫 번째 타이머", "the first timer", "最初のタイマー"),
    ("현재 타이머", "the current timer", "現在のタイマー"),
    ("마지막 타이머", "the last timer", "最後のタイマー"),
)

YOUTUBE_QUERIES: tuple[LanguageText, ...] = (
    ("재즈", "jazz", "ジャズ"),
    ("집중 음악", "focus music", "集中用音楽"),
    ("최신 뉴스", "the latest news", "最新ニュース"),
    ("요리 영상", "a cooking video", "料理動画"),
    ("고양이 영상", "cat videos", "猫の動画"),
    ("수면 음악", "sleep music", "睡眠用音楽"),
    ("파이썬 강의", "a Python lesson", "Python講座"),
    ("이 노래", "this song", "この曲"),
)


FAST_TEXTS: dict[str, dict[str, tuple[LanguageText, ...]]] = {
    "get_current_time": {
        "normal": (
            ("지금 몇 시야", "What time is it now?", "今何時？"),
            ("현재 시간을 확인해줘", "Check the current time", "現在時刻を確認して"),
            ("시계를 보고 시간을 알려줘", "Look at the clock and tell me the time", "時計を見て時刻を教えて"),
        ),
        "conversational": (
            ("시간 좀 봐줄래", "Could you check the time for me?", "時間を見てくれる？"),
            ("지금 시간이 어떻게 돼", "Do you know what time it is?", "今何時か分かる？"),
        ),
        "short": (
            ("몇 시", "What time", "何時"),
            ("시간 알려줘", "Time please", "時間教えて"),
            ("현재 시각", "Current time", "現在時刻"),
        ),
        "polite": (
            ("현재 시각을 알려주시겠어요", "Would you please tell me the current time?", "現在時刻を教えていただけますか"),
            ("지금 몇 시인지 말씀해 주세요", "Please tell me what time it is", "今何時か教えてください"),
        ),
        "alias": (
            ("시계 정보 좀 말해줘", "Tell me the clock reading", "時計の表示を教えて"),
            ("현재 시각을 확인해", "Check the time reading", "現在の時刻表示を確認して"),
        ),
        "slang": (
            ("지금 몇 시냐", "What time is it?", "今何時だ"),
            ("시간 봐줘", "Check the time", "時間見て"),
        ),
        "entity_replacement": (
            ("{zone} 시간으로 몇 시야", "What time is it in {zone}?", "{zone}は今何時？"),
            ("{zone} 현지 시각을 알려줘", "Tell me the local time in {zone}", "{zone}の現地時刻を教えて"),
        ),
        "stt_noise": (
            ("지금 몇시야", "What time is it now", "今何時かね"),
            ("현재시간 알려줘", "Tell me the current time", "現在時刻教えて"),
        ),
    },
    "get_weather": {
        "normal": (
            ("{place} 날씨를 알려줘", "Tell me the weather in {place}", "{place}の天気を教えて"),
            ("{place}의 현재 날씨를 확인해줘", "Check the current weather in {place}", "{place}の現在の天気を確認して"),
        ),
        "conversational": (
            ("{place} 오늘 날씨 어때", "How is the weather in {place} today?", "今日の{place}の天気どう？"),
            ("{place} 비 와?", "Is it raining in {place}?", "{place}は雨？"),
        ),
        "short": (
            ("{place} 날씨", "Weather in {place}", "{place}の天気"),
            ("{place} 기온", "Temperature in {place}", "{place}の気温"),
        ),
        "polite": (
            ("{place} 날씨를 확인해 주시겠어요", "Could you check the weather in {place}?", "{place}の天気を確認していただけますか"),
            ("{place}의 기온을 알려 주세요", "Please tell me the temperature in {place}", "{place}の気温を教えてください"),
        ),
        "alias": (
            ("{place} 바깥 날씨 좀 봐줘", "Take a look at the outdoor weather in {place}", "{place}の外の天気を見て"),
            ("{place} 일기예보를 찾아줘", "Find the forecast for {place}", "{place}の天気予報を探して"),
        ),
        "slang": (
            ("{place} 날씨 어떰", "How's the weather in {place}?", "{place}の天気どうだ"),
            ("{place} 비 오냐", "Is it raining in {place}?", "{place}雨降ってる？"),
        ),
        "entity_replacement": (
            ("{place} 주말 날씨를 봐줘", "Check the weekend forecast for {place}", "{place}の週末の天気を見て"),
            ("{place} 내일 기온이 궁금해", "I want to know tomorrow's temperature in {place}", "{place}の明日の気温が知りたい"),
        ),
        "stt_noise": (
            ("{place} 날씨 알려줘", "Tell me the weather in {place}", "{place}の天気教えてね"),
            ("{place}의날씨 확인해줘", "Check the weather in {place}", "{place}の天気を確認して"),
        ),
    },
    "adjust_volume": {
        "normal": (
            ("볼륨을 {level}로 설정해줘", "Set the volume to {level}", "音量を{level}に設定して"),
            ("소리를 {level} 정도로 맞춰줘", "Set the sound to about {level}", "音量を{level}くらいにして"),
        ),
        "conversational": (
            ("소리 좀 키워줄래", "Could you turn the sound up?", "音量を上げてくれる？"),
            ("볼륨을 조금 낮춰줘", "Lower the volume a little", "音量を少し下げて"),
        ),
        "short": (
            ("볼륨 올려", "Volume up", "音量上げて"),
            ("소리 내려", "Volume down", "音量下げて"),
        ),
        "polite": (
            ("볼륨을 {level} 정도로 조절해 주시겠어요", "Would you adjust the volume to about {level}?", "音量を{level}くらいに調整していただけますか"),
            ("소리를 조금 키워 주세요", "Please turn the sound up a little", "音量を少し上げてください"),
        ),
        "alias": (
            ("미디어 음량을 {level}로 맞춰줘", "Set the media volume to {level}", "メディア音量を{level}にして"),
            ("재생 소리를 낮춰줘", "Turn down the playback sound", "再生音量を下げて"),
        ),
        "slang": (
            ("소리 좀 키워", "Crank the sound up", "音上げて"),
            ("볼륨 확 내려", "Drop the volume way down", "音量ガッと下げて"),
        ),
        "entity_replacement": (
            ("볼륨을 {level}까지 올려줘", "Raise the volume up to {level}", "音量を{level}まで上げて"),
            ("볼륨을 {delta}만큼 올려줘", "Increase the volume by {delta}", "音量を{delta}上げて"),
        ),
        "stt_noise": (
            ("볼륨을 {level}로 맞춰 줘", "Set volume to {level}", "音量を{level}にして"),
            ("소리좀 낮춰줘", "Lower the volume", "音量下げてね"),
        ),
    },
    "set_timer": {
        "normal": (
            ("{duration} 타이머를 설정해줘", "Set a {duration} timer", "{duration}のタイマーを設定して"),
            ("{duration} 뒤에 알림을 맞춰줘", "Set an alert for {duration}", "{duration}後に通知を設定して"),
        ),
        "conversational": (
            ("{duration} 지나면 알려줄래", "Could you remind me after {duration}?", "{duration}経ったら知らせてくれる？"),
            ("{duration} 타이머 하나 부탁해", "I need a {duration} timer", "{duration}のタイマーをお願い"),
        ),
        "short": (
            ("{duration} 타이머", "{duration} timer", "{duration}タイマー"),
            ("타이머 {duration}", "Timer for {duration}", "{duration}でタイマー"),
        ),
        "polite": (
            ("{duration} 타이머를 설정해 주시겠어요", "Would you set a {duration} timer?", "{duration}のタイマーを設定していただけますか"),
            ("{duration} 후에 알림을 보내 주세요", "Please alert me after {duration}", "{duration}後に通知してください"),
        ),
        "alias": (
            ("{duration} 카운트다운을 시작해줘", "Start a {duration} countdown", "{duration}のカウントダウンを始めて"),
            ("{duration} 뒤 알람을 예약해줘", "Schedule an alarm for {duration}", "{duration}後のアラームを予約して"),
        ),
        "slang": (
            ("{duration} 맞춰놔", "Set it for {duration}", "{duration}でセットして"),
            ("{duration} 되면 깨워", "Wake me after {duration}", "{duration}経ったら起こして"),
        ),
        "entity_replacement": (
            ("요리용으로 {duration} 타이머를 맞춰줘", "Set a cooking timer for {duration}", "料理用に{duration}のタイマーを設定して"),
            ("공부 끝날 때까지 {duration} 타이머를 돌려줘", "Run a {duration} study timer", "勉強用に{duration}のタイマーを動かして"),
        ),
        "stt_noise": (
            ("{duration}타이머 설정해줘", "Set a {duration} timer", "{duration}タイマー設定して"),
            ("{duration} 뒤에 알려줘", "Alert me after {duration}", "{duration}後に知らせて"),
        ),
    },
    "cancel_timer": {
        "normal": (
            ("{timer}를 취소해줘", "Cancel {timer}", "{timer}をキャンセルして"),
            ("{timer} 알림을 지워줘", "Remove the {timer} alert", "{timer}の通知を消して"),
        ),
        "conversational": (
            ("{timer} 이제 그만해줘", "Stop {timer} now", "{timer}を止めてくれる？"),
            ("{timer} 알림을 멈춰줄래", "Could you stop the {timer} alert?", "{timer}の通知を止めてくれる？"),
        ),
        "short": (
            ("{timer} 취소", "Cancel {timer}", "{timer}キャンセル"),
            ("타이머 멈춰", "Stop the timer", "タイマー停止"),
        ),
        "polite": (
            ("{timer}를 취소해 주시겠어요", "Would you cancel {timer}?", "{timer}をキャンセルしていただけますか"),
            ("현재 타이머를 중지해 주세요", "Please stop the current timer", "現在のタイマーを止めてください"),
        ),
        "alias": (
            ("{timer} 카운트다운을 없애줘", "Remove the {timer} countdown", "{timer}のカウントダウンを消して"),
            ("{timer} 예약 알림을 해제해줘", "Disable the {timer} scheduled alert", "{timer}の予約通知を解除して"),
        ),
        "slang": (
            ("{timer} 지워", "Cancel {timer}", "{timer}消して"),
            ("알림 그만", "Stop the alert", "通知やめて"),
        ),
        "entity_replacement": (
            ("{timer} 취소해줘", "Please cancel {timer} altogether", "{timer}をキャンセルして"),
            ("{timer}만 취소하고 나머지는 남겨줘", "Cancel only {timer} and keep the rest", "{timer}だけキャンセルして他は残して"),
        ),
        "stt_noise": (
            ("{timer} 취소해 줘", "Cancel {timer}", "{timer}キャンセルしてね"),
            ("타이머를 취소 해줘", "Cancel the timer", "タイマーをキャンセルして"),
        ),
    },
    "launch_app": {
        "normal": (
            ("{app} 앱을 열어줘", "Open {app}", "{app}を開いて"),
            ("{app} 앱을 실행해줘", "Launch {app}", "{app}を起動して"),
        ),
        "conversational": (
            ("{app} 좀 켜줄래", "Could you start {app}?", "{app}を起動してくれる？"),
            ("{app} 쓸 수 있게 띄워줘", "Bring up {app} so I can use it", "使えるように{app}を立ち上げて"),
        ),
        "short": (
            ("{app} 켜", "Open {app}", "{app}開いて"),
            ("{app} 실행", "Launch {app}", "{app}起動"),
        ),
        "polite": (
            ("{app} 앱을 열어 주시겠어요", "Would you open {app}?", "{app}を開いていただけますか"),
            ("{app} 앱을 실행해 주세요", "Please launch {app}", "{app}を起動してください"),
        ),
        "alias": (
            ("{app} 띄워줘", "Bring up {app}", "{app}を立ち上げて"),
            ("{app} 들어가줘", "Open {app} for me", "{app}を開いて"),
        ),
        "slang": (
            ("{app} 켜봐", "Fire up {app}", "{app}起動して"),
            ("{app} 올려", "Bring up {app}", "{app}上げて"),
        ),
        "entity_replacement": (
            ("다른 거 말고 {app}만 열어줘", "Open only {app}, not something else", "他のものではなく{app}だけ開いて"),
            ("작업에 쓸 {app} 앱을 시작해줘", "Start {app} for the task", "作業に使う{app}を起動して"),
        ),
        "stt_noise": (
            ("{app} 열어줘", "Open {app}", "{app}開いてね"),
            ("{app} 앱 켜줘", "Launch {app}", "{app}を起動して"),
        ),
    },
    "focus_window": {
        "normal": (
            ("{app} 창에 포커스를 맞춰줘", "Focus the {app} window", "{app}のウィンドウにフォーカスして"),
            ("{app} 창을 앞으로 가져와", "Bring the {app} window to the front", "{app}のウィンドウを前面に出して"),
        ),
        "conversational": (
            ("{app} 창 좀 보여줄래", "Could you show the {app} window?", "{app}のウィンドウを見せてくれる？"),
            ("{app} 창으로 전환해줄래", "Could you switch to the {app} window?", "{app}のウィンドウに切り替えてくれる？"),
        ),
        "short": (
            ("{app} 창 앞으로", "{app} window front", "{app}のウィンドウを前面に"),
            ("{app} 창으로 전환", "Switch to the {app} window", "{app}のウィンドウに切り替え"),
        ),
        "polite": (
            ("{app} 창을 활성화해 주시겠어요", "Would you activate the {app} window?", "{app}のウィンドウをアクティブにしていただけますか"),
            ("{app} 창을 앞으로 가져와 주세요", "Please bring the {app} window forward", "{app}のウィンドウを前面に出してください"),
        ),
        "alias": (
            ("{app} 화면을 선택해줘", "Select the {app} screen", "{app}の画面を選んで"),
            ("열려 있는 {app} 창에 가줘", "Go to the open {app} window", "開いている{app}のウィンドウに移って"),
        ),
        "slang": (
            ("{app} 앞으로 띄워", "Pull {app} to the front", "{app}前に出して"),
            ("{app} 창 잡아줘", "Grab the {app} window", "{app}のウィンドウを出して"),
        ),
        "entity_replacement": (
            ("다른 창 말고 {app} 창을 선택해줘", "Select the {app} window instead of another", "別のウィンドウではなく{app}を選んで"),
            ("현재 열려 있는 {app} 창을 활성화해줘", "Activate the currently open {app} window", "現在開いている{app}のウィンドウをアクティブにして"),
        ),
        "stt_noise": (
            ("{app} 창으로 포커스해줘", "Focus the {app} window", "{app}にフォーカスしてね"),
            ("{app}창 앞으로 가져와", "Bring the {app} window forward", "{app}ウィンドウを前面に"),
        ),
    },
    "get_running_apps": {
        "normal": (
            ("실행 중인 앱 목록을 보여줘", "Show the list of running apps", "起動中のアプリ一覧を見せて"),
            ("현재 켜진 프로그램을 알려줘", "Tell me which programs are open", "現在開いているプログラムを教えて"),
        ),
        "conversational": (
            ("지금 뭐가 켜져 있는지 볼 수 있을까", "Can I see what is running right now?", "今何が起動しているか見られる？"),
            ("열린 앱을 같이 확인해줘", "Check the open apps with me", "開いているアプリを一緒に確認して"),
        ),
        "short": (
            ("실행 중인 앱", "Running apps", "起動中のアプリ"),
            ("켜진 프로그램", "Open programs", "開いているプログラム"),
        ),
        "polite": (
            ("현재 실행 중인 앱을 알려주시겠어요", "Would you tell me which apps are running?", "現在起動中のアプリを教えていただけますか"),
            ("열려 있는 프로그램을 확인해 주세요", "Please check the open programs", "開いているプログラムを確認してください"),
        ),
        "alias": (
            ("백그라운드에서 도는 앱을 나열해줘", "List the apps running in the background", "バックグラウンドで動くアプリを一覧にして"),
            ("활성 프로세스 목록을 보여줘", "Show the active process list", "アクティブなプロセス一覧を見せて"),
        ),
        "slang": (
            ("뭐 켜져 있냐", "What's running?", "何が起動してる？"),
            ("켜진 거 쭉 보여줘", "Show everything that's open", "起動中のものを全部見せて"),
        ),
        "entity_replacement": (
            ("지금 실행 중인 앱만 골라서 알려줘", "Tell me which apps are currently running", "今実行中のアプリだけ教えて"),
            ("창이 있는 프로그램을 확인해줘", "Check the programs with windows", "ウィンドウのあるプログラムを確認して"),
        ),
        "stt_noise": (
            ("실행중인 앱 보여줘", "Show running apps", "起動中アプリ見せて"),
            ("지금 켜진프로그램 알려줘", "Tell me the open programs", "今開いてるプログラム教えて"),
        ),
    },
    "play_youtube": {
        "normal": (
            ("유튜브에서 {query} 재생해줘", "Play {query} on YouTube", "YouTubeで{query}を再生して"),
            ("유튜브에서 {query} 찾아서 틀어줘", "Find {query} on YouTube and play it", "YouTubeで{query}を探して再生して"),
        ),
        "conversational": (
            ("유튜브에서 {query} 좀 틀어줄래", "Could you play {query} on YouTube?", "YouTubeで{query}を流してくれる？"),
            ("유튜브에서 {query} 재생하면서 쉬고 싶어", "I want to relax while playing {query} on YouTube", "YouTubeで{query}を再生しながら休みたい"),
        ),
        "short": (
            ("유튜브에서 {query} 틀어", "Play {query} on YouTube", "YouTubeで{query}を再生して"),
            ("유튜브에서 {query} 재생", "Play {query} on YouTube", "YouTubeで{query}を再生して"),
        ),
        "polite": (
            ("유튜브에서 {query} 재생해 주시겠어요", "Would you play {query} on YouTube?", "YouTubeで{query}を再生していただけますか"),
            ("유튜브에서 {query} 영상을 재생해 주시겠어요", "Would you play a {query} video on YouTube?", "YouTubeで{query}の動画を再生していただけますか"),
        ),
        "alias": (
            ("유튜브에서 검색해서 {query} 틀어줘", "Search YouTube and play {query}", "YouTubeで検索して{query}を再生して"),
            ("유튜브에서 {query} 영상 하나 골라 재생해줘", "Pick and play a {query} video on YouTube", "YouTubeで{query}の動画を一つ選んで再生して"),
        ),
        "slang": (
            ("유튜브로 {query} 틀자", "Let's play {query} on YouTube", "YouTubeで{query}を流そう"),
            ("{query} 유튜브에 틀어", "Put on {query} from YouTube", "{query}をYouTubeで流して"),
        ),
        "entity_replacement": (
            ("다른 영상 말고 유튜브에서 {query} 재생해줘", "Play {query} on YouTube instead of another video", "他の動画ではなくYouTubeで{query}を再生して"),
            ("지금 듣고 싶은 {query} 유튜브에서 찾아서 재생해줘", "Find and play the {query} I want to hear on YouTube", "今聴きたい{query}をYouTubeで探して再生して"),
        ),
        "stt_noise": (
            ("유튜브에서 {query} 재생해줘", "Play {query} on YouTube", "YouTubeで{query}再生して"),
            ("유튜브로{query} 틀어줘", "Play {query} on YouTube", "YouTubeで{query}を流してね"),
        ),
    },
    "take_screenshot": {
        "normal": (
            ("현재 화면을 캡처해서 저장해줘", "Capture and save the current screen", "現在の画面をキャプチャして保存して"),
            ("스크린샷 파일을 만들어줘", "Create a screenshot file", "スクリーンショットファイルを作って"),
        ),
        "conversational": (
            ("지금 화면 한 장 찍어줄래", "Could you take a shot of the screen?", "今の画面を一枚撮ってくれる？"),
            ("화면을 이미지로 남겨줄래", "Could you save the screen as an image?", "画面を画像で残してくれる？"),
        ),
        "short": (
            ("화면 캡처", "Screenshot", "画面キャプチャ"),
            ("스크린샷 찍어", "Take a screenshot", "スクショ撮って"),
        ),
        "polite": (
            ("현재 화면을 캡처해 주시겠어요", "Would you capture the current screen?", "現在の画面をキャプチャしていただけますか"),
            ("화면을 파일로 저장해 주세요", "Please save the screen to a file", "画面をファイルに保存してください"),
        ),
        "alias": (
            ("디스플레이를 이미지로 기록해줘", "Record the display as an image", "ディスプレイを画像として記録して"),
            ("현재 모니터 화면을 캡처해줘", "Capture the current monitor display", "現在のモニター画面をキャプチャして"),
        ),
        "slang": (
            ("화면 한 컷 남겨", "Snap the screen", "画面を一枚撮って"),
            ("스크린샷 고", "Screenshot, go", "スクショお願い"),
        ),
        "entity_replacement": (
            ("분석하지 말고 화면만 캡처해줘", "Capture only the screen without analyzing it", "分析せず画面だけキャプチャして"),
            ("전체 화면을 이미지로 저장해줘", "Save the full screen as an image", "全画面を画像として保存して"),
        ),
        "stt_noise": (
            ("화면캡처 저장해줘", "Save a screenshot", "画面キャプチャ保存して"),
            ("스크린샷 찍어 줘", "Take a screenshot", "スクショ撮ってね"),
        ),
    },
}


SLOT_OPTIONS: SlotValues = {
    "app": APP_SLOTS,
    "delta": VOLUME_DELTAS,
    "duration": DURATION_SLOTS,
    "level": VOLUME_LEVELS,
    "place": WEATHER_SLOTS,
    "query": YOUTUBE_QUERIES,
    "timer": TIMER_SLOTS,
    "zone": TIMEZONE_SLOTS,
}


HARD_NEGATIVE_TEXTS: Mapping[tuple[str, str], tuple[LanguageText, LanguageText]] = {
    ("launch_app", "focus_window"): (
        ("계산기 앱을 실행해줘", "Launch the Calculator app", "電卓アプリを起動して"),
        ("열려 있는 계산기 창을 앞으로 가져와", "Bring the open Calculator window to the front", "開いている電卓のウィンドウを前面に出して"),
    ),
    ("focus_window", "close_app"): (
        ("열려 있는 메모장 창으로 전환해줘", "Switch to the open Notepad window", "開いているメモ帳のウィンドウに切り替えて"),
        ("메모장 앱을 종료해줘", "Close the Notepad app", "メモ帳アプリを終了して"),
    ),
    ("launch_app", "close_app"): (
        ("스팀 앱을 실행해줘", "Launch the Steam app", "Steamアプリを起動して"),
        ("스팀 앱을 종료해줘", "Close the Steam app", "Steamアプリを終了して"),
    ),
    ("take_screenshot", "analyze_screenshot"): (
        ("현재 화면의 스크린샷을 찍어줘", "Take a screenshot of the current screen", "現在の画面のスクリーンショットを撮って"),
        ("화면 스크린샷을 살펴보고 오류가 있는지 설명해줘", "Inspect the screen capture and explain whether it contains an error", "画面のスクリーンショットを確認してエラーがあるか説明して"),
    ),
    ("search_in_files", "web_search"): (
        ("문서 파일 안에서 예산이라는 단어를 찾아줘", "Find the word budget inside the document file", "文書ファイルの中から予算という言葉を探して"),
        ("웹에서 올해 예산 정보를 검색해줘", "Search the web for this year's budget information", "ウェブで今年の予算情報を検索して"),
    ),
    ("read_file", "read_emails"): (
        ("보고서.txt 파일의 내용을 읽어줘", "Read the contents of report.txt", "report.txtの内容を読んで"),
        ("받은 편지함에서 오늘 온 이메일을 읽어줘", "Read today's emails from my inbox", "受信トレイから今日届いたメールを読んで"),
    ),
    ("schedule_task", "set_timer"): (
        ("내일 오전 9시에 백업 작업을 실행하도록 예약해줘", "Schedule the backup task to run tomorrow at 9 AM", "明日の午前9時にバックアップ作業を実行するよう予約して"),
        ("10분 뒤에 알림이 울리도록 타이머를 설정해줘", "Set a timer to alert me in ten minutes", "10分後に通知が鳴るようタイマーを設定して"),
    ),
    ("set_clipboard", "write_file"): (
        ("클립보드에 '오전 회의' 문구를 복사해줘", "Copy the phrase 'morning meeting' to the clipboard", "「朝の会議」という文言をクリップボードにコピーして"),
        ("agenda.txt 파일에 '오전 회의' 문구를 저장해줘", "Save the phrase 'morning meeting' in agenda.txt", "「朝の会議」という文言をagenda.txtファイルに保存して"),
    ),
    ("get_weather", "get_calendar_events"): (
        ("제주도의 이번 주말 강수 예보를 알려줘", "Tell me Jeju's rain forecast for this weekend", "済州島の今週末の雨予報を教えて"),
        ("오늘 내 캘린더 일정을 보여줘", "Show me today's calendar events", "今日のカレンダーの予定を見せて"),
    ),
}


UNKNOWN_TEXTS: Mapping[str, tuple[LanguageText, ...]] = {
    "multi_intent": (
        ("유튜브를 열고 재즈를 검색해서 재생해줘", "Open YouTube, search for jazz, and play it", "YouTubeを開いてジャズを検索して再生して"),
        ("내일 일정을 확인하고 회의 알림도 설정해줘", "Check tomorrow's calendar and set a meeting reminder", "明日の予定を確認して会議の通知も設定して"),
        ("화면을 캡처하고 오류 원인도 분석해줘", "Capture the screen and analyze the cause of the error", "画面をキャプチャしてエラーの原因も分析して"),
        ("파일을 찾아 수정한 다음 이메일로 보내줘", "Find the file, edit it, and then send it by email", "ファイルを探して編集した後メールで送って"),
    ),
    "unknown_complex": (
        ("컴퓨터를 알아서 최적화하고 불필요한 건 정리해줘", "Optimize my computer and clean up anything unnecessary", "パソコンを自動で最適化して不要なものを整理して"),
        ("내가 하려는 일을 파악해서 필요한 작업을 순서대로 끝내줘", "Figure out what I am trying to do and finish the needed steps in order", "私のやりたいことを読み取って必要な作業を順番に終わらせて"),
        ("관련된 자료를 모두 확인해서 가장 나은 선택을 하고 실행해줘", "Review all related material, choose the best option, and carry it out", "関連資料をすべて確認して最善の選択を実行して"),
        ("문제가 뭔지 진단하고 안전한 방법으로 전부 고쳐줘", "Diagnose the problem and fix everything safely", "問題を診断して安全な方法ですべて直して"),
    ),
    "conversation": (
        ("오늘 좀 지쳤어. 얘기 좀 들어줄래?", "I feel worn out today. Could you listen for a bit?", "今日はちょっと疲れた。少し話を聞いてくれる？"),
        ("고마워, 덕분에 해결됐어", "Thanks, that helped me solve it", "ありがとう、おかげで解決したよ"),
        ("재미있는 이야기 하나 해줘", "Tell me an interesting story", "面白い話を一つして"),
        ("너는 쉬는 날에 뭐 해?", "What do you do on your days off?", "休みの日は何をするの？"),
    ),
    "knowledge_question": (
        ("블랙홀은 어떻게 만들어져?", "How are black holes formed?", "ブラックホールはどうやってできるの？"),
        ("파이썬 데코레이터를 쉽게 설명해줘", "Explain Python decorators in simple terms", "Pythonのデコレーターを簡単に説明して"),
        ("지구와 화성은 어떤 점이 달라?", "How are Earth and Mars different?", "地球と火星はどんなところが違うの？"),
        ("이 문장을 영어로 번역해줘", "Translate this sentence into English", "この文を英語に翻訳して"),
    ),
}


def _render_template(texts: LanguageText, bucket: str) -> Iterable[dict[str, str]]:
    fields = tuple(dict.fromkeys(
        field
        for text in texts
        for _, field, _, _ in Formatter().parse(text)
        if field
    ))
    choices: list[tuple[LanguageText, ...]] = []
    for field in fields:
        if field == "app" and bucket == "alias":
            choices.append(APP_ALIAS_SLOTS)
        else:
            try:
                choices.append(SLOT_OPTIONS[field])
            except KeyError as exc:
                raise ValueError(f"no slot values defined for {{{field}}}") from exc

    for selected in product(*choices):
        yield {
            language: text.format(**{
                field: slot[language_index]
                for field, slot in zip(fields, selected)
            })
            for language_index, (language, text) in enumerate(zip(("ko", "en", "ja"), texts))
        }


def expanded_families() -> list[FamilyRecord]:
    """Return deterministic multilingual templates with slot siblings grouped."""

    families: list[FamilyRecord] = []
    for label in FAST_LABELS:
        for bucket, templates in FAST_TEXTS[label].items():
            for template_index, texts in enumerate(templates, start=1):
                family_id = f"expanded.{label}.{bucket}.{template_index:02d}"
                for rendered in _render_template(texts, bucket):
                    families.append({
                        "family_id": family_id,
                        "template_id": family_id,
                        "source_family_ids": [family_id],
                        "label": label,
                        "bucket": bucket,
                        "texts": rendered,
                    })

    for pair in HARD_NEGATIVE_PAIRS:
        try:
            directional_texts = HARD_NEGATIVE_TEXTS[pair]
        except KeyError as exc:
            raise ValueError(f"missing hard-negative examples for {pair}") from exc
        for label, texts in zip(pair, directional_texts):
            family_id = f"expanded.hard_negative.{pair[0]}.{pair[1]}.{label}"
            families.append({
                "family_id": family_id,
                "template_id": family_id,
                "source_family_ids": [family_id],
                "label": label,
                "bucket": "hard_negative",
                "texts": dict(zip(("ko", "en", "ja"), texts)),
                "hard_negative_pair": list(pair),
            })

    for bucket, examples in UNKNOWN_TEXTS.items():
        for template_index, texts in enumerate(examples, start=1):
            family_id = f"expanded.unknown_or_complex.{bucket}.{template_index:02d}"
            families.append({
                "family_id": family_id,
                "template_id": family_id,
                "source_family_ids": [family_id],
                "label": "unknown_or_complex",
                "bucket": bucket,
                "texts": dict(zip(("ko", "en", "ja"), texts)),
            })

    return families
