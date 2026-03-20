"""
날씨 조회 서비스 모듈
Open-Meteo API 사용 (무료, API 키 불필요)
"""
import logging
import requests
from datetime import datetime


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


class WeatherService:
    """날씨 정보 조회 서비스 (Open-Meteo)"""

    def __init__(self, api_key=None):
        # api_key는 하위 호환성을 위해 유지 (사용하지 않음)
        pass

    def get_current_location(self):
        """IP 기반 현재 위치 조회. 실패 시 서울 기본값 반환."""
        try:
            data = requests.get("https://ipapi.co/json/", timeout=5).json()
            lat = data.get("latitude", 37.5665)
            lon = data.get("longitude", 126.9780)
            city_eng = data.get("city", "")
            
            # 한국어 변환
            city = CITY_NAME_MAP.get(city_eng, city_eng)
            if not city: city = "주변"
            
            logging.info(f"IP 위치: {city_eng} -> {city} ({lat}, {lon})")
            return lat, lon, city
        except Exception as e:
            logging.error(f"위치 정보 실패: {e}")
            return 37.5665, 126.9780, "서울"

    def get_weather(self, lat=None, lon=None):
        """
        현재 위치의 날씨 조회

        Returns:
            str: 날씨 정보 문자열
        """
        city = ""
        if lat is None or lon is None:
            lat, lon, city = self.get_current_location()

        try:
            url = "https://api.open-meteo.com/v1/forecast"
            params = {
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "Asia/Seoul",
                "forecast_days": 1,
            }
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            current = data["current"]
            daily = data["daily"]

            temp = current["temperature_2m"]
            humidity = current["relative_humidity_2m"]
            rain = current["precipitation"]
            code = current["weather_code"]
            status = WMO_CODE.get(code, "알 수 없음")

            t_max = daily["temperature_2m_max"][0]
            t_min = daily["temperature_2m_min"][0]
            pop = daily["precipitation_probability_max"][0]

            location = f"{city} " if city else ""
            info = f"{location}현재 날씨는 {status}입니다. "
            info += f"기온은 {temp:.0f}도, 습도는 {humidity}%"
            if rain > 0:
                info += f", 강수량은 {rain:.1f}밀리미터"
            info += f"입니다. 오늘 최고 {t_max:.0f}도, 최저 {t_min:.0f}도이며, 강수 확률은 {pop}%입니다."

            return info

        except requests.exceptions.RequestException as e:
            logging.error(f"날씨 요청 오류: {e}")
            return "날씨 정보를 가져오는 데 실패했습니다."
        except Exception as e:
            logging.error(f"날씨 처리 오류: {e}", exc_info=True)
            return "날씨 정보를 가져오는 중 오류가 발생했습니다."
