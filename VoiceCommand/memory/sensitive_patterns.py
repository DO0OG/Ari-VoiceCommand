"""기억 추출에서 제외할 민감 정보 규칙."""

import re

SENSITIVE_PATTERNS = (
    re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)"),
    re.compile(r"(?<!\d)\d{6}-[1-8]\d{6}(?!\d)"),
    re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
    re.compile(
        r"(?i)(?:계좌(?:\s*번호)?|은행\s*계좌|account|bank\s*account|口座(?:番号)?)"
        r"(?:\s*(?:번호|number|no\.?|#))?\s*(?:is\s+|(?:는|은|は)\s*)?"
        r"[:：#]?\s*\d(?:[ -]?\d){6,18}\d"
    ),
)

_SENSITIVE_KEYWORDS = re.compile(
    r"(?i)\b(?:health|medical|diagnosis|diagnosed|disease|illness|medication|"
    r"prescription|treatment|surgery|mental health|depression|anxiety|cancer|"
    r"diabetes|hypertension|crime|criminal|conviction|arrest|prosecuted|felony|"
    r"misdemeanor|offense|criminal record)\b|"
    r"건강|질병|병력|진단|투약|복용약|처방|치료|수술|정신건강|우울증|불안장애|암|고혈압|당뇨|의료|"
    r"범죄|전과|형사처벌|기소|체포|유죄|범인|수사기록|범죄기록|"
    r"健康|病気|疾患|診断|服薬|処方|治療|手術|精神疾患|うつ病|不安障害|がん|糖尿病|高血圧|医療|"
    r"犯罪|前科|刑事処罰|起訴|逮捕|有罪|犯人|捜査記録"
)


def is_sensitive_memory_text(text: str) -> bool:
    """민감 숫자 패턴이나 건강·범죄 용어가 있는지 확인한다."""
    candidate = str(text or "")
    return any(pattern.search(candidate) for pattern in SENSITIVE_PATTERNS) or bool(
        _SENSITIVE_KEYWORDS.search(candidate)
    )
