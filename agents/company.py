from __future__ import annotations
from dataclasses import dataclass
from typing import List


@dataclass
class CompanyAgent:
    """
    플랫폼 에이전트 — 물동량 할당 주체
    ----------------------------------------
    daily_volume      : 오늘 해당 구역에 배송해야 할 총 물동량
    assigned_drivers  : 현재 할당된 기사 수
    """
    daily_volume: int
    assigned_drivers: int

    def allocate(self) -> List[int]:
        """
        기사별 배송 건수 균등 배분
        나머지는 앞 기사들에게 1건씩 추가
        """
        if self.assigned_drivers == 0:
            return []
        base = self.daily_volume // self.assigned_drivers
        remainder = self.daily_volume % self.assigned_drivers
        return [
            base + (1 if i < remainder else 0)
            for i in range(self.assigned_drivers)
        ]

    def utilization_rate(self) -> float:
        """기사 1인당 평균 물동량"""
        if self.assigned_drivers == 0:
            return 0.0
        return self.daily_volume / self.assigned_drivers

    def summary(self) -> dict:
        return {
            "daily_volume": self.daily_volume,
            "assigned_drivers": self.assigned_drivers,
            "per_driver_avg": round(self.utilization_rate(), 1),
            "allocation": self.allocate(),
        }
