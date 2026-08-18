"""CosyVoice 3 model runtime for the festival AI guide.

This process is intentionally separate from ``app.main``. CosyVoice brings a large
PyTorch runtime and model weights, so the transactional festival API should remain
lightweight and can proxy to this service through VOICE_RUNTIME_URL.
"""

import io
import base64
import logging
import os
import sys
import threading
import types
from collections import OrderedDict
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class SynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)
    language: str = Field(default="ko-KR", min_length=2, max_length=16)
    provider: str = "cosyvoice3"


app = FastAPI(title="FEST-ON Voice Runtime", version="0.1.0")
_load_lock = threading.Lock()
_audio_cache: OrderedDict[str, bytes] = OrderedDict()
_audio_cache_lock = threading.Lock()
_AUDIO_CACHE_LIMIT = 32


def _setting(name: str) -> str:
    return os.getenv(name, "").strip()


def _install_inference_compat() -> None:
    """CosyVoice imports pyworld from its training-only dataset module.

    The inference path never calls those pitch-extraction helpers, and building
    pyworld on Windows needs a full C++ toolchain. Keep inference usable without
    pulling the training compiler into the local kiosk setup.
    """
    try:
        import pyworld  # noqa: F401
        return
    except ImportError:
        module = types.ModuleType("pyworld")

        def unavailable(*_args, **_kwargs):
            raise RuntimeError("pyworld는 학습/피치 추출 경로에서만 필요합니다.")

        module.harvest = unavailable
        module.dio = unavailable
        module.stonemask = unavailable
        sys.modules["pyworld"] = module


@lru_cache(maxsize=1)
def _cosyvoice():
    repo_path = _setting("COSYVOICE_REPO_PATH")
    model_path = _setting("COSYVOICE_MODEL_PATH")
    if not repo_path or not model_path:
        raise RuntimeError("COSYVOICE_REPO_PATH와 COSYVOICE_MODEL_PATH를 설정해 주세요.")
    for import_path in (repo_path, os.path.join(repo_path, "third_party", "Matcha-TTS")):
        if import_path not in sys.path:
            sys.path.insert(0, import_path)
    _install_inference_compat()
    try:
        from cosyvoice.cli.cosyvoice import CosyVoice3
    except ImportError as error:
        raise RuntimeError("CosyVoice 저장소 의존성이 설치되지 않았습니다.") from error
    with _load_lock:
        return CosyVoice3(model_path)


def _wav_bytes(speech, sample_rate: int) -> bytes:
    import numpy as np
    import soundfile as sf

    samples = speech.squeeze().detach().cpu().numpy().astype(np.float32)
    buffer = io.BytesIO()
    sf.write(buffer, samples, sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def _language_tag(language: str) -> str:
    code = language.lower().split("-", 1)[0].split("_", 1)[0]
    return code if code in {"zh", "en", "ja", "yue", "ko"} else "ko"


def _synthesize_with_cosyvoice(text: str, language: str) -> bytes:
    engine = _cosyvoice()
    repo_path = _setting("COSYVOICE_REPO_PATH")
    prompt_wav = _setting("COSYVOICE_PROMPT_WAV") or os.path.join(repo_path, "asset", "zero_shot_prompt.wav")
    if not os.path.isfile(prompt_wav):
        raise RuntimeError("COSYVOICE_PROMPT_WAV 참조 음성을 찾을 수 없습니다.")
    language_tag = _language_tag(language)
    # CosyVoice3의 cross-lingual 토큰으로 한국어(<|ko|>)를 명시한다. 참조 음성은
    # 한국어 샘플로 교체할 수 있으며, 교체하지 않으면 공식 기본 샘플을 사용한다.
    cosyvoice_text = f"You are a helpful assistant.<|endofprompt|><|{language_tag}|>{text}"
    result = next(engine.inference_cross_lingual(cosyvoice_text, prompt_wav, stream=False))
    sample_rate = int(getattr(engine, "sample_rate", 22_050))
    return _wav_bytes(result["tts_speech"], sample_rate)


def _cached_audio(key: str) -> bytes | None:
    with _audio_cache_lock:
        value = _audio_cache.get(key)
        if value is not None:
            _audio_cache.move_to_end(key)
        return value


def _store_audio(key: str, audio: bytes) -> None:
    with _audio_cache_lock:
        _audio_cache[key] = audio
        _audio_cache.move_to_end(key)
        while len(_audio_cache) > _AUDIO_CACHE_LIMIT:
            _audio_cache.popitem(last=False)


@app.get("/health")
def health():
    return {
        "status": "configured" if _setting("COSYVOICE_MODEL_PATH") else "not_configured",
        "provider": "cosyvoice3",
        "mode": "zero-shot",
        "ready": _cosyvoice.cache_info().currsize > 0,
        "cacheSize": len(_audio_cache),
    }


@app.on_event("startup")
def warm_model() -> None:
    """Load the large model before the first visitor asks a question."""
    def load() -> None:
        try:
            _cosyvoice()
        except Exception:
            import logging
            logging.exception("CosyVoice warm-up failed; request-time retry remains enabled.")

    threading.Thread(target=load, name="cosyvoice-warmup", daemon=True).start()


@app.post("/v1/speech/synthesize")
def synthesize(body: SynthesisRequest):
    if body.provider != "cosyvoice3":
        raise HTTPException(status_code=501, detail="현재 로컬 런타임은 CosyVoice 3를 지원합니다.")
    try:
        cache_key = f"{body.language}:{body.text}"
        audio = _cached_audio(cache_key)
        if audio is None:
            audio = _synthesize_with_cosyvoice(body.text, body.language)
            _store_audio(cache_key, audio)
    except Exception as error:  # 모델 로딩·GPU·가중치 오류를 API 응답으로 변환
        logging.exception("CosyVoice synthesis failed")
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {
        "audioBase64": base64.b64encode(audio).decode("ascii"),
        "mimeType": "audio/wav",
        "provider": "cosyvoice3",
    }
