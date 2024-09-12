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
            base = os.path.dirname(os.path.abspath(__file__))

        os.makedirs(base, exist_ok=True)
        ResourceManager._app_data_dir = base
        return base

    @staticmethod
    def get_bundle_path(relative_path: str) -> str:
        """번들(읽기전용) 리소스 경로 반환"""
        if getattr(sys, 'frozen', False):
            return os.path.join(sys._MEIPASS, relative_path)
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

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
