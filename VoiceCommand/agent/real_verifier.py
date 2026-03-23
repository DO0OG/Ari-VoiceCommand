"""
실제 상태 검증기 (Real Verifier)
LLM 텍스트 판단에만 의존하지 않고,
LLM이 생성한 검증 코드를 실제로 실행하여 목표 달성 여부를 확인합니다.

검증 순서:
  1. LLM이 목표에 맞는 검증 Python 코드 생성
  2. 코드 실행 → 출력이 "True/False" 등 명확한 결과이면 채택
  3. 코드 실행 실패 시 → LLM 텍스트 판단으로 폴백
"""
import logging
import os
import re
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

_VERIFY_CODE_PROMPT = """\
다음 목표가 달성됐는지 확인하는 파이썬 검증 코드를 작성하세요.

목표: {goal}

실행된 단계와 출력:
{steps_summary}

요구사항:
- 목표 달성 여부를 실제 상태로 확인 (파일 존재, 값 검증, 출력 확인 등)
- 브라우저 열기, 앱 실행, URL 열기 같은 작업은 검증을 위해 open_url, launch_app, webbrowser.open 등을 다시 호출하지 마세요.
- 검증 코드는 부작용이 없어야 합니다. 이미 수행된 동작을 다시 실행하지 말고, 가능한 경우 실행 출력과 상태만 확인하세요.
- 마지막 줄에 반드시 True 또는 False를 print()로 출력
- Windows 바탕화면 경로: os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')), 'Desktop')
- 예시: desktop = os.path.join(os.environ.get('USERPROFILE', ''), 'Desktop'); print(os.path.exists(desktop))
- 코드만 반환 (설명·주석·마크다운 없음)
"""

_RE_CODE_FENCE = re.compile(r'```(?:python)?\s*', re.IGNORECASE)


@dataclass
class VerificationResult:
    verified: bool
    method: str         # "code" | "llm"
    evidence: str       # 실제 증거 텍스트
    summary_kr: str


