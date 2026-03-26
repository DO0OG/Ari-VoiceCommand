import json
import logging
import os
import re
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

from agent.execution_analysis import (
    describes_open_action,
    describes_storage_action,
    existing_paths,
    extract_artifacts,
)
from agent.ocr_helper import ocr_contains, ocr_screen

_VERIFY_CODE_PROMPT = """\
다음 목표가 실제로 달성됐는지 확인하는 파이썬 검증 코드를 작성하세요.

목표: {goal}

실행된 단계와 출력:
{steps_summary}

검증 요구사항:
1. 목표 달성 여부를 '실제 상태'로 확인하세요.
   - 파일 작업: os.path.exists(path) 등을 사용
   - 창/앱 실행: get_active_window_title(), find_window("제목"), focus_window("제목") 없는 읽기 전용 검사 활용
   - 웹 브라우저: get_browser_state(), get_browser_current_url(), 창 제목 확인
   - 다운로드: wait_for_download() 같은 상태 헬퍼는 사용 가능하되 새 다운로드를 시작하지 마세요
2. 주의: 브라우저 열기(open_url), 앱 실행(launch_app) 등 상태를 변화시키는 함수를 다시 호출하지 마세요. (읽기 전용 검증)
3. 마지막 줄에 반드시 True 또는 False를 print()로 출력하세요.
4. 예시:
   import os; print(os.path.exists(r'C:\\Users\\User\\Desktop\\test.txt'))
   또는
   title = get_active_window_title(); print('네이버' in title)

코드만 반환 (설명/주석/마크다운 금지):
"""

_RE_CODE_FENCE = re.compile(r'```(?:python)?\s*', re.IGNORECASE)


@dataclass
class VerificationResult:
    verified: bool
    method: str         # "code" | "llm" | "heuristic"
    evidence: str       # 실제 증거 텍스트
    summary_kr: str


