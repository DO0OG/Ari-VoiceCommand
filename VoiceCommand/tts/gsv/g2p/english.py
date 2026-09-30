# Genie (MIT), High-Logic, G2P/English/EnglishG2P.py에서 필요한 경로만 이식했습니다.
import pickle
import hashlib
import os
import re
from typing import List, Dict, Tuple

import numpy as np
import nltk
from nltk.tokenize import TweetTokenizer
from nltk import pos_tag

from .english_normalization import normalize
from .word_segment import segment_text
from .symbols import symbols_v2, symbol_to_id_v2, PUNCTUATION
from tts.gsv.paths import get_genie_data_path

English_G2P_DIR = get_genie_data_path("G2P", "EnglishG2P")

# NLTK 자료 경로와 토크나이저를 설정한다.
nltk.data.path.append(English_G2P_DIR)
word_tokenize = TweetTokenizer().tokenize

# 자료 경로를 설정한다.
CMU_DICT_HOT_PATH = os.path.join(English_G2P_DIR, "engdict-hot.rep")
CACHE_PATH = os.path.join(English_G2P_DIR, "engdict_cache.pickle")
NAMECACHE_PATH = os.path.join(English_G2P_DIR, "namedict_cache.pickle")
MODEL_PATH = os.path.join(English_G2P_DIR, "checkpoint20.npz")

# 정규식과 치환표를 정의한다.
REP_MAP = {
    "[;:：，；]": ",",
    '["’]': "'",
    "。": ".",
    "！": "!",
    "？": "?",
}
REP_MAP_PATTERN = re.compile("|".join(re.escape(p) for p in REP_MAP.keys()))
PUNCTUATIONS_FOR_REGEX = "".join(re.escape(p) for p in PUNCTUATION)
CONSECUTIVE_PUNCTUATION_PATTERN = re.compile(
    rf"([{PUNCTUATIONS_FOR_REGEX}\s])([{PUNCTUATIONS_FOR_REGEX}])+"
)


# 보조 변환 함수.
def _read_cmu_dict(file_path: str) -> Dict[str, List[str]]:
    g2p_dict = {}
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(';;;'): continue
            parts = re.split(r'\s+', line, maxsplit=1)
            if len(parts) < 2: continue
            word, pron_str = parts[0].lower(), parts[1]
            pron = pron_str.split(" ")
            word = re.sub(r'\(\d+\)$', '', word)
            if word not in g2p_dict: g2p_dict[word] = [pron]
    return g2p_dict


def _load_verified_pickle(path: str, expected_sha256: str):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        raise ValueError(f"G2P 캐시 검증에 실패했습니다: {os.path.basename(path)}")
    with open(path, "rb") as source:
        return pickle.load(source)


def _load_and_cache_dict() -> Dict[str, List[List[str]]]:
    g2p_dict = _load_verified_pickle(
        CACHE_PATH,
        "9bff9393f4b192d873a11335efc8f124771087b6dc847d34fd240c2846889d2b",
    )
    hot_dict = _read_cmu_dict(CMU_DICT_HOT_PATH)
    if hot_dict: g2p_dict.update(hot_dict)
    return g2p_dict


def replace_phs(phs: List[str]) -> List[str]:
    rep_map = {"'": "-"}
    phs_new = []
    for ph in phs:
        if ph in symbols_v2:
            phs_new.append(ph)
        elif ph in rep_map:
            phs_new.append(rep_map[ph])
    return phs_new


def replace_consecutive_punctuation(text: str) -> str:
    return CONSECUTIVE_PUNCTUATION_PATTERN.sub(r"\1", text)


def text_normalize(text: str) -> str:
    text = REP_MAP_PATTERN.sub(lambda x: REP_MAP[x.group()], text)
    text = normalize(text)
    text = replace_consecutive_punctuation(text)
    return text


