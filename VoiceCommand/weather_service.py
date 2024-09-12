"""
날씨 조회 서비스 모듈
공공데이터포털 API 사용
"""
import logging
import math
import requests
from datetime import datetime, timedelta


class WeatherService:
    """날씨 정보 조회 서비스"""

    def __init__(self, api_key):
        """
        Args:
            api_key: 공공데이터포털 API 키
        """
        self.api_key = api_key
        self.base_url = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0"

    def get_current_location(self):
        """
        IP 기반 현재 위치 조회

        Returns:
            Tuple[float, float]: (위도, 경도)
        """
        try:
            ip_response = requests.get("https://ipapi.co/json/")
            ip_data = ip_response.json()
            latitude = ip_data.get("latitude", 37.5665)
            longitude = ip_data.get("longitude", 126.9780)

            logging.info(f"IP 기반 위치: 위도 {latitude}, 경도 {longitude}")

            # 한국 내 위치인지 확인
            if 33 <= latitude <= 38 and 124 <= longitude <= 132:
                return latitude, longitude
            else:
                logging.warning("현재 위치가 한국 밖입니다. 서울의 좌표를 사용합니다.")
                return 37.5665, 126.9780
        except Exception as e:
            logging.error(f"위치 정보 가져오기 실패: {str(e)}")
            return 37.5665, 126.9780

    def convert_coord(self, lat, lon):
        """
        위경도를 기상청 격자 좌표로 변환

        Args:
            lat: 위도
            lon: 경도

        Returns:
            Tuple[int, int]: (x, y) 격자 좌표
        """
        RE = 6371.00877  # 지구 반경(km)
        GRID = 5.0  # 격자 간격(km)
        SLAT1 = 30.0  # 투영 위도1(degree)
        SLAT2 = 60.0  # 투영 위도2(degree)
        OLON = 126.0  # 기준점 경도(degree)
        OLAT = 38.0  # 기준점 위도(degree)
        XO = 43  # 기준점 X좌표(GRID)
        YO = 136  # 기준점 Y좌표(GRID)

        DEGRAD = math.pi / 180.0
        re = RE / GRID
        slat1 = SLAT1 * DEGRAD
        slat2 = SLAT2 * DEGRAD
        olon = OLON * DEGRAD
        olat = OLAT * DEGRAD

        sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
        sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
        sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
        sf = math.pow(sf, sn) * math.cos(slat1) / sn
        ro = math.tan(math.pi * 0.25 + olat * 0.5)
        ro = re * sf / math.pow(ro, sn)

        ra = math.tan(math.pi * 0.25 + lat * DEGRAD * 0.5)
        ra = re * sf / math.pow(ra, sn)
        theta = lon * DEGRAD - olon
        if theta > math.pi:
            theta -= 2.0 * math.pi
        if theta < -math.pi:
            theta += 2.0 * math.pi
        theta *= sn

        x = math.floor(ra * math.sin(theta) + XO + 0.5)
        y = math.floor(ro - ra * math.cos(theta) + YO + 0.5)

        return int(x), int(y)

    def format_decimal(self, value, decimal_places=1):
        """
        소수를 한글 표현으로 변환 (예: 12.5 -> "12점5")

        Args:
            value: 변환할 숫자
            decimal_places: 소수점 자리수

        Returns:
            str: 한글 표현
        """
        integer_part = int(value)
        decimal_part = int((value - integer_part) * (10 ** decimal_places))
        if decimal_part == 0:
            return f"{integer_part}"
        return f"{integer_part}점{decimal_part}"

    def get_weather(self, lat=None, lon=None):
        """
        현재 위치의 날씨 조회

        Args:
            lat: 위도 (None이면 자동 감지)
            lon: 경도 (None이면 자동 감지)

        Returns:
            str: 날씨 정보 문자열
        """
        if lat is None or lon is None:
            lat, lon = self.get_current_location()

        now = datetime.now()
        base_date = now.strftime("%Y%m%d")

        # 단기예보 발표 시간
        forecast_times = ['0200', '0500', '0800', '1100', '1400', '1700', '2000', '2300']
        base_time = max([t for t in forecast_times if now.strftime("%H%M") > t] or ['2300'])

        # 어제 23시 발표 사용
        if base_time == '2300' and now.strftime("%H%M") < '0200':
            base_date = (now - timedelta(days=1)).strftime("%Y%m%d")

        nx, ny = self.convert_coord(lat, lon)

        # 초단기실황 조회
        ultra_srt_ncst_url = f"{self.base_url}/getUltraSrtNcst"
        ultra_srt_ncst_params = {
            "serviceKey": self.api_key,
            "pageNo": "1",
            "numOfRows": "1000",
            "dataType": "JSON",
            "base_date": base_date,
            "base_time": base_time,
            "nx": str(nx),
            "ny": str(ny),
        }

        try:
            # 초단기실황 데이터
            ultra_srt_ncst_response = requests.get(ultra_srt_ncst_url, params=ultra_srt_ncst_params)
            ultra_srt_ncst_response.raise_for_status()
            logging.info(f"초단기실황 API 응답: {ultra_srt_ncst_response.text}")
            ultra_srt_ncst_data = ultra_srt_ncst_response.json()

            if 'response' not in ultra_srt_ncst_data or 'body' not in ultra_srt_ncst_data['response']:
                raise ValueError("초단기실황 API 응답 형식이 올바르지 않습니다.")

            items = ultra_srt_ncst_data["response"]["body"]["items"]["item"]
            current_weather = {}
            for item in items:
                current_weather[item["category"]] = item["obsrValue"]

            # 현재 날씨 정보
            temp = float(current_weather.get("T1H", "N/A"))
            humidity = int(current_weather.get("REH", "N/A"))
            rain = float(current_weather.get("RN1", "0"))

            # 날씨 상태 결정
            pty = int(current_weather.get("PTY", "0"))
            weather_status = "맑음"
            if pty == 1:
                weather_status = "비"
            elif pty == 2:
                weather_status = "비/눈"
            elif pty == 3:
                weather_status = "눈"
            elif pty == 4:
                weather_status = "소나기"

            weather_info = f"현재 날씨는 {weather_status}입니다. "
            weather_info += f"기온은 {self.format_decimal(temp)}도, 습도는 {humidity}%, "

            if rain > 0:
                weather_info += f"현재 강수량은 {self.format_decimal(rain)}밀리미터 입니다."

            # 단기예보 데이터
            vilage_fcst_url = f"{self.base_url}/getVilageFcst"
            vilage_fcst_params = {
                "serviceKey": self.api_key,
                "pageNo": "1",
                "numOfRows": "1000",
                "dataType": "JSON",
                "base_date": base_date,
                "base_time": base_time,
                "nx": str(nx),
                "ny": str(ny),
            }

            vilage_fcst_response = requests.get(vilage_fcst_url, params=vilage_fcst_params)
            vilage_fcst_response.raise_for_status()
            logging.info(f"단기예보 API 응답: {vilage_fcst_response.text}")
            vilage_fcst_data = vilage_fcst_response.json()

            if vilage_fcst_data["response"]["header"]["resultCode"] == "00":
                items = vilage_fcst_data["response"]["body"]["items"]["item"]
                forecast = {}
                for item in items:
                    if item["category"] not in forecast:
                        forecast[item["category"]] = []
                    forecast[item["category"]].append({
                        "fcstDate": item["fcstDate"],
                        "fcstTime": item["fcstTime"],
                        "fcstValue": item["fcstValue"]
                    })

                today = now.strftime("%Y%m%d")
                tmx = max([float(item["fcstValue"]) for item in forecast.get("TMX", []) if item["fcstDate"] == today] or [float('-inf')])
                tmn = min([float(item["fcstValue"]) for item in forecast.get("TMN", []) if item["fcstDate"] == today] or [float('inf')])
                pop = max([int(item["fcstValue"]) for item in forecast.get("POP", []) if item["fcstDate"] == today] or [0])

                if tmx != float('-inf') and tmn != float('inf'):
                    weather_info += f"오늘의 최고 기온은 {self.format_decimal(tmx)}도, 최저 기온은 {self.format_decimal(tmn)}도입니다. "
                elif tmx != float('-inf'):
                    weather_info += f"오늘의 최고 기온은 {self.format_decimal(tmx)}도입니다. "
                elif tmn != float('inf'):
                    weather_info += f"오늘의 최저 기온은 {self.format_decimal(tmn)}도입니다. "

                weather_info += f"강수 확률은 {pop}%입니다."
            else:
                weather_info += "최고/최저 기온과 강수 확률 정보는 현재 이용할 수 없습니다."

            return weather_info

        except requests.exceptions.RequestException as e:
            logging.error(f"날씨 정보 요청 오류: {str(e)}")
            return "날씨 정보를 가져오는 데 실패했습니다."
        except ValueError as e:
            logging.error(f"날씨 정보 처리 오류: {str(e)}")
            return "날씨 정보를 처리하는 데 실패했습니다."
        except Exception as e:
            logging.error(f"예상치 못한 오류 발생: {str(e)}", exc_info=True)
            return "날씨 정보를 가져오는 중 오류가 발생했습니다."
