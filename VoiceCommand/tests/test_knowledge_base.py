from memory.knowledge_base import KnowledgeBase


def test_knowledge_base_upsert_query_prompt(tmp_path):
    db = tmp_path / "kb.db"
    kb = KnowledgeBase(str(db))
    row_id = kb.upsert("사용자", "좋아하는것", "딸기 케이크", 0.9, "user_stated")
    assert row_id > 0
    results = kb.query("딸기", top_k=3)
    assert results
    assert results[0]["entity"] == "사용자"
    assert "딸기 케이크" in kb.prompt_for("케이크")
