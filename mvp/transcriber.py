from __future__ import annotations

from pathlib import Path
from typing import Iterable


class LocalTranscriber:
    """延迟加载本地 Whisper 模型，避免启动网页时占用大量内存。"""

    def __init__(self, model_name: str = "small") -> None:
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.model_name,
                device="cpu",
                compute_type="int8",
            )
        return self._model

    def transcribe(self, media_path: str | Path, initial_prompt: str = "") -> str:
        path = Path(media_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        segments, _ = self._load().transcribe(
            str(path),
            language="zh",
            vad_filter=True,
            beam_size=5,
            initial_prompt=initial_prompt or None,
        )
        return "".join(self._clean(segment.text) for segment in segments).strip()

    @staticmethod
    def _clean(text: str) -> str:
        return " ".join(text.split()) + (" " if text.strip() else "")

    def transcribe_many(self, paths: Iterable[str | Path]) -> dict[str, str]:
        return {str(path): self.transcribe(path) for path in paths}
