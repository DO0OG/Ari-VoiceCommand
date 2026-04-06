"""
Selenium 드라이버의 DOM 상태를 분석하고 다음 액션을 제안한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class DomState:
    url: str
    title: str
    domain: str
    login_detected: bool
    logged_in: bool
    forms: list[dict] = field(default_factory=list)
    nav_links: list[dict] = field(default_factory=list)
    main_buttons: list[dict] = field(default_factory=list)
    data_tables: list[dict] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    page_summary: str = ""


def analyse_dom(driver) -> DomState:
    try:
        from selenium.webdriver.common.by import By
    except Exception:
        return DomState("", "", "", False, False, page_summary="")

    url = str(getattr(driver, "current_url", "") or "")
    title = str(getattr(driver, "title", "") or "")
    domain = urlparse(url).netloc.lower()

    login_detected = bool(driver.find_elements(By.CSS_SELECTOR, "input[type='password']"))

    nav_links = []
    for link in driver.find_elements(By.CSS_SELECTOR, "nav a, header a")[:20]:
        text = (link.text or "").strip()
        href = str(link.get_attribute("href") or "")
        if text or href:
            nav_links.append({"text": text, "href": href})

    nav_text = " ".join((item.get("text", "") or "").lower() for item in nav_links)
    logged_in = (not login_detected) and any(
        token in nav_text for token in ("로그아웃", "logout", "sign out", "내 계정", "my account")
    )

    forms = []
    for form in driver.find_elements(By.CSS_SELECTOR, "form"):
        inputs = []
        for element in form.find_elements(By.CSS_SELECTOR, "input, textarea, select")[:12]:
            inputs.append(
                {
                    "name": str(element.get_attribute("name") or ""),
                    "type": str(element.get_attribute("type") or ""),
                    "id": str(element.get_attribute("id") or ""),
                }
            )
        forms.append({"action": str(form.get_attribute("action") or ""), "method": str(form.get_attribute("method") or "get").lower(), "inputs": inputs})

    main_buttons = []
    for button in driver.find_elements(By.CSS_SELECTOR, "button, input[type='submit'], a.btn")[:15]:
        main_buttons.append({"text": (button.text or button.get_attribute("value") or "").strip(), "id": str(button.get_attribute("id") or ""), "class": str(button.get_attribute("class") or "")})

    data_tables = []
    for table in driver.find_elements(By.CSS_SELECTOR, "table")[:5]:
        headers = [(header.text or "").strip() for header in table.find_elements(By.CSS_SELECTOR, "th")[:10] if (header.text or "").strip()]
        rows = table.find_elements(By.CSS_SELECTOR, "tbody tr, tr")
        data_tables.append({"id": str(table.get_attribute("id") or ""), "headers": headers, "row_count": max(len(rows) - (1 if headers else 0), 0)})

    alerts = []
    for el in driver.find_elements(By.CSS_SELECTOR, ".alert, .error, .success, .toast, [role='alert']")[:10]:
        text = (el.text or "").strip()
        if text:
            alerts.append(text)

    headings = [(el.text or "").strip() for el in driver.find_elements(By.CSS_SELECTOR, "h1, h2")[:2] if (el.text or "").strip()]
    page_summary = f"{title} | {' / '.join(headings)}".strip(" |")[:50]
    return DomState(url, title, domain, login_detected, logged_in, forms, nav_links, main_buttons, data_tables, alerts, page_summary)


def suggest_next_actions(state: DomState | dict, goal_hint: str = "") -> list[dict]:
    if isinstance(state, dict):
        state = DomState(**{**DomState("", "", "", False, False).__dict__, **state})

    suggestions: list[dict] = []
    goal_lower = (goal_hint or "").lower()

    if state.login_detected:
        suggestions.append({"type": "read", "selector": "form", "description": "로그인 폼 구조 확인", "priority": 1.0})
    if state.logged_in and state.data_tables:
        suggestions.append({"type": "read", "selector": "table", "description": "표 데이터 읽기", "priority": 0.9})
    for alert in state.alerts:
        if any(token in alert.lower() for token in ("error", "실패", "오류", "invalid")):
            suggestions.append({"type": "read", "selector": ".alert, .error, .toast, [role='alert']", "description": "오류 메시지 읽기", "priority": 0.8})
            break
    if state.logged_in:
        for item in state.nav_links[:5]:
            if item.get("href"):
                suggestions.append({"type": "navigate", "url": item["href"], "description": f"네비게이션 이동: {item.get('text', item['href'])}", "priority": 0.6})
    for button in state.main_buttons:
        text = (button.get("text") or "").strip()
        if not text:
            continue
        priority = 0.85 if any(token and token in text.lower() for token in goal_lower.split()) else 0.5
        suggestions.append({"type": "click_text", "text": text, "description": f"버튼 클릭: {text}", "priority": priority})
    if state.forms and any(token in goal_lower for token in ("submit", "전송", "등록")):
        suggestions.append({"type": "click", "selectors": ["button[type='submit']", "input[type='submit']"], "description": "폼 제출", "priority": 0.75})
    suggestions.sort(key=lambda item: float(item.get("priority", 0.0)), reverse=True)
    return suggestions[:10]


if __name__ == "__main__":
    sample = DomState(url="https://example.com", title="Example", domain="example.com", login_detected=False, logged_in=True)
    print(sample)
    print(suggest_next_actions(sample, "결과 읽어줘"))
