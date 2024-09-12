"""
사용자 컨텍스트 학습 및 관리
"""
import json
import os
import logging
from datetime import datetime
from collections import defaultdict


class UserContextManager:
    """사용자 행동 패턴 및 컨텍스트 관리"""

    def __init__(self, context_file="user_context.json"):
        self.context_file = context_file
        self.context = self.load_context()

    def load_context(self):
        """컨텍스트 로드"""
        if os.path.exists(self.context_file):
            try:
                with open(self.context_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass

        # 기본 구조
        return {
            "command_frequency": {},  # 명령어 사용 빈도
            "time_patterns": {},  # 시간대별 활동
            "preferences": {},  # 선호도 (음악 장르, 온도 등)
            "last_commands": [],  # 최근 명령어 (최대 50개)
            "conversation_topics": {}  # 대화 주제 빈도
        }

    def save_context(self):
        """컨텍스트 저장"""
        try:
            with open(self.context_file, 'w', encoding='utf-8') as f:
                json.dump(self.context, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"컨텍스트 저장 실패: {e}")

    def record_command(self, command_type, params=None):
        """명령어 사용 기록"""
        # 빈도 업데이트
        if command_type not in self.context["command_frequency"]:
            self.context["command_frequency"][command_type] = 0
        self.context["command_frequency"][command_type] += 1

        # 시간대별 패턴
        hour = datetime.now().hour
        time_slot = f"{hour:02d}:00"
        if time_slot not in self.context["time_patterns"]:
            self.context["time_patterns"][time_slot] = []
        self.context["time_patterns"][time_slot].append(command_type)

        # 최근 명령어
        self.context["last_commands"].append({
            "command": command_type,
            "params": params,
            "timestamp": datetime.now().isoformat()
        })

        # 최대 50개로 제한
        if len(self.context["last_commands"]) > 50:
            self.context["last_commands"] = self.context["last_commands"][-50:]

        self.save_context()

    def record_preference(self, category, value):
        """선호도 기록 (예: 음악 장르, 선호 온도)"""
        if category not in self.context["preferences"]:
            self.context["preferences"][category] = {}

        if value not in self.context["preferences"][category]:
            self.context["preferences"][category][value] = 0
        self.context["preferences"][category][value] += 1

        self.save_context()

    def get_context_summary(self):
        """컨텍스트 요약 (프롬프트용)"""
        summary = []

        # 자주 사용하는 명령어
        if self.context["command_frequency"]:
            top_commands = sorted(
                self.context["command_frequency"].items(),
                key=lambda x: x[1],
                reverse=True
            )[:3]
            commands_str = ", ".join([cmd for cmd, _ in top_commands])
            summary.append(f"자주 사용하는 명령: {commands_str}")

        # 현재 시간대 활동
        hour = datetime.now().hour
        time_slot = f"{hour:02d}:00"
        if time_slot in self.context["time_patterns"]:
            recent = self.context["time_patterns"][time_slot][-3:]
            if recent:
                summary.append(f"이 시간대 활동: {', '.join(set(recent))}")

        # 선호도
        if self.context["preferences"]:
            prefs = []
            for category, values in self.context["preferences"].items():
                if values:
                    top_pref = max(values.items(), key=lambda x: x[1])
                    prefs.append(f"{category}: {top_pref[0]}")
            if prefs:
                summary.append(f"선호: {', '.join(prefs)}")

        return "\n".join(summary) if summary else ""


# 싱글톤 인스턴스
_context_manager = None

def get_context_manager():
    """UserContextManager 싱글톤"""
    global _context_manager
    if _context_manager is None:
        _context_manager = UserContextManager()
    return _context_manager
