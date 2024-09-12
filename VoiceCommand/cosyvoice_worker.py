"""
CosyVoice3 워커 프로세스 — 이진 스트리밍 프로토콜
  stdin  : UTF-8 텍스트 명령 (한 줄 = 합성할 텍스트 / "EXIT")
  stdout : 이진 PCM 스트림  [4B uint32 크기][float32 PCM ...] 크기=0이면 문장 끝
  stderr : 제어 메시지 (SAMPLERATE:<n> / READY / DONE / ERROR:<msg>)
"""
import sys
import os
import struct
import argparse
import logging

import numpy as np

# ── 이진 스트림 오염 방지 ─────────────────────────────────────────────────────
_BINARY_OUT = sys.stdout.buffer
sys.stdout = sys.stderr  # 텍스트 출력 → stderr

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

# SDPA 사용 (eager 대신) — sliding window 경고가 뜨지만 속도는 더 빠름
# eager 강제 설정을 하지 않음 (기본 SDPA 유지)


def setup_paths(cosyvoice_dir):
    matcha_dir = os.path.join(cosyvoice_dir, "third_party", "Matcha-TTS")
    for p in [cosyvoice_dir, matcha_dir]:
        if p not in sys.path:
            sys.path.insert(0, p)
    # eager 강제 해제 — SDPA가 eager보다 빠름 (sliding window 경고는 무시)


def write_chunk(data: bytes):
    """이진 stdout에 길이 접두어 + PCM 데이터 씀"""
    _BINARY_OUT.write(struct.pack("<I", len(data)))
    _BINARY_OUT.write(data)
    _BINARY_OUT.flush()


def write_end():
    """문장 종료 신호 (크기 0)"""
    _BINARY_OUT.write(struct.pack("<I", 0))
    _BINARY_OUT.flush()


