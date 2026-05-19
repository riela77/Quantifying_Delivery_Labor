"""
DriverAgent — 도로 노드 경로를 따라 이동
- 직선 이동 대신 find_path()로 구한 노드 경로를 순서대로 이동
- 협로(≤2m) 진입 시 도보 전환 → 아이콘 변경
- 피로도 누적 + 법정시간 초과 시 강제 퇴근
"""
from __future__ import annotations
import math
import random
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from agents.environment import EnvironmentAgent, RoadSegment


@dataclass
class DriverAgent:
    agent_id: int
    lat: float
    lon: float
    max_legal_hours: float
    assigned_deliveries: int

    current_working_hours: float = 0.0
    delivered: int = 0
    over_limit: bool = False
    walking: bool = False
    state: str = "driving"

    # 현재 이동 경로 (노드 좌표 리스트)
    route: List[Tuple[float, float]] = field(default_factory=list)
    route_idx: int = 0      # 현재 경로에서 몇 번째 노드로 가는 중
    target_stop_idx: int = 0

    current_road: Optional["RoadSegment"] = None
    wait_ticks: int = 0
    fatigue_history: List[float] = field(default_factory=list)

    # ── 피로도 함수 ──────────────────────────────────────────────
    @property
    def fatigue_penalty(self) -> float:
        h = self.current_working_hours
        if h < 3: return 3.0
        if h < 6: return 5.0
        return 7.0

    @property
    def slope_multiplier(self) -> float:
        if not self.current_road: return 1.0
        s = self.current_road.slope_abs
        if s >= 25: return 3.0
        if s >= 15: return 2.0
        return 1.0

    @property
    def effective_mins(self) -> float:
        walk_mult = 1.5 if self.walking else 1.0
        return self.fatigue_penalty * self.slope_multiplier * walk_mult

    @property
    def hours_ratio(self) -> float:
        return min(1.0, self.current_working_hours / self.max_legal_hours)

    @property
    def status_color(self) -> str:
        if self.over_limit: return "#8957e5"
        if self.walking:    return "#f0883e"
        return "#388bfd"

    @property
    def status_label(self) -> str:
        if self.over_limit: return "⛔ 퇴근"
        if self.walking:    return "🚶 도보"
        return "🚛 운행"

    # ── 1틱 이동 ─────────────────────────────────────────────────
    def step(self, stops: list, env: "EnvironmentAgent") -> None:
        if self.over_limit or self.delivered >= self.assigned_deliveries:
            self.state = "done"; return
        if self.wait_ticks > 0:
            self.wait_ticks -= 1; return

        # 경로가 없거나 다 소진되면 새 목적지로 경로 탐색
        if not self.route or self.route_idx >= len(self.route):
            if self.delivered < self.assigned_deliveries and stops:
                target = random.choice(stops)
                # 실제 도로 노드 경로 탐색
                self.route = env.find_path(self.lat, self.lon, target[0], target[1])
                self.route_idx = 0
            else:
                return

        if self.route_idx >= len(self.route):
            return

        # 현재 목표 노드
        node_lat, node_lon = self.route[self.route_idx]
        dlat = node_lat - self.lat
        dlon = node_lon - self.lon
        dist = math.hypot(dlat, dlon)

        # 현재 위치의 도로 정보 갱신
        self.current_road = env.nearest_road(self.lat, self.lon)
        self.walking = (self.current_road is not None and self.current_road.is_narrow)
        self.state = "walking" if self.walking else "driving"

        speed = 0.00006 if self.walking else 0.00013

        if dist < 0.0002:
            # 노드 도달 → 다음 노드로
            self.lat, self.lon = node_lat, node_lon
            self.route_idx += 1

            # 경로 끝 = 배송지 도달
            if self.route_idx >= len(self.route):
                self.delivered += 1
                mins = self.effective_mins
                self.current_working_hours += mins / 60
                self.fatigue_history.append(round(self.current_working_hours, 3))

                if self.current_working_hours >= self.max_legal_hours:
                    self.over_limit = True; self.state = "done"; return

                # 다음 배송지 경로 탐색
                if self.delivered < self.assigned_deliveries and stops:
                    target = random.choice(stops)
                    self.route = env.find_path(self.lat, self.lon, target[0], target[1])
                    self.route_idx = 0
                    self.wait_ticks = max(1, int(mins * 0.6))
        else:
            self.lat += dlat / dist * speed
            self.lon += dlon / dist * speed