"""
rider_api.py — 라이더 앱 전용 FastAPI 엔드포인트

마운트 방법 (main.py에 추가):
    from rider_api import rider_router
    app.include_router(rider_router, prefix="/rider")
"""
from __future__ import annotations
import json
import math
import os
import random
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

rider_router = APIRouter()

# ── TMap API 설정 ──────────────────────────────────────────────
TMAP_API_KEY = os.environ.get("TMAP_API_KEY", "YOUR_TMAP_API_KEY")
TMAP_BASE    = "https://apis.openapi.sk.com/tmap"

# ── 안전 배달료 계산 상수 ──────────────────────────────────────
MIN_WAGE_PER_MIN = 167          # 최저임금 분당 (원)
BASE_WALK_ALLOWANCE = 10        # 기본 허용 도보 시간 (분)

def calc_base_fare(distance_km: float) -> int:
    """기본 운행 운임 계산"""
    m = distance_km * 1000
    if m < 675:     return 3000
    if m < 1900:    return 3500
    return 3500 + int((m - 1900) / 100) * 80

def calc_walk_surcharge(walk_minutes: float) -> int:
    """험지 초과 도보 할증 (10분 초과분부터)"""
    over = max(0, walk_minutes - BASE_WALK_ALLOWANCE)
    return int(over * MIN_WAGE_PER_MIN)

def calc_safe_fare(distance_km: float, walk_minutes: float) -> dict:
    base      = calc_base_fare(distance_km)
    surcharge = calc_walk_surcharge(walk_minutes)
    return {
        "base_fare":   base,
        "surcharge":   surcharge,
        "total":       base + surcharge,
        "walk_over":   max(0, walk_minutes - BASE_WALK_ALLOWANCE),
    }

# ── 지형 분석 (GeoJSON 그래프 활용) ──────────────────────────
def analyze_terrain(
    from_lat: float, from_lon: float,
    to_lat:   float, to_lon:   float,
    graph_dir: str = "data/graphs"
) -> dict:
    """
    출발~도착 사이 도로 세그먼트 분석
    → 협로 구간 거리, 예측 도보 시간 반환
    """
    # 가장 가까운 동 그래프 로드
    index_path = os.path.join(graph_dir, "index.json")
    if not os.path.exists(index_path):
        return {"walk_km": 0.0, "walk_minutes": 0.0, "narrow_ratio": 0.0, "max_slope": 0.0, "warnings": []}

    with open(index_path, encoding="utf-8") as f:
        index = json.load(f)

    # 도착지에 가장 가까운 동 선택
    center_lat = (from_lat + to_lat) / 2
    center_lon = (from_lon + to_lon) / 2
    best = min(index, key=lambda d: math.hypot(
        d["center"][0] - center_lat, d["center"][1] - center_lon
    ))

    dong_path = os.path.join(graph_dir, best["file"])
    if not os.path.exists(dong_path):
        return {"walk_km": 0.0, "walk_minutes": 0.0, "narrow_ratio": 0.0, "max_slope": 0.0, "warnings": []}

    with open(dong_path, encoding="utf-8") as f:
        dong = json.load(f)

    # 경로 박스 내 세그먼트 분석
    lat_min = min(from_lat, to_lat) - 0.003
    lat_max = max(from_lat, to_lat) + 0.003
    lon_min = min(from_lon, to_lon) - 0.003
    lon_max = max(from_lon, to_lon) + 0.003

    segs_in_box = [
        s for s in dong.get("map_segs", [])
        if lat_min <= s[0] <= lat_max and lon_min <= s[1] <= lon_max
    ]

    if not segs_in_box:
        return {"walk_km": 0.0, "walk_minutes": 0.0, "narrow_ratio": 0.0, "max_slope": 0.0, "warnings": []}

    # 협로·경사 분석
    total = len(segs_in_box)
    narrow = [s for s in segs_in_box if s[5] <= 2.0]           # min_width ≤ 2m
    steep  = [s for s in segs_in_box if abs(s[4]) >= 15]        # slope ≥ 15°
    max_slope = max((abs(s[4]) for s in segs_in_box), default=0)

    narrow_ratio = len(narrow) / total if total else 0

    # 실제 직선거리 기반 도보 구간 추정
    straight_km = math.hypot(to_lat - from_lat, to_lon - from_lon) * 111
    walk_km     = straight_km * narrow_ratio * 1.4  # 협로 비율 × 우회계수

    # 도보 소요시간: 협로 평지 5km/h, 급경사 3km/h
    steep_ratio = len(steep) / len(narrow) if narrow else 0
    walk_speed  = 3.5 + (1 - steep_ratio) * 1.5   # 3.5 ~ 5 km/h
    walk_minutes = (walk_km / walk_speed) * 60 if walk_km > 0 else 0

    warnings = []
    if narrow_ratio > 0.3:
        warnings.append(f"이륜차 진입 불가 협로 {narrow_ratio*100:.0f}% 포함")
    if max_slope >= 15:
        warnings.append(f"경사도 {max_slope:.0f}° 급경사 구간 포함")
    if len(steep) > 0:
        warnings.append("도보 시 소요시간 대폭 증가 예상")

    return {
        "walk_km":      round(walk_km, 2),
        "walk_minutes": round(walk_minutes, 1),
        "narrow_ratio": round(narrow_ratio, 2),
        "max_slope":    round(max_slope, 1),
        "warnings":     warnings,
    }


