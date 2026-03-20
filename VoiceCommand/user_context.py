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
            "user_bio": {
                "name": "사용자",
                "location": "",
                "interests": [],
                "memos": []
            },
            "facts": {},  # 사용자에 대한 단편적 사실들 (예: "커피를 좋아함": "2025-02-21")
            "command_frequency": {},  # 명령어 사용 빈도
            "command_sequences": {},  # 명령어 연속 사용 패턴 (예: "날씨" -> ["유튜브"])
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
        """명령어 사용 기록 및 패턴 학습"""
        # 연속성 기록 (패턴 학습)
        if self.context["last_commands"]:
            last_cmd = self.context["last_commands"][-1]["command"]
            if last_cmd != command_type:
                if last_cmd not in self.context["command_sequences"]:
                    self.context["command_sequences"][last_cmd] = {}
                if command_type not in self.context["command_sequences"][last_cmd]:
                    self.context["command_sequences"][last_cmd][command_type] = 0
                self.context["command_sequences"][last_cmd][command_type] += 1

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
        if len(self.context["time_patterns"][time_slot]) > 20:
            self.context["time_patterns"][time_slot] = \
                self.context["time_patterns"][time_slot][-20:]

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

    def record_fact(self, key, value):
        """사용자에 대한 사실 기록"""
        self.context["facts"][key] = {
            "value": value,
            "updated_at": datetime.now().isoformat()
        }
        if len(self.context["facts"]) > 100:
            sorted_keys = sorted(
                self.context["facts"].keys(),
                key=lambda k: self.context["facts"][k].get("updated_at", "")
            )
            for old_key in sorted_keys[:len(self.context["facts"]) - 100]:
                del self.context["facts"][old_key]
        self.save_context()

    def update_bio(self, field, value):
        """기본 정보 업데이트 (이름, 관심사 등)"""
        if field in self.context["user_bio"]:
            if isinstance(self.context["user_bio"][field], list):
                if value not in self.context["user_bio"][field]:
                    self.context["user_bio"][field].append(value)
            else:
                self.context["user_bio"][field] = value
            self.save_context()

    def record_preference(self, category, value):
        """선호도 기록 (예: 음악 장르, 선호 온도)"""
        if category not in self.context["preferences"]:
            self.context["preferences"][category] = {}

        if value not in self.context["preferences"][category]:
            self.context["preferences"][category][value] = 0
        self.context["preferences"][category][value] += 1

        if len(self.context["preferences"][category]) > 50:
            sorted_vals = sorted(
                self.context["preferences"][category].items(),
                key=lambda x: x[1], reverse=True
            )
            self.context["preferences"][category] = dict(sorted_vals[:50])

        self.save_context()

    def get_predicted_next_commands(self):
        """현재 패턴을 바탕으로 다음 예상 명령 제안"""
        if not self.context["last_commands"]:
            return []
        
        last_cmd = self.context["last_commands"][-1]["command"]
        if last_cmd in self.context["command_sequences"]:
            candidates = sorted(
                self.context["command_sequences"][last_cmd].items(),
                key=lambda x: x[1],
                reverse=True
            )
            return [cmd for cmd, count in candidates[:2]]
        return []

    def get_context_summary(self):
        """컨텍스트 요약 (프롬프트용)"""
        summary = []

        # 기본 정보
        bio = self.context.get("user_bio", {})
        if bio.get("name") and bio["name"] != "사용자":
            summary.append(f"사용자 이름: {bio['name']}")
        
        # 사실들
        facts = self.context.get("facts", {})
        if facts:
            fact_list = [f"{k}: {v['value']}" for k, v in facts.items()]
            summary.append(f"사용자에 대한 사실: {', '.join(fact_list[:5])}")

        # 자주 사용하는 명령어
        if self.context["command_frequency"]:
            top_commands = sorted(
                self.context["command_frequency"].items(),
                key=lambda x: x[1],
                reverse=True
            )[:3]
            commands_str = ", ".join([cmd for cmd, _ in top_commands])
            summary.append(f"자주 사용하는 명령: {commands_str}")

        # 예상 다음 명령
        predictions = self.get_predicted_next_commands()
        if predictions:
            summary.append(f"패턴 기반 추천: {', '.join(predictions)}")

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
