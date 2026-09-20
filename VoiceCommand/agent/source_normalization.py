import io
import tokenize


_ONE_LINE_SUITE_KEYWORDS = {
    "with", "for", "if", "elif", "else", "try", "except",
    "finally", "while", "def", "class", "match", "case",
}


def _split_top_level_semicolons(code: str) -> str:
    """문자열/괄호 내부를 제외한 최상위 세미콜론만 줄바꿈으로 변환한다."""
    lines = code.splitlines(keepends=True)
    if not lines:
        return code

    line_offsets: list[int] = []
    offset = 0
    for line in lines:
        line_offsets.append(offset)
        offset += len(line)

    def to_index(position: tuple[int, int]) -> int:
        line_no, column = position
        return line_offsets[line_no - 1] + column

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(code).readline))
    except tokenize.TokenError:
        return code

    replacements: list[tuple[int, int]] = []
    depth = 0
    current_line = 1
    first_name_on_line = ""
    one_line_suite_active = False

    for index, token in enumerate(tokens):
        token_line = token.start[0]
        if token_line != current_line:
            current_line = token_line
            first_name_on_line = ""
            one_line_suite_active = False

        if token.type == tokenize.NAME and not first_name_on_line:
            first_name_on_line = token.string

        if token.type != tokenize.OP:
            continue

        if token.string in "([{":
            depth += 1
            continue
        if token.string in ")]}":
            depth = max(0, depth - 1)
            continue
        if token.string == ":" and depth == 0 and first_name_on_line in _ONE_LINE_SUITE_KEYWORDS:
            one_line_suite_active = True
            continue
        if token.string != ";" or depth != 0 or one_line_suite_active:
            continue

        start_index = to_index(token.start)
        end_index = start_index + 1
        for next_token in tokens[index + 1:]:
            if next_token.start[0] != token_line:
                break
            end_index = to_index(next_token.start)
            break
        replacements.append((start_index, end_index))

    if not replacements:
        return code

    normalized = code
    for start_index, end_index in reversed(replacements):
        normalized = f"{normalized[:start_index]}\n{normalized[end_index:]}"
    return normalized


