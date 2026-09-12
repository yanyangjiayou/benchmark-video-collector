from types import SimpleNamespace

from mvp.transcriber import LocalTranscriber


class Model:
    def __init__(self):
        self.options = None

    def transcribe(self, path, **options):
        self.options = options
        return [SimpleNamespace(text=" 测试 ")], None


def test_standard_model_uses_fast_decoding(tmp_path):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"test")
    transcriber = LocalTranscriber("small")
    transcriber._model = Model()
    assert transcriber.transcribe(media) == "测试"
    assert transcriber._model.options["beam_size"] == 1
    assert transcriber._model.options["best_of"] == 1
    assert transcriber._model.options["condition_on_previous_text"] is False


def test_accurate_model_keeps_beam_search(tmp_path):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"test")
    transcriber = LocalTranscriber("medium")
    transcriber._model = Model()
    transcriber.transcribe(media)
    assert transcriber._model.options["beam_size"] == 5
