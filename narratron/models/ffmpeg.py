"""FFmpeg。綁定 Light Core，供 Muxer 合流。"""

from __future__ import annotations


class FFmpeg:
    def mux(self, media_uris: list[str]) -> str:
        raise NotImplementedError("FFmpeg 合流待 Alpha Q4")