# ── TMap 경로 조회 ─────────────────────────────────────────────
async def get_tmap_route(
    from_lat: float, from_lon: float,
    to_lat:   float, to_lon:   float,
    mode: str = "motorcycle",  # motorcycle | pedestrian | car
) -> dict:
    """TMap Directions API 호출"""
    if TMAP_API_KEY == "YOUR_TMAP_API_KEY":
        # API 키 없을 때 Mock 데이터
        dist_km = math.hypot(to_lat - from_lat, to_lon - from_lon) * 111
        return {
            "distance_m":  int(dist_km * 1000),
            "duration_s":  int(dist_km / 25 * 3600),  # 25km/h 기준
            "polyline":    [[from_lon, from_lat], [to_lon, to_lat]],
            "is_mock":     True,
        }

    endpoint = {
        "motorcycle":  f"{TMAP_BASE}/routes/motorcycle",
        "pedestrian":  f"{TMAP_BASE}/routes/pedestrian",
        "car":         f"{TMAP_BASE}/routes",
    }.get(mode, f"{TMAP_BASE}/routes")

    payload = {
        "startX":       str(from_lon),
        "startY":       str(from_lat),
        "endX":         str(to_lon),
        "endY":         str(to_lat),
        "reqCoordType": "WGS84GEO",
        "resCoordType": "WGS84GEO",
        "searchOption": "0",
    }

    async with httpx.AsyncClient(timeout=5.0) as client:
        res = await client.post(
            endpoint,
            headers={"appKey": "3zo6yeSBU73BF5kAoTvaJ5UtFw4S6jBI7Nk6TVex", "Content-Type": "application/json"},
            json=payload,
        )
    data = res.json()

    props    = data["features"][0]["properties"]
    polyline = [
        f["geometry"]["coordinates"]
        for f in data["features"]
        if f["geometry"]["type"] == "LineString"
    ]
    coords = []
    for seg in polyline:
        coords.extend(seg)

    return {
        "distance_m": props.get("totalDistance", 0),
        "duration_s": props.get("totalTime", 0),
        "polyline":   coords,
        "is_mock":    False,
    }


# ── API 모델 ───────────────────────────────────────────────────
class RouteRequest(BaseModel):
    rider_lat:  float
    rider_lon:  float
    store_lat:  float
    store_lon:  float
    dest_lat:   float
    dest_lon:   float
    store_name: str = "픽업 매장"
    dest_name:  str = "배달지"


class CallSimRequest(BaseModel):
    rider_lat: float
    rider_lon: float
    dong_name: str = "난곡동"   # 시뮬레이션용 동 선택


# ── 엔드포인트 ─────────────────────────────────────────────────

