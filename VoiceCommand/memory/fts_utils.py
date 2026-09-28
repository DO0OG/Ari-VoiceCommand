"""FTS5 검색 질의 유틸리티."""

_EDGE_PUNCTUATION = '"\'`.,:;()[]{}'


def split_fts_tokens(text: str) -> list[str]:
    """공백 토큰의 바깥 문장 부호를 정리한다."""
    tokens = [token.strip(_EDGE_PUNCTUATION) for token in str(text or "").split()[:12]]
    return [token for token in tokens if token]


def build_fts_query(text: str) -> str:
    """공백 토큰을 안전한 FTS5 구문으로 변환한다."""
    tokens = split_fts_tokens(text)
    if not tokens:
        return '""'
    quoted = ['"' + token.replace('"', '""') + '"' for token in tokens]
    return " OR ".join(quoted)
