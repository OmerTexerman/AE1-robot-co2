import os
from pathlib import Path
from threading import Lock


SUPPORTED_PROVIDERS = {"openai", "local"}
_LOCAL_MODEL_CACHE = {}
_LOCAL_MODEL_LOCK = Lock()


def normalize_provider(requested_provider: str | None) -> str:
    provider = (requested_provider or os.getenv("TRANSCRIBE_PROVIDER", "local")).strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported provider '{provider}'.")
    return provider


def transcribe_audio(audio_path: Path, provider: str) -> dict[str, str | float | None]:
    normalized_provider = normalize_provider(provider)
    if normalized_provider == "openai":
        transcription = transcribe_with_openai(audio_path)
    else:
        transcription = transcribe_with_local_whisper(audio_path)

    return {
        "provider": normalized_provider,
        "text": str(transcription["text"]).strip(),
        "language": transcription.get("language") or "",
        "language_confidence": transcription.get("language_confidence"),
    }


def transcribe_with_openai(audio_path: Path) -> dict[str, str | float | None]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "OpenAI transcription requires the openai package. Install dependencies first."
        ) from exc

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    model = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
    client = OpenAI(api_key=api_key)

    with audio_path.open("rb") as audio_file:
        transcription = client.audio.transcriptions.create(
            model=model,
            file=audio_file,
        )

    text = getattr(transcription, "text", "").strip()
    if not text:
        raise RuntimeError("The OpenAI transcription service returned empty text.")
    return {
        "text": text,
        "language": getattr(transcription, "language", None),
        "language_confidence": None,
    }


def transcribe_with_local_whisper(audio_path: Path) -> dict[str, str | float | None]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "Local transcription requires faster-whisper. Install dependencies first."
        ) from exc

    model_name = os.getenv("LOCAL_WHISPER_MODEL", "small")
    device = os.getenv("WHISPER_DEVICE", "auto")
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

    model = get_local_whisper_model(WhisperModel, model_name, device, compute_type)
    segments, info = model.transcribe(str(audio_path), vad_filter=True)
    text = " ".join(segment.text.strip() for segment in segments).strip()

    if not text:
        raise RuntimeError("The local Whisper model returned empty text.")
    return {
        "text": text,
        "language": getattr(info, "language", None),
        "language_confidence": getattr(info, "language_probability", None),
    }


def get_local_whisper_model(
    whisper_model_cls,
    model_name: str,
    device: str,
    compute_type: str,
):
    cache_key = (model_name, device, compute_type)
    model = _LOCAL_MODEL_CACHE.get(cache_key)
    if model is not None:
        return model

    with _LOCAL_MODEL_LOCK:
        model = _LOCAL_MODEL_CACHE.get(cache_key)
        if model is None:
            model = whisper_model_cls(model_name, device=device, compute_type=compute_type)
            _LOCAL_MODEL_CACHE[cache_key] = model

    return model