class RealVerifier:
    """검증 코드를 실제로 실행하여 목표 달성 여부를 확인합니다."""

    def __init__(self, llm_provider, executor):
        self.llm = llm_provider
        self.executor = executor

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def verify(self, goal: str, step_results: list) -> VerificationResult:
        """휴리스틱 → OCR → 코드 → LLM 순으로 검증한다."""
        # 1. 휴리스틱 검증 (빠른 판단)
        heuristic = self._heuristic_verify(goal, step_results)
        if heuristic is not None:
            return heuristic

        # 2. OCR 기반 화면 검증
        ocr_result = self._ocr_verify(goal, step_results)
        if ocr_result is not None:
            return ocr_result

        # 3. 코드 기반 실제 상태 검증 (Phase 2.2 핵심)
        code = self._generate_verification_code(goal, step_results)
        if code:
            result = self._run_verification(code)
            if result is not None:
                return result

        # 4. 폴백: LLM 텍스트 판단
        return self._llm_verify(goal, step_results)

    # ── 내부 ──────────────────────────────────────────────────────────────────

    def _heuristic_verify(self, goal: str, step_results: list) -> Optional[VerificationResult]:
        """간단한 규칙 기반 검증"""
        outputs = []
        descriptions = []
        workflow_payloads: List[Dict[str, Any]] = []
        for sr in step_results:
            exec_r = getattr(sr, "exec_result", sr)
            if not getattr(exec_r, "success", False):
                return VerificationResult(
                    verified=False,
                    method="heuristic",
                    evidence=(exec_r.error or exec_r.output or "")[:200],
                    summary_kr="일부 단계가 실패하여 목표를 달성하지 못했습니다.",
                )
            outputs.append((exec_r.output or "").strip())
            payload = self._parse_json_output(exec_r.output or "")
            if payload:
                workflow_payloads.append(payload)
            if hasattr(sr, "step"):
                descriptions.append(getattr(sr.step, "description_kr", ""))

        artifacts = extract_artifacts(outputs)
        existing_path_items = existing_paths(artifacts["paths"])
        description_text = " ".join(descriptions)
        url_candidates = [url.lower() for url in artifacts["urls"] if url]
        active_title = ""
        open_window_titles: List[str] = []
        browser_state: Dict[str, Any] = {}
        image_candidates = [
            path for path in artifacts["paths"]
            if str(path).lower().endswith((".png", ".jpg", ".jpeg", ".bmp"))
        ]
        try:
            active_title = (self.executor.execution_globals.get("get_active_window_title") or (lambda: ""))() or ""
        except Exception:
            active_title = ""
        try:
            open_window_titles = (self.executor.execution_globals.get("list_open_windows") or (lambda: []))() or []
        except Exception:
            open_window_titles = []
        try:
            browser_state = (self.executor.execution_globals.get("get_browser_state") or (lambda: {}))() or {}
        except Exception:
            browser_state = {}
        try:
            is_image_visible = self.executor.execution_globals.get("is_image_visible") or (lambda *_args, **_kwargs: False)
        except Exception:
            is_image_visible = lambda *_args, **_kwargs: False

        # 파일 생성 작업 확인
        if existing_path_items and describes_storage_action(description_text):
            return VerificationResult(
                verified=True,
                method="heuristic",
                evidence=existing_path_items[0],
                summary_kr=f"실제 경로({os.path.basename(existing_path_items[0])})가 확인되어 작업을 완료했습니다.",
            )

        if describes_open_action(description_text):
            lowered_title = active_title.lower()
            current_url = str(browser_state.get("current_url", "")).lower()
            matched_url = next((url for url in url_candidates if url in current_url), "")
            if matched_url or any(token for token in url_candidates if token and token.split("//")[-1].split("/")[0] in lowered_title):
                evidence = matched_url or active_title or current_url
                return VerificationResult(
                    verified=True,
                    method="heuristic",
                    evidence=evidence[:200],
                    summary_kr="브라우저 또는 앱 상태가 목표와 일치해 작업을 완료했습니다.",
                )
            if active_title:
                return VerificationResult(
                    verified=True,
                    method="heuristic",
                    evidence=active_title[:200],
                    summary_kr="활성 창 제목이 확인되어 앱 실행 상태를 검증했습니다.",
                )
            if open_window_titles:
                domain_tokens = []
                for token in url_candidates:
                    domain = token.split("//")[-1].split("/")[0]
                    domain_tokens.extend([part for part in domain.split(".") if len(part) >= 3])
                matched_title = next(
                    (
                        title for title in open_window_titles
                        if any(part in title.lower() for part in domain_tokens)
                    ),
                    "",
                )
                if matched_title:
                    return VerificationResult(
                        verified=True,
                        method="heuristic",
                        evidence=matched_title[:200],
                        summary_kr="열린 창 목록에서 목표 URL과 일치하는 상태를 확인했습니다.",
                    )
                goal_tokens = [token.lower() for token in re.findall(r"[A-Za-z가-힣0-9._-]+", description_text) if len(token) >= 2]
                matched_title = next(
                    (
                        title for title in open_window_titles
                        if any(token in title.lower() for token in goal_tokens)
                    ),
                    "",
                )
                if matched_title:
                    return VerificationResult(
                        verified=True,
                        method="heuristic",
                        evidence=matched_title[:200],
                        summary_kr="열린 창 목록에서 목표와 일치하는 앱 상태를 확인했습니다.",
                    )

        visible_image = next((path for path in image_candidates if is_image_visible(path)), "")
        if visible_image:
            return VerificationResult(
                verified=True,
                method="heuristic",
                evidence=visible_image[:200],
                summary_kr="화면 이미지 인식을 통해 목표 상태를 확인했습니다.",
            )

        if describes_open_action(goal):
            app_name = self._extract_app_name_from_goal(goal)
            if app_name and ocr_contains(app_name, region=(0, 0, 1920, 40)):
                return VerificationResult(
                    verified=True,
                    method="ocr_heuristic",
                    evidence=f"화면 상단에서 '{app_name}' 텍스트 확인됨",
                    summary_kr=f"'{app_name}' 앱이 화면에 열려 있음이 OCR로 확인됨",
                )

        for payload in workflow_payloads:
            opened_url = str(payload.get("opened_url", "") or "")
            window_title = str(payload.get("window_title", "") or "")
            action_items = payload.get("actions") or []
            if opened_url and (not url_candidates or any(url in opened_url.lower() for url in url_candidates)):
                return VerificationResult(
                    verified=True,
                    method="heuristic",
                    evidence=opened_url[:200],
                    summary_kr="워크플로우 실행 결과에 열린 URL이 기록되어 목표를 달성했습니다.",
                )
            if window_title and any(isinstance(item, str) and item.startswith("성공:") for item in action_items):
                return VerificationResult(
                    verified=True,
                    method="heuristic",
                    evidence=window_title[:200],
                    summary_kr="워크플로우 실행 결과에 창 제목과 성공 액션이 기록되어 작업을 완료했습니다.",
                )

        if browser_state.get("current_url") and browser_state.get("title"):
            return VerificationResult(
                verified=True,
                method="heuristic",
                evidence=f"{browser_state.get('title')} | {browser_state.get('current_url')}"[:200],
                summary_kr="현재 브라우저 상태를 읽어 목표와 일치하는 실행 결과를 확인했습니다.",
            )

        last_action_summary = str(browser_state.get("last_action_summary", "") or "")
        if last_action_summary and "성공:" in last_action_summary and not any(token in last_action_summary for token in ("실패:", "오류:")):
            return VerificationResult(
                verified=True,
                method="heuristic",
                evidence=last_action_summary[:200],
                summary_kr="브라우저 마지막 액션 기록을 통해 목표와 일치하는 실행 상태를 확인했습니다.",
            )

        return None

    def _ocr_verify(self, goal: str, step_results: list) -> Optional[VerificationResult]:
        expected_keywords = self._extract_expected_keywords(goal, step_results)
        if not expected_keywords:
            return None
        screen_text = ocr_screen()
        if not screen_text:
            return None
        lowered = screen_text.lower()
        keywords_found = [kw for kw in expected_keywords if kw.lower() in lowered]
        score = len(keywords_found) / max(len(expected_keywords), 1)
        if score < 0.6:
            return None
        evidence = ", ".join(keywords_found[:5])
        return VerificationResult(
            verified=True,
            method="ocr",
            evidence=evidence[:200],
            summary_kr=f"화면 OCR에서 목표 관련 텍스트를 확인했습니다. ({len(keywords_found)}/{len(expected_keywords)})",
        )

    def _extract_expected_keywords(self, goal: str, step_results: list) -> list[str]:
        keywords: List[str] = []
        try:
            artifacts = extract_artifacts([goal])
            keywords.extend(os.path.basename(path) for path in artifacts.get("paths", []) if path)
            for url in artifacts.get("urls", []):
                domain = url.split("//")[-1].split("/")[0]
                keywords.extend(part for part in re.split(r"[.\-_/]", domain) if len(part) >= 2)
        except Exception:
            pass
        keywords.extend(token for token in re.findall(r"[A-Za-z가-힣0-9._-]+", goal) if len(token) >= 2)
        for sr in step_results:
            exec_r = getattr(sr, "exec_result", sr)
            output = str(getattr(exec_r, "output", "") or "")
            keywords.extend(token for token in re.findall(r"[A-Za-z가-힣0-9._-]+", output) if len(token) >= 3)
        deduped: List[str] = []
        for item in keywords:
            normalized = item.strip()
            if normalized and normalized not in deduped:
                deduped.append(normalized)
        return deduped[:10]

    def _extract_app_name_from_goal(self, goal: str) -> str:
        tokens = [token for token in re.findall(r"[A-Za-z가-힣0-9._-]+", goal) if len(token) >= 2]
        for token in tokens:
            if token.lower() not in {"열어줘", "실행해줘", "열기", "실행"}:
                return token
        return ""

    def _parse_json_output(self, output: str) -> Optional[Dict[str, Any]]:
        text = (output or "").strip()
        if not text:
            return None
        if not text.startswith("{"):
            json_line = next((line.strip() for line in reversed(text.splitlines()) if line.strip().startswith("{")), "")
            text = json_line
        if not text.startswith("{"):
            return None
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _generate_verification_code(self, goal: str, step_results: list) -> Optional[str]:
        """LLM에게 검증 코드 생성 요청 (planner_model 사용)"""
        lines = []
        artifacts = {"paths": [], "urls": []}
        for i, sr in enumerate(step_results):
            exec_r = getattr(sr, "exec_result", sr)
            desc = getattr(sr.step, "description_kr", "") if hasattr(sr, "step") else ""
            status = "성공" if exec_r.success else "실패"
            out = (exec_r.output or exec_r.error or "없음")[:100]
            lines.append(f"  단계 {i+1} [{status}] {desc}: {out}")
            
            extracted = extract_artifacts([exec_r.output or "", exec_r.error or ""])
            artifacts["paths"].extend(extracted["paths"])
            artifacts["urls"].extend(extracted["urls"])

        steps_summary = "\n".join(lines) or "  (단계 정보 없음)"
        artifact_lines = []
        if artifacts["paths"]: artifact_lines.append("관측된 경로: " + ", ".join(set(artifacts["paths"]))[:400])
        if artifacts["urls"]: artifact_lines.append("관측된 URL: " + ", ".join(set(artifacts["urls"]))[:400])
        if artifact_lines: steps_summary += "\n" + "\n".join(artifact_lines)

        prompt = _VERIFY_CODE_PROMPT.format(goal=goal, steps_summary=steps_summary)

        try:
            # planner_model을 사용하여 더 정확한 검증 코드 생성
            code = self.llm.chat(
                prompt, 
                system_override="파이썬 검증 코드만 반환하세요. 설명·마크다운 없음.",
                model_override=self.llm.planner_model
            )
            code = _RE_CODE_FENCE.sub("", code).strip()
            self._write_trace(goal, code)
            return code if code else None
        except Exception as e:
            logging.error(f"[RealVerifier] 검증 코드 생성 실패: {e}")
            return None

    def _run_verification(self, code: str) -> Optional[VerificationResult]:
        """검증 코드를 실행하고 결과 해석."""
        try:
            # 검증 코드는 safety check 없이 실행 (읽기 전용으로 유도됨)
            result = self.executor._do_run_python(code, extra_globals={"verification_context": {"mode": "verifier"}})
            if not result.success:
                return None

            output = result.output.strip().lower()
            if not output: return None

            if "true" in output or output == "1":
                verified = True
            elif "false" in output or output == "0":
                verified = False
            else:
                return None

            return VerificationResult(
                verified=verified,
                method="code",
                evidence=result.output.strip()[:200],
                summary_kr=f"상태 검증 결과: {'성공' if verified else '미달성'}",
            )
        except Exception as e:
            logging.error(f"[RealVerifier] 검증 실행 오류: {e}")
            return None

    def _llm_verify(self, goal: str, step_results: list) -> VerificationResult:
        """LLM 텍스트 기반 폴백 검증 (planner_model 사용)"""
        try:
            from agent.agent_planner import get_planner
            planner = get_planner()
            exec_results = [getattr(sr, "exec_result", sr) for sr in step_results]
            verdict = planner.verify(goal, exec_results)
            return VerificationResult(
                verified=verdict.get("achieved", False),
                method="llm",
                evidence="",
                summary_kr=verdict.get("summary_kr", "LLM 검증 실패"),
            )
        except Exception as e:
            logging.error(f"[RealVerifier] LLM 검증 오류: {e}")
            return VerificationResult(verified=False, method="llm", evidence="", summary_kr="검증 프로세스 오류")

    def _write_trace(self, goal: str, code: str):
        try:
            from core.resource_manager import ResourceManager
            log_dir = ResourceManager.get_writable_path("logs")
            os.makedirs(log_dir, exist_ok=True)
            path = os.path.join(log_dir, f"verifier_trace_{datetime.now().strftime('%Y%m%d')}.log")
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] goal: {goal}\n{code}\n{'=' * 80}\n")
        except OSError as e:
            logging.debug(f"[Verifier] 추적 로그 쓰기 실패: {e}")

# ── 싱글톤 ─────────────────────────────────────────────────────────────────────

_verifier: Optional[RealVerifier] = None

def get_real_verifier() -> RealVerifier:
    global _verifier
    if _verifier is None:
        from agent.llm_provider import get_llm_provider
        from agent.autonomous_executor import get_executor
        _verifier = RealVerifier(get_llm_provider(), get_executor())
    return _verifier
