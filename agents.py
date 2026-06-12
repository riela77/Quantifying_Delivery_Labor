"""
agents.py - 배달 시뮬레이션 에이전트 (Mesa-Geo GeoAgent 기반)

HouseAgent     : 배송 목적지
TruckWalkAgent : 트럭+도보 배달원
"""

import random
from mesa_geo import GeoAgent
from shapely.geometry import Point

# ── 속도/비용 상수 ────────────────────────────────────────────────
TRUCK_SPEED_KMH   = 60.0
WALK_SPEED_KMH    = 4.0
TRUCK_COST_PER_KM = 800

STEP_MIN        = 0.25   # 1 step = 15초 (4배 세분화)
STEEP_THRESHOLD = 15.0   # 험지 기준 (15도 이상)


def walk_speed(slope_deg=0.0):
    return max(1.5, WALK_SPEED_KMH - abs(slope_deg) * 0.3)

def travel_time_min(dist_m, speed_kmh):
    return (dist_m / 1000) / speed_kmh * 60

def speed_to_deg_per_step(speed_kmh):
    """km/h → step당 이동 도(degree). 1도 ≈ 111km"""
    return speed_kmh * STEP_MIN / 60 / 111.0

def route_dist_m(route):
    total = 0.0
    for i in range(len(route) - 1):
        dx = (route[i+1][0] - route[i][0]) * 111000
        dy = (route[i+1][1] - route[i][1]) * 111000
        total += (dx**2 + dy**2) ** 0.5
    return total


class HouseAgent(GeoAgent):
    """배송 목적지"""
    def __init__(self, model, geometry, crs, pkg_kg=None):
        super().__init__(model, geometry, crs)
        self.atype   = "house"
        self.visited = False
        self.pkg_kg  = pkg_kg or round(random.uniform(1.0, 15.0), 1)

    def step(self):
        pass


class TruckWalkAgent(GeoAgent):
    """트럭 + 도보 배달원"""

    def __init__(self, model, geometry, crs):
        super().__init__(model, geometry, crs)
        self.atype            = "truck"
        self.phase            = "idle"
        self.route_idx        = 0
        self.house_idx        = 0
        self.segments         = []
        self.current_segment  = None
        self.current_route    = []
        self.total_time_min   = 0.0
        self.total_cost_won   = 0.0
        self.truck_dist_m     = 0.0
        self.walk_dist_m      = 0.0
        self.delivered_kg     = 0.0
        self.delivered_count  = 0
        self.current_slope    = 0.0
        self.park_pos         = None

        self.carried_kg       = 0.0
        self.steep_crossings  = 0
        self._was_steep       = False
        self.cumul_walk_m     = 0.0
        self.cumul_truck_m    = 0.0
        self.elapsed_steps    = 0

    def set_segments(self, segments):
        self.segments = segments
        for seg in segments:
            td = route_dist_m(seg["truck"])
            wd = route_dist_m(seg["walk"])
            avg_slope = (sum(seg["slope_walk"]) / len(seg["slope_walk"])
                         if seg["slope_walk"] else 0.0)
            self.truck_dist_m   += td
            self.walk_dist_m    += wd
            self.total_time_min += (travel_time_min(td, TRUCK_SPEED_KMH) +
                                    travel_time_min(wd, walk_speed(avg_slope)))
            self.total_cost_won += (td / 1000) * TRUCK_COST_PER_KM
            self.delivered_kg   += seg["house"].pkg_kg
        self._load_segment(0)

    def _load_segment(self, idx):
        if idx >= len(self.segments):
            self.phase      = "done"
            self.atype      = "done"
            self.carried_kg = 0.0
            return
        self.house_idx       = idx
        self.current_segment = self.segments[idx]
        self.park_pos        = self.current_segment["park_pos"]
        self.phase           = "truck"
        self.atype           = "truck"
        self.route_idx       = 0
        self.current_route   = self.current_segment["truck"]
        self.carried_kg      = 0.0

    def _enter_walk(self):
        self.phase         = "walk"
        self.atype         = "walk"
        self.route_idx     = 0
        self.current_route = self.current_segment["walk"]
        self.carried_kg    = self.current_segment["house"].pkg_kg

    def step(self):
        if self.phase in ("idle", "done"):
            return

        self.elapsed_steps += 1
        route = self.current_route

        if self.route_idx >= len(route):
            if self.phase == "truck":
                self._enter_walk()
            elif self.phase == "walk":
                self.current_segment["house"].visited = True
                self.current_segment["house"].atype   = "visited"
                self.delivered_count += 1
                self.carried_kg      = 0.0
                self._load_segment(self.house_idx + 1)
            return

        # 현재 스텝 속도 계산
        if self.phase == "walk":
            slopes = self.current_segment.get("slope_walk", [])
            si     = min(self.route_idx, len(slopes) - 1) if slopes else 0
            slope  = slopes[si] if slopes else 0.0
            spd    = speed_to_deg_per_step(walk_speed(slope))
        else:
            slope = 0.0
            spd   = speed_to_deg_per_step(TRUCK_SPEED_KMH)

        self.current_slope = slope

        is_steep = (abs(slope) >= STEEP_THRESHOLD and self.phase == "walk")
        if is_steep and not self._was_steep:
            self.steep_crossings += 1
        self._was_steep = is_steep

        # ── 매 스텝 정확히 spd만큼 경로를 따라 이동 ──────────────
        # (포인트 간격이 넓어도 건너뛰지 않고 부드럽게 전진)
        remaining = spd
        moved_deg = 0.0

        while remaining > 0 and self.route_idx < len(route):
            tlon, tlat = route[self.route_idx]
            cx, cy     = self.geometry.x, self.geometry.y
            dx, dy     = tlon - cx, tlat - cy
            dist       = (dx**2 + dy**2) ** 0.5

            if dist == 0:
                self.route_idx += 1
                continue

            if dist <= remaining:
                # 이 포인트까지 도달 후 남은 거리로 계속 진행
                self.geometry  = Point(tlon, tlat)
                self.route_idx += 1
                moved_deg  += dist
                remaining  -= dist
                # 경로 끝이면 중단
                if self.route_idx >= len(route):
                    break
            else:
                # remaining만큼만 전진
                ratio         = remaining / dist
                self.geometry = Point(cx + dx * ratio, cy + dy * ratio)
                moved_deg    += remaining
                remaining     = 0

        moved_m = moved_deg * 111000
        if self.phase == "walk":
            self.cumul_walk_m  += moved_m
        else:
            self.cumul_truck_m += moved_m