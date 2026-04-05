"""
날씨 조회 서비스 모듈
Open-Meteo API 사용 (무료, API 키 불필요)
"""
import logging
import re
import threading
import time

import requests


# WMO 날씨 코드 → 한국어
WMO_CODE = {
    0: "맑음",
    1: "대체로 맑음", 2: "구름 많음", 3: "흐림",
    45: "안개", 48: "안개",
    51: "이슬비", 53: "이슬비", 55: "이슬비",
    61: "비", 63: "비", 65: "강한 비",
    71: "눈", 73: "눈", 75: "강한 눈",
    80: "소나기", 81: "소나기", 82: "강한 소나기",
    95: "천둥번개", 96: "천둥번개(우박)", 99: "천둥번개(우박)",
}

# 영문 도시명 → 한국어 매핑
CITY_NAME_MAP = {
    "Seoul": "서울", "Busan": "부산", "Incheon": "인천", "Daegu": "대구",
    "Daejeon": "대전", "Gwangju": "광주", "Ulsan": "울산", "Suwon": "수원",
    "Seongnam": "성남", "Goyang": "고양", "Yongin": "용인", "Bucheon": "부천",
    "Ansan": "안산", "Anyang": "안양", "Namyangju": "남양주", "Hwaseong": "화성",
    "Cheongju": "청주", "Cheongju-si": "청주", "Chuncheon": "춘천", "Gangneung": "강릉",
    "Wonju": "원주", "Jeonju": "전주", "Iksan": "익산", "Gunsan": "군산",
    "Mokpo": "목포", "Yeosu": "여수", "Suncheon": "순천", "Pohang": "포항",
    "Gumi": "구미", "Gyeongju": "경주", "Gyeongsan": "경산", "Changwon": "창원",
    "Gimhae": "김해", "Jinju": "진주", "Yangsan": "양산", "Jeju": "제주",
    "Sejong": "세종", "Asan": "아산", "Cheonan": "천안", "Gimpo": "김포",
}

CITY_COORDINATES = {
    "서울": (37.5665, 126.9780),
    "부산": (35.1796, 129.0756),
    "인천": (37.4563, 126.7052),
    "대구": (35.8722, 128.6025),
    "대전": (36.3504, 127.3845),
    "광주": (35.1595, 126.8526),
    "울산": (35.5384, 129.3114),
    "수원": (37.2636, 127.0286),
    "청주": (36.6424, 127.4890),
    "천안": (36.8151, 127.1139),
    "세종": (36.4800, 127.2890),
    "제주": (33.4996, 126.5312),
}


