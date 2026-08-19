"""Scheduler —— 分時排程（Night Shift）。"""

from __future__ import annotations

from datetime import datetime

from narratron.hardware.pools import HardwarePool


class Scheduler:
    """高精度任務集中於夜間離峰電價時段。"""

    def schedule(self, pool: HardwarePool, ready_at: datetime | None = None) -> None:
        raise NotImplementedError("Scheduler Night Shift 待 Alpha")
