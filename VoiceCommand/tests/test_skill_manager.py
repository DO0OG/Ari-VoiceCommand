import os
import tempfile
import threading
import unittest
from unittest.mock import patch


from agent.skill_manager import SkillManager, reset_skill_manager


class SkillManagerTests(unittest.TestCase):
    def tearDown(self):
        reset_skill_manager()

    def _make_manager(self, skills_dir: str) -> SkillManager:
        manager = SkillManager.__new__(SkillManager)
        manager._skills = {}
        manager._lock = threading.RLock()
        manager.skills_dir = skills_dir
        return manager

    def test_load_all_parses_frontmatter_scripts_and_mcp_endpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = os.path.join(temp_dir, "coupang-product-search")
            scripts_dir = os.path.join(skill_dir, "scripts")
            os.makedirs(scripts_dir, exist_ok=True)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write(
                    """---
name: coupang-product-search
description: 쿠팡 상품 검색 스킬
triggers:
  - 쿠팡
  - 상품 검색
---

이 스킬은 MCP 프로토콜을 사용합니다.
endpoint: https://example.com/mcp
tool: search_coupang_products
"""
                )

            manager = self._make_manager(temp_dir)
            loaded = manager.load_all()

            self.assertEqual(len(loaded), 1)
            skill = loaded[0]
            self.assertEqual(skill.name, "coupang-product-search")
            self.assertEqual(skill.description, "쿠팡 상품 검색 스킬")
            self.assertIn("쿠팡", skill.trigger_keywords)
            self.assertEqual(skill.mcp_endpoint, "https://example.com/mcp")
            self.assertEqual(skill.scripts_dir, scripts_dir)
            self.assertTrue(skill.is_mcp_skill)

    def test_build_match_context_includes_mcp_prompt_and_required_tool(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = os.path.join(temp_dir, "coupang-product-search")
            os.makedirs(skill_dir, exist_ok=True)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write(
                    """---
name: coupang-product-search
triggers: [쿠팡, 모니터]
---

쿠팡 상품 검색 결과를 가져옵니다.
https://example.com/mcp
search_coupang_products
"""
                )

            manager = self._make_manager(temp_dir)
            manager.load_all()

            context = manager.build_match_context("쿠팡에서 4K 모니터 찾아줘")

            self.assertEqual(context["preferred_tool"], "mcp_call")
            self.assertIn("mcp_call", context["required_tool_names"])
            self.assertIn("[사용 가능한 스킬]", context["prompt"])
            self.assertIn("https://example.com/mcp", context["prompt"])

    def test_load_all_parses_search_skill_type_and_language_specific_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = os.path.join(temp_dir, "lck-analytics")
            os.makedirs(skill_dir, exist_ok=True)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write(
                    """---
name: lck-analytics
skill_type: search
description: 기본 설명
description_en: English description
triggers_en:
  - LCK
  - match result
search_query_template_en: LCK {date} match results
---

body
"""
                )

            manager = self._make_manager(temp_dir)
            with patch("i18n.translator.get_language", return_value="en"):
                loaded = manager.load_all()

            self.assertEqual(len(loaded), 1)
            skill = loaded[0]
            self.assertEqual(skill.skill_type, "search")
            self.assertEqual(skill.description, "English description")
            self.assertIn("match result", skill.trigger_keywords)
            self.assertEqual(skill.search_query_templates["en"], "LCK {date} match results")

    def test_mcp_endpoint_overrides_declared_skill_type_to_mcp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = os.path.join(temp_dir, "mixed-skill")
            os.makedirs(skill_dir, exist_ok=True)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write(
                    """---
name: mixed-skill
skill_type: script
---

endpoint: https://example.com/mcp
tool: search_items
"""
                )

            manager = self._make_manager(temp_dir)
            skill = manager.load_all()[0]

            self.assertEqual(skill.skill_type, "mcp")

    def test_builtin_overrides_fill_search_defaults_for_known_runtime_skills(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = os.path.join(temp_dir, "lck-analytics")
            os.makedirs(skill_dir, exist_ok=True)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write(
                    """---
name: lck-analytics
---

body
"""
                )

            manager = self._make_manager(temp_dir)
            with patch("i18n.translator.get_language", return_value="en"):
                skill = manager.load_all()[0]

            self.assertEqual(skill.skill_type, "search")
            self.assertEqual(skill.description, "Retrieve LCK match results, standings, and ban/pick analysis from Riot official LoL Esports data.")
            self.assertEqual(skill.search_query_templates["en"], "LCK {date} match results")

    def test_build_match_context_sets_force_web_search_and_query_template(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = os.path.join(temp_dir, "lck-analytics")
            os.makedirs(skill_dir, exist_ok=True)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write(
                    """---
name: lck-analytics
skill_type: search
triggers_ja:
  - LCK
  - 試合結果
search_query_template_ja: LCK {date} 試合結果
---

body
"""
                )

            manager = self._make_manager(temp_dir)
            with patch("i18n.translator.get_language", return_value="ja"):
                manager.load_all()
                context = manager.build_match_context("LCK の試合結果を教えて")

            self.assertTrue(context["force_web_search"])
            self.assertFalse(context["escalate_to_agent"])
            self.assertEqual(context["preferred_tool"], "web_search")
            self.assertIn("web_search", context["required_tool_names"])
            self.assertEqual(context["search_query_template"], "LCK {date} 試合結果")

    def test_build_match_context_sets_escalate_to_agent_for_script_skill(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = os.path.join(temp_dir, "joseon-sillok-search")
            os.makedirs(skill_dir, exist_ok=True)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write(
                    """---
name: joseon-sillok-search
skill_type: script
triggers: [실록, 사료]
---

body
"""
                )

            manager = self._make_manager(temp_dir)
            manager.load_all()
            context = manager.build_match_context("실록에서 세종 기록 찾아줘")

            self.assertFalse(context["force_web_search"])
            self.assertTrue(context["escalate_to_agent"])
            self.assertEqual(context["search_query_template"], "")

    def test_builtin_overrides_match_representative_korean_queries(self):
        cases = {
            "coupang-product-search": "쿠팡에서 에어팟 찾아줘",
            "korean-law-search": "개인정보보호법 조문 알려줘",
            "seoul-subway-arrival": "강남역 지하철 도착 정보",
            "delivery-tracking": "쿠팡 택배 운송장 조회",
            "korean-spell-check": "한국 맞춤법 검사해줘",
            "ktx-booking": "KTX 서울 부산 예매",
            "srt-booking": "SRT 수서 부산 예약",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            for skill_name in cases:
                skill_dir = os.path.join(temp_dir, skill_name)
                os.makedirs(skill_dir, exist_ok=True)
                with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
                    handle.write(f"---\nname: {skill_name}\n---\n\nbody\n")

            manager = self._make_manager(temp_dir)
            with patch("i18n.translator.get_language", return_value="ko"):
                manager.load_all()
                for expected, query in cases.items():
                    matched = [skill.name for skill in manager.build_match_context(query)["skills"]]
                    self.assertIn(expected, matched, msg=f"{expected} not matched for query={query!r}: {matched}")

    def test_fallback_keywords_use_description_when_triggers_are_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = os.path.join(temp_dir, "future-skill")
            os.makedirs(skill_dir, exist_ok=True)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write(
                    """---
name: future-skill
description_ko: 서울 버스 도착 정보를 조회한다.
---

body
"""
                )

            manager = self._make_manager(temp_dir)
            with patch("i18n.translator.get_language", return_value="ko"):
                manager.load_all()
                matched = [skill.name for skill in manager.build_match_context("서울 버스 도착 정보 알려줘")["skills"]]

            self.assertIn("future-skill", matched)


if __name__ == "__main__":
    unittest.main()
