"""학습 상태와 저장된 교훈을 보여 주는 설정 페이지."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from i18n.translator import _


def format_skill_row(skill, usage: dict) -> str:
    """스킬 성공률과 최근 사용 시각을 표시할 문자열로 만든다."""
    skill_usage = usage.get(skill.skill_id, {})
    total = int(skill_usage.get("total", 0) or 0)
    if total:
        success_rate = int(round(float(skill_usage.get("success_rate", 0)) * 100))
    else:
        total = int(skill.success_count or 0) + int(skill.fail_count or 0)
        success_rate = (
            int(round(int(skill.success_count or 0) / total * 100)) if total else None
        )

    rate_text = (
        _("{rate}%").format(rate=success_rate)
        if success_rate is not None
        else _("표본 없음")
    )
    last_used = _format_last_used(str(skill_usage.get("last_used", "") or ""))
    status = _("사용 중") if skill.enabled else _("꺼짐")
    return _(
        "{name} · 성공률 {rate} · 마지막 사용: {last_used} · 상태: {status}"
    ).format(
        name=skill.name,
        rate=rate_text,
        last_used=last_used,
        status=status,
    )


def _format_last_used(timestamp: str) -> str:
    if not timestamp:
        return _("기록 없음")
    try:
        return datetime.fromisoformat(timestamp).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return timestamp


class _LearningSettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        skills_group = QGroupBox(_("학습 스킬"))
        skills_layout = QVBoxLayout(skills_group)
        self.skill_list = QListWidget()
        self.skill_list.setMaximumHeight(150)
        skills_layout.addWidget(self.skill_list)
        self.disable_skill_button = QPushButton(_("이 스킬 끄기"))
        self.disable_skill_button.setEnabled(False)
        self.disable_skill_button.clicked.connect(self._disable_selected_skill)
        skills_layout.addWidget(self.disable_skill_button)
        layout.addWidget(skills_group)

        lessons_group = QGroupBox(_("활성 교훈"))
        lessons_layout = QVBoxLayout(lessons_group)
        self.lesson_list = QListWidget()
        self.lesson_list.setMaximumHeight(150)
        lessons_layout.addWidget(self.lesson_list)
        self.delete_lesson_button = QPushButton(_("이 교훈 삭제"))
        self.delete_lesson_button.setEnabled(False)
        self.delete_lesson_button.clicked.connect(self._delete_selected_lesson)
        lessons_layout.addWidget(self.delete_lesson_button)
        layout.addWidget(lessons_group)

        self.policies_group = QGroupBox(_("최근 정책 기록"))
        self.policies_layout = QVBoxLayout(self.policies_group)
        layout.addWidget(self.policies_group)

        self.component_group = QGroupBox(_("컴포넌트 lift"))
        self.component_layout = QVBoxLayout(self.component_group)
        self.component_group.setVisible(False)
        layout.addWidget(self.component_group)
        layout.addStretch(1)

        self.skill_list.currentItemChanged.connect(self._update_skill_button)
        self.lesson_list.currentItemChanged.connect(self._update_lesson_button)
        self._refresh()

    def _refresh(self) -> None:
        from agent.episode_memory import get_episode_memory
        from agent.learning_metrics import get_learning_metrics
        from agent.skill_library import get_skill_library
        from agent.strategy_memory import get_strategy_memory

        skill_library = get_skill_library()
        strategy_memory = get_strategy_memory()
        usage = strategy_memory.get_skill_usage()
        self.skill_list.clear()
        for skill in skill_library.skills:
            item = QListWidgetItem(format_skill_row(skill, usage))
            item.setData(Qt.UserRole, skill.skill_id)
            item.setData(Qt.UserRole + 1, bool(skill.enabled))
            self.skill_list.addItem(item)
        if not skill_library.skills:
            self.skill_list.addItem(QListWidgetItem(_("사용 스킬이 없습니다.")))

        lessons = strategy_memory.get_recent_lessons()
        self.lesson_list.clear()
        for record in lessons:
            item = QListWidgetItem(record.lesson)
            item.setData(Qt.UserRole, record.record_id)
            self.lesson_list.addItem(item)
        if not lessons:
            self.lesson_list.addItem(QListWidgetItem(_("교훈이 없습니다.")))

        self._refresh_policies(get_episode_memory().get_recent_episodes(10))
        self._refresh_component_lift(get_learning_metrics())
        self._update_skill_button(self.skill_list.currentItem(), None)
        self._update_lesson_button(self.lesson_list.currentItem(), None)

    def _refresh_policies(self, episodes: list) -> None:
        while self.policies_layout.count():
            item = self.policies_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        policies = []
        for episode in reversed(episodes):
            policy = str(episode.policy_summary or "").strip()
            if policy and policy not in policies:
                policies.append(policy)
            if len(policies) >= 5:
                break
        for policy in policies:
            label = QLabel(policy)
            label.setWordWrap(True)
            self.policies_layout.addWidget(label)
        self.policies_group.setVisible(bool(policies))

    def _refresh_component_lift(self, metrics) -> None:
        while self.component_layout.count():
            item = self.component_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        lines = []
        for row in metrics.get_component_diagnostics():
            component = metrics.get_component(row["name"])
            if not component.trial_total_with or not component.trial_total_holdout:
                continue
            lift = int(round(component.lift * 100))
            lines.append(_("{component}: {lift:+d}%p").format(
                component=component.name,
                lift=lift,
            ))
        for line in lines:
            self.component_layout.addWidget(QLabel(line))
        self.component_group.setVisible(bool(lines))

    def _update_skill_button(self, item, previous) -> None:
        del previous
        self.disable_skill_button.setEnabled(
            item is not None
            and bool(item.data(Qt.UserRole))
            and bool(item.data(Qt.UserRole + 1))
        )

    def _update_lesson_button(self, item, previous) -> None:
        del previous
        self.delete_lesson_button.setEnabled(
            item is not None and bool(item.data(Qt.UserRole))
        )

    def _disable_selected_skill(self) -> None:
        item = self.skill_list.currentItem()
        if item is None:
            return
        from agent.skill_library import get_skill_library

        get_skill_library().deprecate_skill(str(item.data(Qt.UserRole) or ""))
        self._refresh()

    def _delete_selected_lesson(self) -> None:
        item = self.lesson_list.currentItem()
        if item is None:
            return
        from agent.strategy_memory import get_strategy_memory

        get_strategy_memory().delete_lesson(str(item.data(Qt.UserRole) or ""))
        self._refresh()
