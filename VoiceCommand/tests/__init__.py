"""Ari regression tests."""

import atexit
import importlib
import os
import shutil
import tempfile

# 테스트는 실제 사용자 런타임 디렉터리를 건드리면 안 된다.  설정 파일과 사용자
# 컨텍스트가 실제로 덮어써진 적이 있어 경로 자체를 임시 디렉터리로 돌린다.
# 패키지 초기화는 테스트 모듈보다 먼저 실행되므로 ResourceManager가 경로
# 캐시를 채우기 전에 적용된다.  conftest가 아니라 여기에 두는 이유는
# unittest discover 가 conftest 를 읽지 않기 때문이다.
_RUNTIME_DIR = tempfile.mkdtemp(prefix="ari_test_runtime_")
os.environ["ARI_APP_DATA_DIR"] = _RUNTIME_DIR
atexit.register(shutil.rmtree, _RUNTIME_DIR, ignore_errors=True)

# 테스트가 실제 임베딩 모델(약 130MB)을 내려받지 않도록 Hugging Face를 오프라인으로 둔다.
os.environ["HF_HUB_OFFLINE"] = "1"

# Main.py처럼 Qt보다 onnxruntime을 먼저 불러 DLL 초기화 실패를 피한다.
try:
    importlib.import_module("onnxruntime")
except ImportError:
    pass
