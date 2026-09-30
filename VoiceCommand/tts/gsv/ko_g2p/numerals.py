# g2pk2 0.0.3 (Apache-2.0), tenebo, 규칙 파일을 분리해 이식했습니다.
# -*- coding: utf-8 -*-
import re

# 고유어 수사와 함께 쓰는 의존 명사.
BOUND_NOUNS = "군데 권 개 그루 닢 대 두 마리 모 모금 뭇 발 발짝 방 번 벌 보루 살 수 술 시 쌈 움큼 정 짝 채 척 첩 축 켤레 톨 통"


def process_num(num, sino=True):
    """숫자를 한글 수사로 바꾼다."""
    num = re.sub(",", "", num)

    if num == "0":
        return "영"
    if not sino and num == "20":
        return "스무"

    digits = "123456789"
    names = "일이삼사오육칠팔구"
    digit2name = {d: n for d, n in zip(digits, names)}

    modifiers = "한 두 세 네 다섯 여섯 일곱 여덟 아홉"
    decimals = "열 스물 서른 마흔 쉰 예순 일흔 여든 아흔"
    digit2mod = {d: mod for d, mod in zip(digits, modifiers.split())}
    digit2dec = {d: dec for d, dec in zip(digits, decimals.split())}

    spelledout = []
    for i, digit in enumerate(num):
        i = len(num) - i - 1
        if sino:
            if i == 0:
                name = digit2name.get(digit, "")
            elif i == 1:
                name = digit2name.get(digit, "") + "십"
                name = name.replace("일십", "십")
        else:
            if i == 0:
                name = digit2mod.get(digit, "")
            elif i == 1:
                name = digit2dec.get(digit, "")
        if digit == '0':
            if i % 4 == 0:
                last_three = spelledout[-min(3, len(spelledout)):]
                if "".join(last_three) == "":
                    spelledout.append("")
                    continue
            else:
                spelledout.append("")
                continue
        if i == 2:
            name = digit2name.get(digit, "") + "백"
            name = name.replace("일백", "백")
        elif i == 3:
            name = digit2name.get(digit, "") + "천"
            name = name.replace("일천", "천")
        elif i == 4:
            name = digit2name.get(digit, "") + "만"
            name = name.replace("일만", "만")
        elif i == 5:
            name = digit2name.get(digit, "") + "십"
            name = name.replace("일십", "십")
        elif i == 6:
            name = digit2name.get(digit, "") + "백"
            name = name.replace("일백", "백")
        elif i == 7:
            name = digit2name.get(digit, "") + "천"
            name = name.replace("일천", "천")
        elif i == 8:
            name = digit2name.get(digit, "") + "억"
        elif i == 9:
            name = digit2name.get(digit, "") + "십"
        elif i == 10:
            name = digit2name.get(digit, "") + "백"
        elif i == 11:
            name = digit2name.get(digit, "") + "천"
        elif i == 12:
            name = digit2name.get(digit, "") + "조"
        elif i == 13:
            name = digit2name.get(digit, "") + "십"
        elif i == 14:
            name = digit2name.get(digit, "") + "백"
        elif i == 15:
            name = digit2name.get(digit, "") + "천"
        spelledout.append(name)

    return "".join(elem for elem in spelledout)


def convert_num(string):
    """표기된 숫자를 한글 발음으로 바꾼다."""
    global BOUND_NOUNS

    # 의존 명사 앞 수사를 구분한다.
    tokens = set(re.findall("([\d][\d,]*)([ㄱ-힣]+)/B", string))
    for token in tokens:
        num, bn = token
        if bn in BOUND_NOUNS:
            spelledout = process_num(num, sino=False)
        else:
            spelledout = process_num(num, sino=True)
        string = string.replace(f"{num}{bn}/B", f"{spelledout}{bn}/B")

    # 나머지 숫자를 한 자리씩 읽는다.
    digits = "0123456789"
    names = "영일이삼사오육칠팔구"
    for d, n in zip(digits, names):
        string = string.replace(d, n)

    return string


if __name__ == "__main__":
    # 변환 결과를 확인한다.
    print(process_num("123,456,789", sino=True))
    print(process_num("123,456,789", sino=False))
    print(convert_num("우리 3시/B 10분/B에 만나자."))
