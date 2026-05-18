from __future__ import annotations
import math
import random
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agents.environment import RoadSegment


@dataclass
class DriverAgent:
    """
    배송 기사 에이전트 — '노동' 중심 설계
    ----------------------------------------
    max_legal_hours     : 법정 최대 근로시간 (8h or 12h)
                          초과 시 강제 퇴근(작동 중지)
    current_working_hours: 누적 노동 시간
    fatigue_penalty     : 피로도 가중치
                          평지 3분 → 후반 5분 → 7분으로 증가
    """
    agent_id: int
    lat: float
    lon: float
    max_legal_hours: float
    assigned_deliveries: int

    current_working_hours: float = 0.0
    delivered: int = 0
    over_limit: bool = False          # 법정시간 초과 → 강제 퇴근
    walking: bool = False             # 도로폭 <2m → 도보 강제전환
    state: str = "driving"            # driving / walking / done
    target_lat: float = 0.0
    target_lon: float = 0.0
    current_road: Optional["RoadSegment"] = None
    wait_ticks: int = 0
    fatigue_history: List[float] = field(default_factory=list)

    # ── 피로도 함수 ──────────────────────────────────────────────
    @property
    def fatigue_penalty(self) -> float:
        """건당 기본 소요 시간(분): 노동 누적에 따라 단계적 증가"""
        h = self.current_working_hours
        if h < 3:
            return 3.0
        elif h < 6:
            return 5.0
        return 7.0

    # ── 경사도 가중치 ────────────────────────────────────────────
    @property
    def slope_multiplier(self) -> float:
        """도보 오르막 시 시간 2~3배"""
        if self.current_road is None:
            return 1.0
        s = abs(self.current_road.slope_deg)
        if s >= 25:
            return 3.0
        elif s >= 15:
            return 2.0
        return 1.0

    # ── 실질 배송 1건 소요 시간 ──────────────────────────────────
    @property
    def effective_mins(self) -> float:
        walk_mult = 1.5 if self.walking else 1.0
        return self.fatigue_penalty * self.slope_multiplier * walk_mult

    @property
    def hours_ratio(self) -> float:
        return min(1.0, self.current_working_hours / self.max_legal_hours)

    # ── 표시용 색상 / 레이블 ─────────────────────────────────────
    @property
    def status_color(self) -> str:
        if self.over_limit:
            return "#8957e5"   # 보라 — 퇴근
        if self.walking:
            return "#f0883e"   # 주황 — 도보
        return "#388bfd"       # 파랑 — 운행

    @property
    def status_label(self) -> str:
        if self.over_limit:
            return "⛔ 퇴근"
        if self.walking:
            return "🚶 도보"
        return "🚛 운행"

    @property
    def icon_type(self) -> str:
        """지도 마커 아이콘 종류"""
        if self.over_limit:
            return "done"
        if self.walking:
            return "walk"
        return "truck"

    # ── 1틱 이동 처리 ────────────────────────────────────────────
    def step(self, stops: list, nearest_road_fn) -> None:
        if self.over_limit or self.delivered >= self.assigned_deliveries:
            self.state = "done"
            return
        if self.wait_ticks > 0:
            self.wait_ticks -= 1
            return

        # 도로 정보 갱신
        self.current_road = nearest_road_fn(self.lat, self.lon)

        # 도로폭 2m 이하 → 도보 강제전환 (핵심 로직)
        if self.current_road:
            self.walking = self.current_road.min_width <= 2.0
        else:
            self.walking = False
        self.state = "walking" if self.walking else "driving"

        # 목적지 방향 이동
        dlat = self.target_lat - self.lat
        dlon = self.target_lon - self.lon
        dist = math.hypot(dlat, dlon)
        speed = 0.00007 if self.walking else 0.00014

        if dist < 0.0003:
            # 배송 완료
            self.delivered += 1
            self.current_working_hours += self.effective_mins / 60
            self.fatigue_history.append(round(self.current_working_hours, 3))

            if self.current_working_hours >= self.max_legal_hours:
                self.over_limit = True
                self.state = "done"
                return

            if self.delivered < self.assigned_deliveries and stops:
                tgt = random.choice(stops)
                self.target_lat, self.target_lon = tgt
                self.wait_ticks = max(1, int(self.effective_mins * 0.7))
        else:
            self.lat += dlat / dist * speed
            self.lon += dlon / dist * speed
