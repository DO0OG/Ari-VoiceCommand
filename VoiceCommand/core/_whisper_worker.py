"""
Whisper STT 워커 프로세스.
메인 프로세스와 stdin/stdout IPC로 통신:
  - 초기화 완료 시 stdout에 "READY\\n" 출력
  - 입력: base64 인코딩된 WAV 바이트 한 줄
  - 출력: 전사 텍스트 한 줄, 결과 없으면 "__NONE__"
  - "QUIT" 수신 시 종료
"""
import sys
import io
import os
import wave
import base64

# 메인 프로세스와 동일한 KMP 설정 상속 (혹은 기본 적용)
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")


def _wav_bytes_to_numpy(wav_bytes: bytes):
    import numpy as np

    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
        sample_width = wf.getsampwidth()
        channels = wf.getnchannels()

    if sample_width == 1:
        audio = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        audio = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        return None

    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio


def main():
    if len(sys.argv) < 4:
        sys.stderr.write("Usage: _whisper_worker.py <model_size> <device> <compute_type>\n")
        sys.exit(1)

    model_size, device, compute_type = sys.argv[1], sys.argv[2], sys.argv[3]

    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as exc:
        sys.stderr.write(f"MODEL_LOAD_ERROR: {exc}\n")
        sys.stderr.flush()
        sys.exit(1)

    sys.stdout.write("READY\n")
    sys.stdout.flush()

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        if line == "QUIT":
            break
        try:
            wav_bytes = base64.b64decode(line)
            audio_np = _wav_bytes_to_numpy(wav_bytes)
            if audio_np is None:
                sys.stdout.write("__NONE__\n")
                sys.stdout.flush()
                continue
            segments, _ = model.transcribe(
                audio_np,
                language="ko",
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            sys.stdout.write((text if text else "__NONE__") + "\n")
            sys.stdout.flush()
        except Exception:
            sys.stdout.write("__NONE__\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