class WeatherService:
    """날씨 정보 조회 서비스 (Open-Meteo)"""

    _session = requests.Session()
    _cache_lock = threading.Lock()
    _location_cache: tuple[float, tuple[float, float, str]] | None = None
    _weather_cache: dict[tuple[float, float, str, int], tuple[float, str]] = {}
    _LOCATION_TTL_SECONDS = 30 * 60
    _WEATHER_TTL_SECONDS = 10 * 60

    def __init__(self, api_key=None):
        # api_key는 하위 호환성을 위해 유지 (사용하지 않음)
        pass

    def get_current_location(self):
        """IP 기반 현재 위치 조회. 실패 시 서울 기본값 반환."""
        now = time.time()
        with self._cache_lock:
            if self._location_cache and now - self._location_cache[0] < self._LOCATION_TTL_SECONDS:
                return self._location_cache[1]
        try:
            data = self._session.get("https://ipapi.co/json/", timeout=5).json()
            lat = data.get("latitude", 37.5665)
            lon = data.get("longitude", 126.9780)
            city_eng = data.get("city", "")

            # 한국어 변환
            city = CITY_NAME_MAP.get(city_eng, city_eng)
            if not city: city = "주변"

            logging.info(f"IP 위치: {city_eng} -> {city} ({lat}, {lon})")
            resolved = (lat, lon, city)
            with self._cache_lock:
                self._location_cache = (now, resolved)
            return resolved
        except Exception as e:
            logging.error(f"위치 정보 실패: {e}")
            return 37.5665, 126.9780, "서울"

    def _extract_day_offset(self, text: str) -> int:
        normalized = re.sub(r"\s+", "", text or "")
        if "모레" in normalized:
            return 2
        if "내일" in normalized:
            return 1
        return 0

    def _extract_city_name(self, text: str) -> str:
        normalized = (text or "").replace(" ", "")
        city_candidates = sorted(set(CITY_NAME_MAP.values()), key=len, reverse=True)
        for city in city_candidates:
            if city and city in normalized:
                return city
        return ""

    def _resolve_city_coordinates(self, city_name: str):
        if not city_name:
            return None
        if city_name in CITY_COORDINATES:
            lat, lon = CITY_COORDINATES[city_name]
            return lat, lon, city_name
        try:
            resp = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={
                    "name": city_name,
                    "count": 1,
                    "language": "ko",
                    "countryCode": "KR",
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results") or []
            if not results:
                return None
            top = results[0]
            return top.get("latitude"), top.get("longitude"), city_name
        except Exception as e:
            logging.error(f"도시 좌표 조회 실패 ({city_name}): {e}")
            return None

    def get_weather_from_text(self, text: str) -> str:
        city_name = self._extract_city_name(text)
        day_offset = self._extract_day_offset(text)

        if city_name:
            resolved = self._resolve_city_coordinates(city_name)
            if resolved:
                lat, lon, city = resolved
                return self.get_weather(lat=lat, lon=lon, city=city, day_offset=day_offset)

        return self.get_weather(day_offset=day_offset)

    def get_weather(self, lat=None, lon=None, city="", day_offset=0):
        """
        현재 위치의 날씨 조회

        Returns:
            str: 날씨 정보 문자열
        """
        if lat is None or lon is None:
            lat, lon, detected_city = self.get_current_location()
            if not city:
                city = detected_city

        cache_key = (round(float(lat), 4), round(float(lon), 4), city or "", int(day_offset))
        now = time.time()
        with self._cache_lock:
            cached = self._weather_cache.get(cache_key)
            if cached and now - cached[0] < self._WEATHER_TTL_SECONDS:
                return cached[1]

        try:
            url = "https://api.open-meteo.com/v1/forecast"
            params = {
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "Asia/Seoul",
                "forecast_days": max(day_offset + 1, 1),
            }
            resp = self._session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            current = data["current"]
            daily = data["daily"]

            index = min(day_offset, len(daily["temperature_2m_max"]) - 1)
            t_max = daily["temperature_2m_max"][index]
            t_min = daily["temperature_2m_min"][index]
            pop = daily["precipitation_probability_max"][index]
            forecast_code = daily["weather_code"][index]

            if day_offset == 0:
                temp = current["temperature_2m"]
                humidity = current["relative_humidity_2m"]
                rain = current["precipitation"]
                status = WMO_CODE.get(current["weather_code"], "알 수 없음")
            else:
                temp = (t_max + t_min) / 2
                humidity = None
                rain = 0
                status = WMO_CODE.get(forecast_code, "알 수 없음")

            location = f"{city} " if city else ""
            day_label = "현재" if day_offset == 0 else ("내일" if day_offset == 1 else "모레")
            info = f"{location}{day_label} 날씨는 {status}입니다. "
            info += f"기온은 {temp:.0f}도"
            if humidity is not None:
                info += f", 습도는 {humidity}%"
            if rain > 0:
                info += f", 강수량은 {rain:.1f}밀리미터"
            info += "입니다. "
            info += f"{day_label} 최고 {t_max:.0f}도, 최저 {t_min:.0f}도"
            if pop is not None:
                info += f", 강수 확률은 {pop}%"
            info += "입니다."

            with self._cache_lock:
                self._weather_cache[cache_key] = (now, info)
            return info

        except requests.exceptions.RequestException as e:
            logging.error(f"날씨 요청 오류: {e}")
            return "날씨 정보를 가져오는 데 실패했습니다."
        except Exception as e:
            logging.error(f"날씨 처리 오류: {e}", exc_info=True)
            return "날씨 정보를 가져오는 중 오류가 발생했습니다."
