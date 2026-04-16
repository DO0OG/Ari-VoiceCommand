"""
.po 파일을 .mo 바이너리로 컴파일한다. (인코딩 지원 강화 버전)
실행: py -3.11 scripts/compile_po.py

msgfmt 없이 Python 표준 라이브러리만 사용한다.
"""
import os
import struct

_BASE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "i18n", "locales")


def compile_po(po_path: str, mo_path: str) -> None:
    messages: dict[str, str] = {}
    msgid = msgstr = None
    in_msgid = in_msgstr = False

    with open(po_path, encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                # 공백이나 주석일 때 이전까지의 데이터를 저장
                if msgid is not None and msgstr is not None:
                    messages[msgid] = msgstr
                    msgid = msgstr = None
                in_msgid = in_msgstr = False
                continue

            if line.startswith("msgid "):
                msgid = line[6:].strip('"')
                in_msgid, in_msgstr = True, False
            elif line.startswith("msgstr "):
                msgstr = line[7:].strip('"')
                in_msgid, in_msgstr = False, True
            elif line.startswith('"'):
                # 멀티라인 처리
                content = line.strip('"')
                if in_msgid:
                    msgid = (msgid or "") + content
                elif in_msgstr:
                    msgstr = (msgstr or "") + content

        # 마지막 엔트리 저장
        if msgid is not None and msgstr is not None:
            messages[msgid] = msgstr

    # gettext는 msgid가 없는 항목(공백 문자열)을 헤더로 인식함.
    # 헤더가 없으면 ASCII로 폴백하므로 반드시 포함해야 함.
    keys = sorted(messages.keys())
    N = len(keys)
    MAGIC = 0x950412de
    # 레이아웃: header(28) + orig_table(N*8) + trans_table(N*8) + key_blob + val_blob
    orig_start = 28
    trans_start = orig_start + N * 8
    data_start = trans_start + N * 8

    key_blob = b""
    val_blob = b""
    for k in keys:
        # 이스케이프 문자(\n 등)를 실제 바이트로 변환
        kb = k.replace("\\n", "\n").encode("utf-8")
        vb = messages[k].replace("\\n", "\n").encode("utf-8")
        key_blob += kb + b"\x00"
        val_blob += vb + b"\x00"

    orig_table = []
    offset = data_start
    for k in keys:
        kb = k.replace("\\n", "\n").encode("utf-8")
        orig_table.append((len(kb), offset))
        offset += len(kb) + 1

    trans_table = []
    offset = data_start + len(key_blob)
    for k in keys:
        vb = messages[k].replace("\\n", "\n").encode("utf-8")
        trans_table.append((len(vb), offset))
        offset += len(vb) + 1

    with open(mo_path, "wb") as f:
        f.write(struct.pack("<IIIIIII", MAGIC, 0, N, orig_start, trans_start, 0, 0))
        for length, off in orig_table:
            f.write(struct.pack("<II", length, off))
        for length, off in trans_table:
            f.write(struct.pack("<II", length, off))
        f.write(key_blob)
        f.write(val_blob)


if __name__ == "__main__":
    for lang in os.listdir(_BASE):
        po = os.path.join(_BASE, lang, "LC_MESSAGES", "ari.po")
        mo = po.replace(".po", ".mo")
        if os.path.exists(po):
            compile_po(po, mo)
            print("Compiled: %s -> %d bytes" % (lang, os.path.getsize(mo)))
