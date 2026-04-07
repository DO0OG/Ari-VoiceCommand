"""
_() 문자열을 소스에서 자동 추출해 .pot 파일을 생성합니다.
실행: py -3.11 scripts/extract_strings.py

xgettext가 설치된 경우 사용하고, 없으면 간단한 regex 추출로 대체합니다.
"""
import os
import re
import subprocess
import sys

_BASE = os.path.dirname(os.path.dirname(__file__))
_OUTPUT = os.path.join(_BASE, "i18n", "locales", "ari.pot")
_SOURCES = ["ui", "agent", "core", "commands", "memory", "services", "i18n"]

_PY_FILES: list[str] = []
for d in _SOURCES:
    target = os.path.join(_BASE, d)
    if not os.path.isdir(target):
        continue
    for root, _, files in os.walk(target):
        for f in files:
            if f.endswith(".py"):
                _PY_FILES.append(os.path.join(root, f))


def _extract_with_xgettext() -> bool:
    try:
        subprocess.run(
            [
                "xgettext", "--language=Python",
                "--keyword=_", "--keyword=ngettext:1,2",
                "--output=" + _OUTPUT, "--from-code=UTF-8",
                "--package-name=Ari",
            ] + _PY_FILES,
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _extract_with_regex() -> None:
    pattern = re.compile(r'_\(\s*["\']([^"\']+)["\']')
    found: set[str] = set()
    for path in _PY_FILES:
        try:
            text = open(path, encoding="utf-8").read()
        except Exception:
            continue
        for match in pattern.finditer(text):
            found.add(match.group(1))

    os.makedirs(os.path.dirname(_OUTPUT), exist_ok=True)
    with open(_OUTPUT, "w", encoding="utf-8") as f:
        f.write('# Ari .pot — auto-generated\n')
        f.write('msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n\n')
        for msgid in sorted(found):
            f.write('msgid "' + msgid + '"\nmsgstr ""\n\n')


if __name__ == "__main__":
    if not _extract_with_xgettext():
        print("xgettext not found, using regex extractor")
        _extract_with_regex()
    print("Extracted:", _OUTPUT)
    print("Next: add translations to each .po file, then run compile_po.py")
