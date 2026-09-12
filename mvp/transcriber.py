from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable


class LocalTranscriber:
    """延迟加载本地 Whisper 模型，避免启动网页时占用大量内存。"""

    def __init__(self, model_name: str = "small", on_stage: Callable[[str], None] | None = None) -> None:
        self.model_name = model_name
        self.on_stage = on_stage
        self._model = None

    def load(self):
        if self._model is None:
            if self.on_stage:
                self.on_stage(f"正在加载 {self.model_name} 转写模型（首次使用会先下载模型）")
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
        fast_mode = self.model_name == "small"
        segments, _ = self.load().transcribe(
            str(path),
            language="zh",
            vad_filter=True,
            beam_size=1 if fast_mode else 5,
            best_of=1 if fast_mode else 5,
            condition_on_previous_text=False,
            initial_prompt=initial_prompt or None,
        )
        return "".join(self._clean(segment.text) for segment in segments).strip()

    @staticmethod
    def _clean(text: str) -> str:
        return " ".join(text.split()) + (" " if text.strip() else "")

    def transcribe_many(self, paths: Iterable[str | Path]) -> dict[str, str]:
        return {str(path): self.transcribe(path) for path in paths}
