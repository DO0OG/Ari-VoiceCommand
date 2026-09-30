"""g2pk2의 한글 규칙표 로더와 후처리."""

# g2pk2 0.0.3 (Apache-2.0), tenebo, 한국어 규칙 처리 부분을 이식했습니다.

import os
import re

from jamo import j2h


def parse_table() -> list[tuple[str, str, list[str]]]:
    """받침·초성 조합 규칙을 읽는다."""
    path = os.path.join(os.path.dirname(__file__), "table.csv")
    with open(path, encoding="utf-8-sig") as source:
        lines = source.read().splitlines()
    onsets = lines[0].split(",")
    table = []
    for line in lines[1:]:
        columns = line.split(",")
        coda = columns[0]
        for index, onset in enumerate(onsets):
            if index == 0 or not columns[index]:
                continue
            cell = columns[index]
            if "(" in cell:
                replacement, rule_ids = cell.split("(", 1)
                table.append((coda + onset, replacement, rule_ids[:-1].split("/")))
            else:
                table.append((coda + onset, cell, []))
    return table


def get_rule_id2text() -> dict[str, str]:
    path = os.path.join(os.path.dirname(__file__), "rules.txt")
    with open(path, encoding="utf-8") as source:
        blocks = source.read().strip().split("\n\n")
    return {
        block.splitlines()[0].strip(): "\n".join(block.splitlines()[1:])
        for block in blocks
        if block.splitlines()
    }


def compose(letters: str) -> str:
    """결합 자모를 한글 음절로 합친다."""
    letters = re.sub(r"(^|[^ᄀ-ᄒ])([ᅡ-ᅵ])", r"\1ᄋ\2", letters)
    for match in set(re.findall(r"[ᄀ-ᄒ][ᅡ-ᅵ][ᆨ-ᇂ]", letters)):
        letters = letters.replace(match, j2h(*match))
    for match in set(re.findall(r"[ᄀ-ᄒ][ᅡ-ᅵ]", letters)):
        letters = letters.replace(match, j2h(*match))
    return letters


def gloss(verbose: bool, out: str, inp: str, rule: str) -> None:
    """디버그 모드에서 적용된 발음 규칙을 표시한다."""
    if verbose and out != inp:
        print(f"{compose(inp)} -> {compose(out)}\n{rule}")
