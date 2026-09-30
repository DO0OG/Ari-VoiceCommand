"""Genie 언어별 음소 변환 연결."""

# Genie (MIT), High-Logic, GetPhonesAndBert.py의 언어별 입력 구성을 이식했습니다.

import numpy as np

from tts.gsv.g2p.symbols import symbol_to_id_v2, symbols_v2

BERT_FEATURE_DIM = 1024


def get_phones_and_bert(text: str, language: str) -> tuple[np.ndarray, np.ndarray]:
    """언어별 음소 ID와 빈 BERT 특징을 만든다."""
    if language == "en":
        from tts.gsv.g2p.english import english_to_phones

        phones = english_to_phones(text)
    elif language == "ja":
        from tts.gsv.g2p.japanese import japanese_to_phones

        phones = japanese_to_phones(text)
    elif language == "ko":
        from tts.gsv.ko_g2p.korean import korean_to_phones

        phones = korean_to_phones(text)
    else:
        raise ValueError(f"지원하지 않는 음성 언어입니다: {language}")
    if phones and isinstance(phones[0], (int, np.integer)):
        phone_ids = [int(phone) for phone in phones]
    else:
        valid = [phone for phone in phones if phone in symbols_v2]
        phone_ids = [symbol_to_id_v2[phone] for phone in valid]
    sequence = np.asarray([phone_ids], dtype=np.int64)
    features = np.zeros((len(phone_ids), BERT_FEATURE_DIM), dtype=np.float32)
    return sequence, features
