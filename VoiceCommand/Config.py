"""
간단한 로컬 설정 관리
"""
import json
import logging


def use_api(key_name):
    """로컬 설정에서 API 키 읽기"""
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
        return config.get(key_name)
    except FileNotFoundError:
        logging.warning(f"설정 파일을 찾을 수 없습니다: {key_name}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"설정 파일 파싱 오류: {e}")
        return None
    except Exception as e:
        logging.error(f"설정 로드 중 예외 발생: {e}")
        return None