class RealVerifier:
    """검증 코드를 실제로 실행하여 목표 달성 여부를 확인합니다."""

    def __init__(self, llm_provider, executor):
        self.llm = llm_provider
        self.executor = executor

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def verify(self, goal: str, step_results: list) -> VerificationResult:
        """
        검증 코드 실행 → 실패 시 LLM 텍스트 판단 폴백.
        step_results: List[StepResult] 또는 List[ExecutionResult]
        """
        heuristic = self._heuristic_verify(goal, step_results)
        if heuristic is not None:
            return heuristic

        code = self._generate_verification_code(goal, step_results)
        if code:
            result = self._run_verification(code)
            if result is not None:
                return result

        # 폴백: LLM 텍스트 판단
        return self._llm_verify(goal, step_results)

    # ── 내부 ──────────────────────────────────────────────────────────────────

    def _heuristic_verify(self, goal: str, step_results: list) -> Optional[VerificationResult]:
        descs = []
        outputs = []
        for sr in step_results:
            exec_r = getattr(sr, "exec_result", sr)
            if not getattr(exec_r, "success", False):
                return None
            outputs.append((exec_r.output or "").strip())
            if hasattr(sr, "step"):
                descs.append(getattr(sr.step, "description_kr", ""))

        joined_desc = " ".join(descs)
        open_markers = ("웹사이트 열기", "앱 실행", "파일/경로 열기")
        has_open_evidence = any(
            output.startswith(("http://", "https://"))
            or output.lower().endswith((".exe", ".lnk"))
            or ("\\" in output and ":" in output)
            for output in outputs if output
        )
        if has_open_evidence:
            evidence = next((out for out in outputs if out), "")
            return VerificationResult(
                verified=True,
                method="heuristic",
                evidence=evidence[:200],
                summary_kr="실행 결과 기준으로 열기 작업이 완료되었습니다.",
            )
        return None

    def _generate_verification_code(self, goal: str, step_results: list) -> Optional[str]:
        """LLM에게 검증 코드 생성 요청"""
        lines = []
        for i, sr in enumerate(step_results):
            # StepResult or ExecutionResult 모두 처리
            exec_r = getattr(sr, "exec_result", sr)
            desc = ""
            if hasattr(sr, "step"):
                desc = getattr(sr.step, "description_kr", "")
            status = "성공" if exec_r.success else "실패"
            out = (exec_r.output or exec_r.error or "없음")[:100]
            lines.append(f"  단계 {i+1} [{status}] {desc}: {out}")

        steps_summary = "\n".join(lines) or "  (단계 정보 없음)"
        prompt = _VERIFY_CODE_PROMPT.format(goal=goal, steps_summary=steps_summary)

        try:
            if not self.llm.client:
                return None
            if self.llm.provider == "anthropic":
                resp = self.llm.client.messages.create(
                    model=self.llm.model,
                    max_tokens=400,
                    system="파이썬 검증 코드만 반환하세요. 설명·마크다운 없음.",
                    messages=[{"role": "user", "content": prompt}],
                )
                code = " ".join(b.text for b in resp.content if b.type == "text")
            else:
                resp = self.llm.client.chat.completions.create(
                    model=self.llm.model,
                    messages=[
                        {"role": "system", "content": "파이썬 검증 코드만 반환하세요. 설명·마크다운 없음."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=400,
                )
                code = resp.choices[0].message.content or ""

            code = _RE_CODE_FENCE.sub("", code).strip()
            self._write_trace(goal, code)
            return code if code else None

        except Exception as e:
            logging.error(f"[RealVerifier] 검증 코드 생성 실패: {e}")
            return None

    def _run_verification(self, code: str) -> Optional[VerificationResult]:
        """검증 코드를 실행하고 결과 해석. 실패 시 None 반환."""
        try:
            # _do_run_python은 safety check 없이 직접 실행 (검증용 코드)
            result = self.executor._do_run_python(code)
            if not result.success:
                logging.warning(f"[RealVerifier] 검증 코드 실행 실패: {result.error[:100]}")
                return None

            output = result.output.strip().lower()
            if not output:
                return None

            # True/False 판단
            if output.startswith("true") or output == "1":
                verified = True
            elif output.startswith("false") or output == "0":
                verified = False
            else:
                # 명확하지 않으면 폴백
                logging.info(f"[RealVerifier] 검증 출력 불명확: {output[:50]}")
                return None

            return VerificationResult(
                verified=verified,
                method="code",
                evidence=result.output.strip()[:200],
                summary_kr=f"코드 검증 {'달성' if verified else '미달성'}: {result.output.strip()[:80]}",
            )
        except Exception as e:
            logging.error(f"[RealVerifier] 검증 실행 오류: {e}")
            return None

    def _llm_verify(self, goal: str, step_results: list) -> VerificationResult:
        """LLM 텍스트 기반 폴백 검증"""
        try:
            from agent_planner import get_planner
            planner = get_planner()
            exec_results = [
                getattr(sr, "exec_result", sr) for sr in step_results
            ]
            verdict = planner.verify(goal, exec_results)
            return VerificationResult(
                verified=verdict.get("achieved", False),
                method="llm",
                evidence="",
                summary_kr=verdict.get("summary_kr", "LLM 검증 실패"),
            )
        except Exception as e:
            logging.error(f"[RealVerifier] LLM 검증 실패: {e}")
            return VerificationResult(
                verified=False, method="llm", evidence="", summary_kr="검증 오류"
            )

    def _write_trace(self, goal: str, code: str):
        try:
            from core.resource_manager import ResourceManager
            log_dir = ResourceManager.get_writable_path("logs")
            os.makedirs(log_dir, exist_ok=True)
            path = os.path.join(log_dir, f"verifier_trace_{datetime.now().strftime('%Y%m%d')}.log")
            with open(path, "a", encoding="utf-8") as f:
                f.write(
                    f"[{datetime.now().strftime('%H:%M:%S')}] goal: {goal}\n"
                    f"{code[:4000]}\n"
                    f"{'=' * 80}\n"
                )
        except Exception as e:
            logging.warning(f"[RealVerifier] trace 저장 실패: {e}")


# ── 싱글톤 ─────────────────────────────────────────────────────────────────────

_verifier: Optional[RealVerifier] = None


def get_real_verifier() -> RealVerifier:
    global _verifier
    if _verifier is None:
        from llm_provider import get_llm_provider
        from autonomous_executor import get_executor
        _verifier = RealVerifier(get_llm_provider(), get_executor())
    return _verifier