class CleanG2p:
    """영어 음소를 변환한다."""

    def __init__(self):
        # 사전과 동음이의어 정보를 준비한다.
        self.cmu = _load_and_cache_dict()
        self.namedict = self._load_name_dict()
        for word in ["AE", "AI", "AR", "IOS", "HUD", "OS"]:
            self.cmu.pop(word.lower(), None)
        self._setup_homographs()

        # 신경망 모델을 준비한다.
        self._setup_nn_components()
        self._load_nn_model()

    def _setup_nn_components(self):
        """문자와 음소 인덱스를 준비한다."""
        self.graphemes = ["<pad>", "<unk>", "</s>"] + list("abcdefghijklmnopqrstuvwxyz")
        self.phonemes = ["<pad>", "<unk>", "<s>", "</s>"] + [
            "AA0", "AA1", "AA2", "AE0", "AE1", "AE2", "AH0", "AH1",
            "AH2", "AO0", "AO1", "AO2", "AW0", "AW1", "AW2", "AY0",
            "AY1", "AY2", "B", "CH", "D", "DH", "EH0", "EH1", "EH2",
            "ER0", "ER1", "ER2", "EY0", "EY1", "EY2", "F", "G", "HH",
            "IH0", "IH1", "IH2", "IY0", "IY1", "IY2", "JH", "K", "L",
            "M", "N", "NG", "OW0", "OW1", "OW2", "OY0", "OY1", "OY2",
            "P", "R", "S", "SH", "T", "TH", "UH0", "UH1", "UH2", "UW",
            "UW0", "UW1", "UW2", "V", "W", "Y", "Z", "ZH",
        ]
        self.g2idx = {g: idx for idx, g in enumerate(self.graphemes)}
        self.idx2g = {idx: g for idx, g in enumerate(self.graphemes)}
        self.p2idx = {p: idx for idx, p in enumerate(self.phonemes)}
        self.idx2p = {idx: p for idx, p in enumerate(self.phonemes)}

    def _load_nn_model(self):
        """고정된 신경망 가중치를 읽는다."""
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(
                f"G2P model file not found at: {MODEL_PATH}. "
                "Please ensure 'checkpoint20.npz' is in the correct directory."
            )

        variables = np.load(MODEL_PATH)
        self.enc_emb = variables["enc_emb"]
        self.enc_w_ih = variables["enc_w_ih"]
        self.enc_w_hh = variables["enc_w_hh"]
        self.enc_b_ih = variables["enc_b_ih"]
        self.enc_b_hh = variables["enc_b_hh"]
        self.dec_emb = variables["dec_emb"]
        self.dec_w_ih = variables["dec_w_ih"]
        self.dec_w_hh = variables["dec_w_hh"]
        self.dec_b_ih = variables["dec_b_ih"]
        self.dec_b_hh = variables["dec_b_hh"]
        self.fc_w = variables["fc_w"]
        self.fc_b = variables["fc_b"]

    @staticmethod
    def _sigmoid(x):
        return 1 / (1 + np.exp(-x))

    def _grucell(self, x, h, w_ih, w_hh, b_ih, b_hh):
        rzn_ih = np.matmul(x, w_ih.T) + b_ih
        rzn_hh = np.matmul(h, w_hh.T) + b_hh
        rz_ih, n_ih = rzn_ih[:, :rzn_ih.shape[-1] * 2 // 3], rzn_ih[:, rzn_ih.shape[-1] * 2 // 3:]
        rz_hh, n_hh = rzn_hh[:, :rzn_hh.shape[-1] * 2 // 3], rzn_hh[:, rzn_hh.shape[-1] * 2 // 3:]
        rz = self._sigmoid(rz_ih + rz_hh)
        r, z = np.split(rz, 2, -1)
        n = np.tanh(n_ih + r * n_hh)
        h = (1 - z) * n + z * h
        return h

    def _gru(self, x, steps, w_ih, w_hh, b_ih, b_hh, h0=None):
        if h0 is None:
            h0 = np.zeros((x.shape[0], w_hh.shape[1]), np.float32)
        h = h0
        outputs = np.zeros((x.shape[0], steps, w_hh.shape[1]), np.float32)
        for t in range(steps):
            h = self._grucell(x[:, t, :], h, w_ih, w_hh, b_ih, b_hh)
            outputs[:, t, ::] = h
        return outputs

    def _encode(self, word: str) -> np.ndarray:
        chars = list(word.lower()) + ["</s>"]
        x = [self.g2idx.get(char, self.g2idx["<unk>"]) for char in chars]
        x = np.take(self.enc_emb, np.expand_dims(x, 0), axis=0)
        return x

    def predict(self, word: str) -> List[str]:
        """신경망으로 단어의 발음을 예측한다."""
        # 인코더.
        enc = self._encode(word)
        enc = self._gru(
            enc,
            len(word) + 1,
            self.enc_w_ih,
            self.enc_w_hh,
            self.enc_b_ih,
            self.enc_b_hh,
            h0=np.zeros((1, self.enc_w_hh.shape[-1]), np.float32),
        )
        last_hidden = enc[:, -1, :]

        # 디코더.
        dec = np.take(self.dec_emb, [self.p2idx["<s>"]], axis=0)  # 시작 기호.
        h = last_hidden
        preds = []
        for _ in range(20):  # 최대 반복 횟수.
            h = self._grucell(dec, h, self.dec_w_ih, self.dec_w_hh, self.dec_b_ih, self.dec_b_hh)
            logits = np.matmul(h, self.fc_w.T) + self.fc_b
            pred_idx = logits.argmax()
            if pred_idx == self.p2idx["</s>"]: break
            preds.append(pred_idx)
            dec = np.take(self.dec_emb, [pred_idx], axis=0)

        return [self.idx2p.get(idx, "<unk>") for idx in preds]

    # 기본 음소 변환.

    @staticmethod
    def _load_name_dict() -> Dict[str, List[List[str]]]:
        if os.path.exists(NAMECACHE_PATH):
            return _load_verified_pickle(
                NAMECACHE_PATH,
                "559552094c4a6e995213e3fa586330e078ef8cb3a7a95a3109e945111cd2bfc1",
            )
        return {}

    def _setup_homographs(self):
        self.homograph2features: Dict[str, Tuple[List[str], List[str], str]] = {
            "read": (["R", "EH1", "D"], ["R", "IY1", "D"], "VBD"),
            "complex": (
                ["K", "AH0", "M", "P", "L", "EH1", "K", "S"],
                ["K", "AA1", "M", "P", "L", "EH0", "K", "S"],
                "JJ",
            ),
            "lead": (["L", "IY1", "D"], ["L", "EH1", "D"], "NN"),
            "presents": (
                ["P", "R", "IY0", "Z", "EH1", "N", "T", "S"],
                ["P", "R", "EH1", "Z", "AH0", "N", "T", "S"],
                "VBZ",
            ),
        }

    def __call__(self, text: str) -> List[str]:
        original_words = word_tokenize(text)
        normalized_text = text_normalize(text)
        normalized_words = word_tokenize(normalized_text)

        corrected_words = []
        original_idx, normalized_idx = 0, 0
        while original_idx < len(original_words) and normalized_idx < len(normalized_words):
            if original_words[original_idx] == "I" and \
                    " ".join(normalized_words[normalized_idx:normalized_idx + 2]) == "the first":
                corrected_words.append("I")
                original_idx += 1
                normalized_idx += 2
            else:
                corrected_words.append(normalized_words[normalized_idx])
                original_idx += 1
                normalized_idx += 1
        if normalized_idx < len(normalized_words):
            corrected_words.extend(normalized_words[normalized_idx:])

        if not corrected_words: return []

        tokens = pos_tag(corrected_words)
        prons = []
        for o_word, pos in tokens:
            word = o_word.lower()
            if re.search("[a-z]", word) is None:
                pron = [word]
            elif word in self.homograph2features:
                pron1, pron2, pos1 = self.homograph2features[word]
                pron = pron1 if pos.startswith(pos1) else pron2
            else:
                pron = self._query_word(o_word)
            prons.extend(pron)
            prons.extend([" "])
        return prons[:-1] if prons else []

    def _query_word(self, o_word: str) -> List[str]:
        word = o_word.lower()
        if word in self.cmu:
            if o_word == "A": return ["AH0"]
            return self.cmu[word][0]
        if o_word.istitle() and word in self.namedict:
            return self.namedict[word][0]
        if word.endswith("'s") and len(word) > 2:
            base_pron = self._query_word(word[:-2])
            if base_pron:
                last_ph = base_pron[-1]
                if last_ph in {"S", "Z", "SH", "ZH", "CH", "JH"}: return base_pron + ["AH0", "Z"]
                if last_ph in {"P", "T", "K", "F", "TH"}: return base_pron + ["S"]
                return base_pron + ["Z"]
        if "-" in word and len(word) > 1:
            parts = [p for p in word.split("-") if p]
            if len(parts) > 1:
                result = [ph for part in parts for ph in self._query_word(part)]
                if result: return result
        segments = segment_text(word)
        if len(segments) > 1 and "".join(segments) == word:
            result = [ph for segment in segments for ph in self._query_word(segment)]
            if result: return result

        return self.predict(o_word)


_g2p_instance: CleanG2p | None = None


def g2p(text: str) -> List[str]:
    global _g2p_instance
    if _g2p_instance is None:
        _g2p_instance = CleanG2p()
    raw_phonemes = _g2p_instance(text)
    undesired = {" ", "<pad>", "UW", "</s>", "<s>"}
    phones = ["UNK" if ph == "<unk>" else ph for ph in raw_phonemes if ph not in undesired]
    return replace_phs(phones)


def english_to_phones(text: str) -> List[int]:
    phones = g2p(text)
    phones = [symbol_to_id_v2[ph] for ph in phones]
    return phones