def ctrl(msg: str):
    """stderr에 제어 메시지 출력"""
    print(msg, file=sys.stderr, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--reference-wav", required=True)
    parser.add_argument("--reference-text", default="")
    parser.add_argument("--cosyvoice-dir", default=r"D:\Git\CosyVoice")
    parser.add_argument("--speed", type=float, default=1.0)
    args = parser.parse_args()

    setup_paths(args.cosyvoice_dir)

    # 모델 로드
    try:
        from cosyvoice.cli.cosyvoice import CosyVoice3 as ModelClass
    except ImportError:
        from cosyvoice.cli.cosyvoice import CosyVoice2 as ModelClass

    # GPU 최적화 플래그
    try:
        import torch
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
    except Exception:
        pass

    model = ModelClass(args.model_dir, load_trt=False, fp16=True)

    # ── 최적화 1: Flow ODE steps 10→5 (각 청크 ~50% 빠름, 품질 소폭 하락)
    # register_forward_pre_hook으로 n_timesteps 인자만 교체 (nn.Module 호환)
    try:
        def _ode_hook(module, args, kwargs):
            kwargs = dict(kwargs)
            kwargs['n_timesteps'] = 5
            return args, kwargs
        model.model.flow.decoder.register_forward_pre_hook(_ode_hook, with_kwargs=True)
        ctrl("INFO:Flow ODE steps 10→5 적용됨")
    except Exception as e:
        ctrl(f"INFO:Flow ODE patch 생략 ({e})")

    sample_rate = model.sample_rate

    ref_text = args.reference_text
    if ref_text and "<|endofprompt|>" not in ref_text:
        ref_text = f"You are a helpful assistant.<|endofprompt|>{ref_text}"

    # ── 핵심 최적화: reference.wav 특징 사전 추출 ────────────────────────────
    # inference_zero_shot은 매번 speech_token, embedding, speech_feat를
    # ONNX(CPU)로 추출하여 2~3초를 낭비한다.
    # reference.wav는 고정이므로 한 번만 계산하고 spk2info에 등록한다.
    SPK_ID = "ari"
    try:
        import torch
        frontend = model.frontend
        with torch.no_grad():
            prompt_text_token, prompt_text_token_len = frontend._extract_text_token(ref_text)
            speech_feat, speech_feat_len = frontend._extract_speech_feat(args.reference_wav)
            speech_token, speech_token_len = frontend._extract_speech_token(args.reference_wav)
            if sample_rate == 24000:  # CosyVoice2/3
                token_len = min(int(speech_feat.shape[1] / 2), speech_token.shape[1])
                speech_feat = speech_feat[:, :2 * token_len]
                speech_feat_len[:] = 2 * token_len
                speech_token = speech_token[:, :token_len]
                speech_token_len[:] = token_len
            embedding = frontend._extract_spk_embedding(args.reference_wav)
        frontend.spk2info[SPK_ID] = {
            'prompt_text': prompt_text_token,
            'prompt_text_len': prompt_text_token_len,
            'llm_prompt_speech_token': speech_token,
            'llm_prompt_speech_token_len': speech_token_len,
            'flow_prompt_speech_token': speech_token,
            'flow_prompt_speech_token_len': speech_token_len,
            'prompt_speech_feat': speech_feat,
            'prompt_speech_feat_len': speech_feat_len,
            'llm_embedding': embedding,
            'flow_embedding': embedding,
        }
        ctrl("INFO:reference.wav 특징 사전 추출 완료 (이후 호출에서 ONNX 생략)")
    except Exception as e:
        SPK_ID = ""  # 실패 시 기존 방식 fallback
        ctrl(f"INFO:특징 사전추출 실패, fallback: {e}")

    def make_gen(text, stream):
        """SPK_ID 캐시 사용 시 ONNX 추출 생략"""
        if SPK_ID:
            return model.inference_zero_shot(
                tts_text=text,
                prompt_text=ref_text,
                prompt_wav=args.reference_wav,
                zero_shot_spk_id=SPK_ID,
                stream=stream,
                speed=args.speed,
            )
        elif ref_text:
            return model.inference_zero_shot(
                tts_text=text,
                prompt_text=ref_text,
                prompt_wav=args.reference_wav,
                stream=stream,
                speed=args.speed,
            )
        else:
            return model.inference_cross_lingual(
                tts_text=text,
                prompt_wav=args.reference_wav,
                stream=stream,
                speed=args.speed,
            )

    # GPU warmup — 첫 CUDA 커널 컴파일 (초회 실행 시 ~90초, 이후 PyTorch 캐시 사용)
    try:
        ctrl("INFO:GPU warmup 시작 (초회만 ~90초 소요)...")
        for _ in make_gen("네.", stream=True):
            pass  # 모든 청크 소비 → generator 정상 완료 및 정리
        ctrl("INFO:GPU warmup 완료")
    except Exception as e:
        ctrl(f"INFO:GPU warmup 생략 ({e})")

    ctrl(f"SAMPLERATE:{sample_rate}")

    # GPU warmup 제거 — CUDA 커널 컴파일은 첫 실제 TTS 호출 시 발생.
    # 워밍업을 여기서 하면 초회에 5~10분이 걸려 타임아웃이 터지므로
    # 워커는 모델 로드 직후 바로 READY를 보낸다.
    # (두 번째 호출부터는 캐시 사용으로 빠름)

    ctrl("READY")

    # 요청 처리 루프
    for raw in sys.stdin:
        text = raw.strip()
        if not text or text == "EXIT":
            break

        try:
            n = 0
            for result in make_gen(text, stream=True):
                chunk = result.get("tts_speech") if isinstance(result, dict) else result
                if chunk is not None:
                    arr = chunk.squeeze().cpu().numpy().astype(np.float32)
                    write_chunk(arr.tobytes())
                    n += 1

            write_end()
            ctrl(f"DONE:{n}")

        except Exception as e:
            write_end()
            ctrl(f"ERROR:{e}")


if __name__ == "__main__":
    main()
