# g2pk2 0.0.3 (Apache-2.0), tenebo, 규칙 파일을 분리해 이식했습니다.
# -*- coding: utf-8 -*-
import re

from .utils import gloss, get_rule_id2text

rule_id2text = get_rule_id2text()

# 모음 규칙.
def jyeo(inp, descriptive=False, verbose=False):
    rule = rule_id2text["5.1"]
    # 해당 발음을 일반 규칙으로 적용한다.

    out = re.sub("([ᄌᄍᄎ])ᅧ", r"\1ᅥ", inp)
    gloss(verbose, out, inp, rule)
    return out

def ye(inp, descriptive=False, verbose=False):
    rule = rule_id2text["5.2"]
    # 일부 예외를 제외한 'ㅖ'를 'ㅔ'로 바꾼다.

    if descriptive:
        out = re.sub("([ᄀᄁᄃᄄㄹᄆᄇᄈᄌᄍᄎᄏᄐᄑᄒ])ᅨ", r"\1ᅦ", inp)
    else:
        out = inp
    gloss(verbose, out, inp, rule)
    return out

def consonant_ui(inp, descriptive=False, verbose=False):
    rule = rule_id2text["5.3"]

    out = re.sub("([ᄀᄁᄂᄃᄄᄅᄆᄇᄈᄉᄊᄌᄍᄎᄏᄐᄑᄒ])ᅴ", r"\1ᅵ", inp)
    gloss(verbose, out, inp, rule)
    return out

def josa_ui(inp, descriptive=False, verbose=False):
    rule = rule_id2text["5.4.2"]
    # 조사 '의'를 '에'에 가깝게 바꾼다.
    if descriptive:
        out = re.sub("의/J", "에", inp)
    else:
        out = inp.replace("/J", "")
    gloss(verbose, out, inp, rule)
    return out

def vowel_ui(inp, descriptive=False, verbose=False):
    rule = rule_id2text["5.4.1"]
    # 첫 음절 밖의 '의'를 '이'에 가깝게 바꾼다.
    if descriptive:
        out = re.sub("(\Sᄋ)ᅴ", r"\1ᅵ", inp)
    else:
        out = inp
    gloss(verbose, out, inp, rule)
    return out

def jamo(inp, descriptive=False, verbose=False):
    rule = rule_id2text["16"]
    out = inp

    out = re.sub("([그])ᆮᄋ", r"\1ᄉ", out)
    out = re.sub("([으])[ᆽᆾᇀᇂ]ᄋ", r"\1ᄉ", out)
    out = re.sub("([으])[ᆿ]ᄋ", r"\1ᄀ", out)
    out = re.sub("([으])[ᇁ]ᄋ", r"\1ᄇ", out)

    gloss(verbose, out, inp, rule)
    return out

# 어간 받침 규칙.
def rieulgiyeok(inp, descriptive=False, verbose=False):
    rule = rule_id2text["11.1"]

    out = inp
    out = re.sub("ᆰ/P([ᄀᄁ])", r"ᆯᄁ", out)

    gloss(verbose, out, inp, rule)
    return out

def rieulbieub(inp, descriptive=False, verbose=False):
    rule = rule_id2text["25"]
    out = inp

    out = re.sub("([ᆲᆴ])/Pᄀ", r"\1ᄁ", out)
    out = re.sub("([ᆲᆴ])/Pᄃ", r"\1ᄄ", out)
    out = re.sub("([ᆲᆴ])/Pᄉ", r"\1ᄊ", out)
    out = re.sub("([ᆲᆴ])/Pᄌ", r"\1ᄍ", out)

    gloss(verbose, out, inp, rule)
    return out

def verb_nieun(inp, descriptive=False, verbose=False):
    rule = rule_id2text["24"]
    out = inp

    pairs = [ ("([ᆫᆷ])/Pᄀ", r"\1ᄁ"),
              ("([ᆫᆷ])/Pᄃ", r"\1ᄄ"),
              ("([ᆫᆷ])/Pᄉ", r"\1ᄊ"),
              ("([ᆫᆷ])/Pᄌ", r"\1ᄍ"),

              ("ᆬ/Pᄀ", "ᆫᄁ"),
              ("ᆬ/Pᄃ", "ᆫᄄ"),
              ("ᆬ/Pᄉ", "ᆫᄊ"),
              ("ᆬ/Pᄌ", "ᆫᄍ"),

              ("ᆱ/Pᄀ", "ᆷᄁ"),
              ("ᆱ/Pᄃ", "ᆷᄄ"),
              ("ᆱ/Pᄉ", "ᆷᄊ"),
              ("ᆱ/Pᄌ", "ᆷᄍ")  ]

    for str1, str2 in pairs:
        out = re.sub(str1, str2, out)

    gloss(verbose, out, inp, rule)
    return out

def balb(inp, descriptive=False, verbose=False):
    rule = rule_id2text["10.1"]
    out = inp
    syllable_final_or_consonants = "($|[^ᄋᄒ])"

    # 예외 발음.
    out = re.sub(f"(바)ᆲ({syllable_final_or_consonants})", r"\1ᆸ\2", out)
    out = re.sub(f"(너)ᆲ([ᄌᄍ]ᅮ|[ᄃᄄ]ᅮ)", r"\1ᆸ\2", out)
    gloss(verbose, out, inp, rule)
    return out

def palatalize(inp, descriptive=False, verbose=False):
    rule = rule_id2text["17"]
    out = inp

    out = re.sub("ᆮᄋ([ᅵᅧ])", r"ᄌ\1", out)
    out = re.sub("ᇀᄋ([ᅵᅧ])", r"ᄎ\1", out)
    out = re.sub("ᆴᄋ([ᅵᅧ])", r"ᆯᄎ\1", out)

    out = re.sub("ᆮᄒ([ᅵ])", r"ᄎ\1", out)

    gloss(verbose, out, inp, rule)
    return out

def modifying_rieul(inp, descriptive=False, verbose=False):
    rule = rule_id2text["27"]
    out = inp

    pairs = [   ("ᆯ/E ᄀ", r"ᆯ ᄁ"),
                ("ᆯ/E ᄃ", r"ᆯ ᄄ"),
                ("ᆯ/E ᄇ", r"ᆯ ᄈ"),
                ("ᆯ/E ᄉ", r"ᆯ ᄊ"),
                ("ᆯ/E ᄌ", r"ᆯ ᄍ"),

                ("ᆯ걸", "ᆯ껄"),
                ("ᆯ밖에", "ᆯ빠께"),
                ("ᆯ세라", "ᆯ쎄라"),
                ("ᆯ수록", "ᆯ쑤록"),
                ("ᆯ지라도", "ᆯ찌라도"),
                ("ᆯ지언정", "ᆯ찌언정"),
                ("ᆯ진대", "ᆯ찐대") ]

    for str1, str2 in pairs:
        out = re.sub(str1, str2, out)

    gloss(verbose, out, inp, rule)
    return out
