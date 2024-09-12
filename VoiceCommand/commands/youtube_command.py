"""유튜브 명령 — 웹브라우저로 검색/재생"""
import webbrowser
import urllib.parse
import logging
from commands.base_command import BaseCommand


class YoutubeCommand(BaseCommand):
    def __init__(self, tts_func):
        self.tts_wrapper = tts_func

    def matches(self, text: str) -> bool:
        return "유튜브" in text

    # 검색어가 아닌 동사/조사 표현
    _ACTION_WORDS = [
        "열어줘", "열어 줘", "켜줘", "켜 줘", "틀어줘", "틀어 줘",
        "재생해줘", "재생해 줘", "보여줘", "보여 줘", "찾아줘", "찾아 줘",
        "열어", "켜", "틀어", "재생", "검색", "열기", "해줘", "줘",
    ]

    def execute(self, text: str) -> None:
        query = text.replace("유튜브", "").strip()

        # 동사/조사 제거
        for word in self._ACTION_WORDS:
            query = query.replace(word, "")
        query = query.strip()

        if query:
            url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
            self.tts_wrapper(f"{query} 유튜브에서 검색할게요.")
        else:
            url = "https://www.youtube.com"
            self.tts_wrapper("유튜브를 열게요.")

        logging.info(f"유튜브 열기: {url}")
        webbrowser.open(url)
