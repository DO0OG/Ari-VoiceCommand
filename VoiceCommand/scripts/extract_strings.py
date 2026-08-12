"""
_() 문자열을 소스에서 자동 추출해 .pot 파일을 생성한다.
실행: py -3.11 scripts/extract_strings.py

xgettext가 설치된 경우 사용하고, 없으면 간단한 regex 추출로 대체한다.
"""
import os
import re
import logging
import shutil
# xgettext is resolved to an executable path and invoked without a shell.
import subprocess  # nosec B404
import tempfile

_BASE = os.path.dirname(os.path.dirname(__file__))
_OUTPUT = os.path.join(_BASE, "i18n", "locales", "ari.pot")
_SOURCES = ["ui", "agent", "core", "commands", "memory", "services", "i18n"]

log = logging.getLogger(__name__)

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
    executable = shutil.which("xgettext")
    if executable is None:
        return False

    files_from: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                        delete=False, encoding="utf-8") as fh:
            fh.write("\n".join(_PY_FILES))
            files_from = fh.name
        # The executable and every argument are controlled by this script.
        subprocess.run(  # nosec B603
            [
                executable, "--language=Python",
                "--keyword=_", "--keyword=ngettext:1,2",
                "--output", _OUTPUT, "--from-code=UTF-8",
                "--package-name=Ari",
                "--files-from", files_from,
            ],
            check=True,
            shell=False,
        )
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        log.warning("xgettext extraction failed: %s", exc)
        return False
    finally:
        if files_from is not None:
            try:
                os.unlink(files_from)
            except OSError as exc:
                log.debug("Could not remove temporary xgettext input list: %s", exc)


def _read_source(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as source:
            return source.read()
    except (OSError, UnicodeError) as exc:
        log.warning("Skipping unreadable source file %s: %s", path, exc)
        return None


def _extract_with_regex() -> None:
    pattern = re.compile(r'_\(\s*["\']([^"\']+)["\']')
    found: set[str] = set()
    for path in _PY_FILES:
        text = _read_source(path)
        if text is None:
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
