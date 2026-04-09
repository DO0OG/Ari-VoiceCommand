import os
import tempfile
import threading
import unittest


from agent.skill_manager import SkillManager


class SkillManagerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
