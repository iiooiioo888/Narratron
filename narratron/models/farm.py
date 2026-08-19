"""Model Farm 集合介面。本階段禁止真實 API 呼叫。"""

from __future__ import annotations

from narratron.models.ffmpeg import FFmpeg
from narratron.models.flux import Flux
from narratron.models.tts import TTS
from narratron.models.veo import Veo
from narratron.models.wan import Wan


class ModelFarm:
    def __init__(
        self,
        flux: Flux | None = None,
        wan: Wan | None = None,
        veo: Veo | None = None,
        tts: TTS | None = None,
        ffmpeg: FFmpeg | None = None,
    ) -> None:
        self.flux = flux or Flux()
        self.wan = wan or Wan()
        self.veo = veo or Veo()
        self.tts = tts or TTS()
        self.ffmpeg = ffmpeg or FFmpeg()

    def generate_image(self, prompt: str) -> str:
        return self.flux.generate(prompt)

    def generate_video(self, prompt: str) -> str:
        return self.wan.generate(prompt)

    def generate_speech(self, text: str) -> str:
        return self.tts.synthesize(text)

    def mux(self, media_uris: list[str]) -> str:
        return self.ffmpeg.mux(media_uris)
