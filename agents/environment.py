from __future__ import annotations
import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class RoadSegment:
    seg_id: int
    slope_deg: float
    min_width: float
    mid_lat: float
    mid_lon: float
    length_m: float = 5.0
    road_name: str = ""

    @property
    def slope_abs(self) -> float:
        return abs(self.slope_deg)

    @property
    def is_narrow(self) -> bool:
        return self.min_width <= 2.0

    @property
    def road_color(self) -> str:
        if self.slope_abs >= 25: return "#f85149"
        if self.slope_abs >= 15: return "#d29922"
        return "#238636"

    @property
    def road_weight(self) -> int:
        return 2 if self.is_narrow else 4

    @property
    def difficulty_label(self) -> str:
        if self.is_narrow and self.slope_abs >= 25: return "최난배송"
        if self.is_narrow or  self.slope_abs >= 25: return "난배송"
        if self.slope_abs >= 15: return "주의"
        return "일반"


class EnvironmentAgent:
    """
    지형 및 도로 에이전트
    - GeoJSON 전체를 메모리에 올리지 않음
    - 좌표+속성 배열만 numpy로 보관 → 에이전트 위치 반경 쿼리
    """

    DEFAULT_CENTER = (37.4840, 126.9430)
    DEFAULT_STOPS = [
        (37.4820, 126.9391), (37.4835, 126.9408), (37.4812, 126.9422),
        (37.4798, 126.9435), (37.4847, 126.9418), (37.4860, 126.9402),
        (37.4875, 126.9388), (37.4855, 126.9445), (37.4830, 126.9455),
        (37.4810, 126.9468), (37.4790, 126.9478), (37.4870, 126.9460),
        (37.4885, 126.9472), (37.4800, 126.9412), (37.4815, 126.9448),
        (37.4840, 126.9430), (37.4865, 126.9435), (37.4878, 126.9450),
        (37.4820, 126.9462), (37.4808, 126.9395),
    ]
    AUTO_LOAD_PATHS = [
        "data/관악구_smoothDEM.geojson",
        "data/gwanak_smoothDEM.geojson",
        "data/roads.geojson",
    ]

    def __init__(self):
        # numpy 배열로만 보관 (RoadSegment 객체 생성 안 함)
        # _lats, _lons : 세그먼트 중간점 좌표 (n,)
        # _props       : [(seg_id, slope_deg, min_width, length_m), ...] (n,4)
        self._lats  = []
        self._lons  = []
        self._props = []   # (seg_id, slope_deg, min_width, length_m)

        self.delivery_stops: List[tuple] = list(self.DEFAULT_STOPS)
        self.geojson_loaded: bool = False
        self.region_name: str = "관악구 난곡동 (기본)"
        self.center: tuple = self.DEFAULT_CENTER
        self._transformer = None
        self._cached_stats: dict = {}

        # 지도 표시용 polyline 샘플 (전체 아님 — 최대 3000개)
        self.map_segments: List[dict] = []

        self._try_auto_load()

    # ── 좌표 변환 ──────────────────────────────────────────────
    def _get_transformer(self):
        if self._transformer is None:
            import pyproj
            self._transformer = pyproj.Transformer.from_crs(
                "EPSG:5181", "EPSG:4326", always_xy=True
            )
        return self._transformer

    def _tm_to_wgs84(self, x, y):
        tf = self._get_transformer()
        lon, lat = tf.transform(x, y)
        return lat, lon

    # ── GeoJSON 로드 (파싱만, 객체화 안 함) ────────────────────
    def load_geojson(self, geojson_data: dict, region_name: str = "") -> int:
        import json

        features = geojson_data.get("features", [])
        lats, lons, props = [], [], []
        all_lats, all_lons = [], []

        for feat in features:
            p = feat.get("properties", {})
            try:
                sx, sy = p["start_x"], p["start_y"]
                ex, ey = p["end_x"],   p["end_y"]
                s_lat, s_lon = self._tm_to_wgs84(sx, sy)
                e_lat, e_lon = self._tm_to_wgs84(ex, ey)
                mid_lat = (s_lat + e_lat) / 2
                mid_lon = (s_lon + e_lon) / 2
                lats.append(mid_lat)
                lons.append(mid_lon)
                props.append((
                    p.get("seg_id", 0),
                    p.get("slope_deg", 0.0),
                    p.get("min_width", 5.0),
                    p.get("length_m", 5.0),
                    s_lat, s_lon, e_lat, e_lon,   # 지도 표시용
                    p.get("ENG_RN", ""),
                ))
                all_lats += [s_lat, e_lat]
                all_lons += [s_lon, e_lon]
            except Exception:
                continue

        if not lats:
            return 0

        self._lats  = lats
        self._lons  = lons
        self._props = props
        self.geojson_loaded = True
        self.region_name = region_name or "업로드 지역"
        self.center = (sum(all_lats)/len(all_lats), sum(all_lons)/len(all_lons))

        # 배송지: 난배송 지점 우선 샘플 20개
        hard_idx = [i for i, p in enumerate(props) if p[2] <= 2.0 or abs(p[1]) >= 15]
        pool_idx = hard_idx if len(hard_idx) >= 10 else list(range(len(lats)))
        sampled  = random.sample(pool_idx, min(20, len(pool_idx)))
        self.delivery_stops = [(lats[i], lons[i]) for i in sampled]

        # 지도 표시용 폴리라인 샘플 (최대 3000개 — 전체 아님)
        sample_idx = random.sample(range(len(props)), min(3000, len(props)))
        self.map_segments = [
            {
                "slope_deg": props[i][1],
                "min_width": props[i][2],
                "s_lat": props[i][4], "s_lon": props[i][5],
                "e_lat": props[i][6], "e_lon": props[i][7],
            }
            for i in sample_idx
        ]

        # 통계 미리 계산
        slopes = [abs(p[1]) for p in props]
        widths = [p[2] for p in props]
        narrow = sum(1 for w in widths if w <= 2.0)
        steep  = sum(1 for s in slopes if s >= 25)
        n = len(props)
        self._cached_stats = {
            "total": n,
            "max_slope": round(max(slopes), 2),
            "min_width": round(min(widths), 2),
            "narrow_count": narrow,
            "narrow_pct":   round(narrow / n * 100, 1),
            "steep_count":  steep,
            "steep_pct":    round(steep  / n * 100, 1),
        }

        return n

    # ── 에이전트 위치 근처 도로 쿼리 (반경 ~50m) ───────────────
    def nearest_road(self, lat: float, lon: float) -> Optional[RoadSegment]:
        if not self._lats:
            return None
        # 위도 0.0005 ≈ 55m, 경도 0.0006 ≈ 55m — 이 범위만 선형 탐색
        R_LAT = 0.0008
        R_LON = 0.001
        best_d, best_i = float("inf"), -1
        for i, (la, lo) in enumerate(zip(self._lats, self._lons)):
            if abs(la - lat) > R_LAT or abs(lo - lon) > R_LON:
                continue
            d = math.hypot(la - lat, lo - lon)
            if d < best_d:
                best_d = d
                best_i = i
        if best_i == -1:
            # 반경 내 없으면 전체에서 가장 가까운 것 (fallback)
            best_i = min(range(len(self._lats)),
                         key=lambda i: math.hypot(self._lats[i]-lat, self._lons[i]-lon))
        p = self._props[best_i]
        return RoadSegment(
            seg_id=p[0], slope_deg=p[1], min_width=p[2], length_m=p[3],
            mid_lat=self._lats[best_i], mid_lon=self._lons[best_i],
            road_name=p[8],
        )

    def stats(self) -> dict:
        return self._cached_stats

    # ── 자동 로드 ───────────────────────────────────────────────
    def _try_auto_load(self) -> None:
        import os, json
        for path in self.AUTO_LOAD_PATHS:
            if os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        data = json.load(f)
                    n = self.load_geojson(data, os.path.basename(path).replace(".geojson", ""))
                    if n > 0:
                        print(f"[EnvironmentAgent] 로드 완료: {n}개 세그먼트 (지도 표시: {len(self.map_segments)}개 샘플)")
                        return
                except Exception as e:
                    print(f"[EnvironmentAgent] 로드 실패: {e}")