@rider_router.post("/analyze-call")
async def analyze_call(req: RouteRequest):
    """
    콜 수락 전 분석:
    1. TMap 예측 (오토바이 기준)
    2. LastMile 실제 예측 (지형 반영)
    3. 안전 배달료 산정
    """
    # 1. TMap 경로 (라이더→매장, 매장→배달지)
    to_store   = await get_tmap_route(req.rider_lat, req.rider_lon, req.store_lat, req.store_lon, "motorcycle")
    to_dest    = await get_tmap_route(req.store_lat, req.store_lon, req.dest_lat,  req.dest_lon,  "motorcycle")

    tmap_dist_km   = (to_store["distance_m"] + to_dest["distance_m"]) / 1000
    tmap_minutes   = (to_store["duration_s"] + to_dest["duration_s"]) / 60

    # 2. 지형 분석 (매장→배달지 구간)
    terrain = analyze_terrain(req.store_lat, req.store_lon, req.dest_lat, req.dest_lon)

    # 3. 실제 예상 시간 = TMap + 도보 할증
    actual_minutes = tmap_minutes + terrain["walk_minutes"]
    actual_dist_km = tmap_dist_km + terrain["walk_km"]

    # 4. 안전 배달료
    platform_fare = calc_base_fare(tmap_dist_km)    # 플랫폼이 제시하는 금액
    safe_fare     = calc_safe_fare(actual_dist_km, terrain["walk_minutes"])

    return {
        "store_name":    req.store_name,
        "dest_name":     req.dest_name,
        "tmap": {
            "distance_km":  round(tmap_dist_km, 2),
            "minutes":      round(tmap_minutes, 1),
            "fare":         platform_fare,
        },
        "actual": {
            "distance_km":  round(actual_dist_km, 2),
            "minutes":      round(actual_minutes, 1),
            "walk_km":      terrain["walk_km"],
            "walk_minutes": terrain["walk_minutes"],
        },
        "safe_fare":     safe_fare,
        "terrain":       terrain,
        "gap": {
            "minutes": round(actual_minutes - tmap_minutes, 1),
            "fare":    safe_fare["total"] - platform_fare,
        },
        "polyline_to_store": to_store["polyline"],
        "polyline_to_dest":  to_dest["polyline"],
        "is_mock": to_store.get("is_mock", False),
    }


@rider_router.post("/sim-call")
async def sim_call(req: CallSimRequest):
    """
    시뮬레이션용 콜 생성
    (실제 TMap API 없이도 데모 가능)
    """
    # 동별 대표 매장/배달지 좌표 (난곡동 기준)
    DEMO_LOCATIONS = {
        "난곡동": {
            "stores": [(37.4698, 126.9312, "○○치킨 난곡점"),
                       (37.4712, 126.9285, "▲▲편의점")],
            "dests":  [(37.4671, 126.9298, "난곡동 123-4"),
                       (37.4683, 126.9275, "난곡동 언덕마을 302호")],
        },
        "신림동": {
            "stores": [(37.4812, 126.9224, "신림 분식"),
                       (37.4798, 126.9241, "신림 카페")],
            "dests":  [(37.4756, 126.9187, "신림동 산101"),
                       (37.4771, 126.9203, "신림동 가파른길 5")],
        },
    }
    loc = DEMO_LOCATIONS.get(req.dong_name, DEMO_LOCATIONS["난곡동"])
    store_info = random.choice(loc["stores"])
    dest_info  = random.choice(loc["dests"])

    route_req = RouteRequest(
        rider_lat=req.rider_lat, rider_lon=req.rider_lon,
        store_lat=store_info[0], store_lon=store_info[1],
        dest_lat=dest_info[0],   dest_lon=dest_info[1],
        store_name=store_info[2], dest_name=dest_info[2],
    )
    result = await analyze_call(route_req)
    result["call_id"] = f"CALL-{random.randint(1000,9999)}"
    result["expires_in"] = 30   # 30초 카운트다운
    return result


@rider_router.get("/monthly-summary")
async def monthly_summary():
    """이달 누적 배달 요약 (로컬스토리지 기반 — 실제 DB 없이 데모)"""
    return {
        "total_calls":        47,
        "total_km":           183.4,
        "total_walk_km":      41.2,
        "total_walk_minutes": 494,
        "platform_total":     188_000,
        "safe_total":         262_800,
        "gap_total":           74_800,
        "message":            "이달 74,800원이 미반영된 노동입니다",
    }