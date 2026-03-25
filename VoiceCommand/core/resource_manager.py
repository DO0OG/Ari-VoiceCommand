"""PyInstaller 번들 리소스 관리"""
import os
import sys
import shutil
import logging

# 앱 이름 (appdata 폴더명)
APP_NAME = "Ari"


class ResourceManager:
    _app_data_dir = None

    @staticmethod
    def _project_root() -> str:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @staticmethod
    def get_app_data_dir() -> str:
        """사용자 데이터 디렉토리 반환.
        - 배포(frozen): %appdata%\\Ari
        - 개발: 프로젝트 루트
        """
        if ResourceManager._app_data_dir:
            return ResourceManager._app_data_dir

        if getattr(sys, 'frozen', False):
            base = os.path.join(
                os.environ.get('APPDATA', os.path.expanduser('~')),
                APP_NAME
            )
        else:
            base = ResourceManager._project_root()

        os.makedirs(base, exist_ok=True)
        ResourceManager._app_data_dir = base
        return base

    @staticmethod
    def get_bundle_path(relative_path: str) -> str:
        """번들(읽기전용) 리소스 경로 반환"""
        if getattr(sys, 'frozen', False):
            if hasattr(sys, '_MEIPASS'):
                # PyInstaller: 임시 압축 해제 폴더
                base = sys._MEIPASS
            else:
                # Nuitka standalone: 데이터 파일이 exe 옆에 위치
                base = os.path.dirname(os.path.abspath(sys.executable))
            return os.path.join(base, relative_path)
        return os.path.join(ResourceManager._project_root(), relative_path)

    @staticmethod
    def get_writable_path(relative_path: str) -> str:
        """쓰기 가능한 사용자 데이터 경로 반환"""
        return os.path.join(ResourceManager.get_app_data_dir(), relative_path)

    @staticmethod
    def extract_resources():
        """첫 실행 시 번들 리소스를 appdata로 추출"""
        if not getattr(sys, 'frozen', False):
            return  # 개발 모드에서는 불필요

        resources = [
            ('images', 'images'),
            ('theme', 'theme'),
            ('plugins', 'plugins'),
            ('DNFBitBitv2.ttf', 'DNFBitBitv2.ttf'),
            ('icon.png', 'icon.png'),
            ('reference.wav', 'reference.wav'),
        ]

        for src_name, dest_name in resources:
            source = ResourceManager.get_bundle_path(src_name)
            destination = ResourceManager.get_writable_path(dest_name)

            if os.path.exists(destination):
                continue  # 이미 추출됨

            try:
                if os.path.isdir(source):
                    shutil.copytree(source, destination)
                    logging.info(f"✓ 폴더 추출: {dest_name}")
                elif os.path.exists(source):
                    os.makedirs(os.path.dirname(destination), exist_ok=True)
                    shutil.copy2(source, destination)
                    logging.info(f"✓ 파일 추출: {dest_name}")
            except Exception as e:
                logging.error(f"리소스 추출 실패 {src_name}: {e}")

    @staticmethod
    def get_images_dir() -> str:
        """이미지 디렉토리 경로 반환 (appdata > 번들 순)"""
        writable = ResourceManager.get_writable_path('images')
        if os.path.exists(writable):
            return writable
        return ResourceManager.get_bundle_path('images')

    @staticmethod
    def get_theme_dir() -> str:
        """테마 디렉토리 경로 반환 (appdata > 프로젝트/번들 순)."""
        writable = ResourceManager.get_writable_path("theme")
        if os.path.exists(writable):
            return writable
        return ResourceManager.get_bundle_path("theme")

    @staticmethod
    def ensure_theme_files() -> str:
        """테마 JSON 파일을 사용자 편집 가능한 위치에 보장합니다."""
        writable = ResourceManager.get_writable_path("theme")
        source = ResourceManager.get_bundle_path("theme")
        os.makedirs(writable, exist_ok=True)

        try:
            if os.path.isdir(source):
                for name in os.listdir(source):
                    src = os.path.join(source, name)
                    dst = os.path.join(writable, name)
                    if os.path.isdir(src):
                        if not os.path.exists(dst):
                            shutil.copytree(src, dst)
                    elif os.path.isfile(src) and not os.path.exists(dst):
                        shutil.copy2(src, dst)
        except Exception as e:
            logging.warning(f"테마 파일 준비 실패: {e}")
        return writable

    @staticmethod
    def ensure_plugin_files() -> str:
        """플러그인 템플릿 파일을 사용자 편집 가능한 위치에 보장합니다."""
        writable = ResourceManager.get_writable_path("plugins")
        source = ResourceManager.get_bundle_path("plugins")
        os.makedirs(writable, exist_ok=True)

        try:
            if os.path.isdir(source):
                for name in os.listdir(source):
                    src = os.path.join(source, name)
                    dst = os.path.join(writable, name)
                    if os.path.isdir(src):
                        if not os.path.exists(dst):
                            shutil.copytree(src, dst)
                    elif os.path.isfile(src) and not os.path.exists(dst):
                        shutil.copy2(src, dst)
        except Exception as e:
            logging.warning(f"플러그인 파일 준비 실패: {e}")
        return writable
