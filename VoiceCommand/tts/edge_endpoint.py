"""edge-tts가 쓰는 합성 주소 보정."""

_LEGACY_HOST = "speech.platform.bing.com"


def use_current_edge_endpoint() -> None:
    """예전 합성 주소가 403을 반환해(rany2/edge-tts#490) 새 주소로 바꾼다."""
    # ponytail: 라이브러리 내부 상수를 덮어쓴다. 수정된 edge-tts가 배포되면
    # requirements.txt의 하한을 올리고 이 모듈을 지운다.
    try:
        from edge_tts import communicate
        from edge_tts.constants import TRUSTED_CLIENT_TOKEN
    except ImportError:
        return
    if _LEGACY_HOST in getattr(communicate, "WSS_URL", ""):
        communicate.WSS_URL = (
            "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"
            f"?Ocp-Apim-Subscription-Key={TRUSTED_CLIENT_TOKEN}"
        )
