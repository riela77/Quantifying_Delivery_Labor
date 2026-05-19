"""
EnvironmentAgent — 동별 도로 그래프 기반
- data/graphs/index.json 에서 동 목록 로드
- 구역 선택 시 해당 동 파일만 로드 (온디맨드)
- 에이전트 이동: 다익스트라 노드 경로 탐색
"""
from __future__ import annotations
import heapq, json, math, os, random
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class RoadSegment:
    slope_deg: float
    min_width: float

    @property
    def slope_abs(self): return abs(self.slope_deg)

    @property
    def is_narrow(self): return self.min_width <= 2.0


class RoadGraph:
    """노드+엣지 인접 리스트 그래프"""

    def __init__(self):
        self.nodes: List[Tuple[float, float]] = []
        self.adj:   Dict[int, List]           = defaultdict(list)

    def load(self, nodes: list, edges: list):
        """동 파일의 nodes/edges 직접 로드"""
        self.nodes = [tuple(n) for n in nodes]
        self.adj   = defaultdict(list)
        for na, nb, slope, width in edges:
            self.adj[na].append((nb,  slope,  width))
            self.adj[nb].append((na, -slope,  width))

    def nearest_node(self, lat: float, lon: float) -> int:
        if not self.nodes: return 0
        best, bd = 0, float("inf")
        for i, (la, lo) in enumerate(self.nodes):
            d = math.hypot(lat - la, lon - lo)
            if d < bd: bd = d; best = i
        return best

    def dijkstra(self, src: int, dst: int) -> List[int]:
        """실질 소요시간 기반 최단 경로"""
        dist = {src: 0.0}
        prev: Dict[int, Optional[int]] = {src: None}
        pq   = [(0.0, src)]
        vis  = set()
        while pq:
            d, u = heapq.heappop(pq)
            if u in vis: continue
            vis.add(u)
            if u == dst: break
            for v, slope, width in self.adj.get(u, []):
                if v in vis: continue
                walking = width <= 2.0
                speed   = 1.2 if walking else 3.5
                sf      = 3.0 if abs(slope) >= 25 else 2.0 if abs(slope) >= 15 else 1.0
                nd      = d + 5.0 / speed * sf   # 세그먼트 길이 약 5m
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd; prev[v] = u
                    heapq.heappush(pq, (nd, v))
        path, cur = [], dst
        while cur is not None:
            path.append(cur); cur = prev.get(cur)
        path.reverse()
        return path if path and path[0] == src else []

    def road_at(self, node_id: int) -> Optional[RoadSegment]:
        edges = self.adj.get(node_id, [])
        if not edges: return None
        worst = max(edges, key=lambda e: (e[2] <= 2.0, abs(e[1])))
        return RoadSegment(slope_deg=worst[1], min_width=worst[2])


class EnvironmentAgent:
    GRAPHS_DIR    = "data/graphs"
    INDEX_FILE    = "data/graphs/index.json"
    FALLBACK_FILE = "data/gwanak_graph.json"   # 구버전 호환

    def __init__(self):
        self.graph          = RoadGraph()
        self.delivery_stops: List[Tuple[float, float]] = []
        self.hard_nodes:     List[int]  = []
        self.map_segments:   List[dict] = []
        self.center:         Tuple[float, float] = (37.470, 126.932)
        self.region_name:    str  = "기본"
        self.loaded:         bool = False

        # 동 목록 (index.json에서)
        self.dong_list: List[dict] = []   # [{name, file, center, bounds, stats}, ...]
        self._load_index()

    # ── 인덱스 로드 ────────────────────────────────────────────
    def _load_index(self):
        if os.path.exists(self.INDEX_FILE):
            with open(self.INDEX_FILE, encoding="utf-8") as f:
                self.dong_list = json.load(f)
            print(f"[ENV] 동 목록 로드: {len(self.dong_list)}개")
            if self.dong_list:
                self._load_dong(0)
        elif os.path.exists(self.FALLBACK_FILE):
            self._load_fallback()
        else:
            # GeoJSON 있으면 자동 전처리 시도
            geojson_candidates = []
            for root, _, files in os.walk("data"):
                for f in files:
                    if f.endswith((".geojson", ".json")) and "graph" not in f and "index" not in f:
                        geojson_candidates.append(os.path.join(root, f))
            if geojson_candidates:
                gj_path = geojson_candidates[0]
                print(f"[ENV] GeoJSON 발견: {gj_path} — 자동 전처리 시작")
                self._auto_prep(gj_path)
            else:
                print("[ENV] 그래프 파일 없음 — 샘플 사용 (환경 탭에서 GeoJSON 업로드하세요)")
                self._load_sample()

    def _auto_prep(self, geojson_path: str):
        """GeoJSON 발견 시 data_prep 로직 직접 호출 (subprocess 없이)"""
        try:
            os.makedirs("data/graphs", exist_ok=True)
            # data_prep 모듈을 직접 임포트해서 실행
            import importlib.util, sys
            spec = importlib.util.spec_from_file_location("data_prep", "data_prep.py")
            dp   = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(dp)
            # 전처리 실행
            dp.run_prep(geojson_path, "data/graphs")
            if os.path.exists(self.INDEX_FILE):
                with open(self.INDEX_FILE, encoding="utf-8") as f:
                    self.dong_list = json.load(f)
                print(f"[ENV] 자동 전처리 완료: {len(self.dong_list)}개 동")
                if self.dong_list:
                    self._load_dong(0)
            else:
                print("[ENV] 전처리 후 index.json 없음 — 샘플 사용")
                self._load_sample()
        except Exception as e:
            print(f"[ENV] 자동 전처리 오류: {e}")
            self._load_sample()

    def _load_dong(self, idx: int):
        """인덱스 idx번째 동 파일 로드"""
        entry    = self.dong_list[idx]
        filepath = os.path.join(self.GRAPHS_DIR, entry["file"])
        if not os.path.exists(filepath):
            print(f"[ENV] 파일 없음: {filepath}")
            return
        with open(filepath, encoding="utf-8") as f:
            d = json.load(f)

        self.graph.load(d["nodes"], d["edges"])
        self.hard_nodes    = d.get("hard_nodes", [])
        self.map_segments  = [
            {"slat": s[0], "slon": s[1], "elat": s[2], "elon": s[3],
             "sl": s[4], "w": s[5]}
            for s in d.get("map_segs", [])
        ]
        self.center      = tuple(d["center"])
        self.region_name = d["dong"]
        self.loaded      = True

        # 배송지: 난배송 노드 중 랜덤 20개
        pool   = self.hard_nodes if len(self.hard_nodes) >= 10 else list(range(len(self.graph.nodes)))
        sample = random.sample(pool, min(20, len(pool)))
        self.delivery_stops = [self.graph.nodes[i] for i in sample]

        st = d.get("stats", {})
        print(f"[ENV] '{self.region_name}' 로드: "
              f"{st.get('total_nodes',0)}노드 "
              f"협로{st.get('narrow_pct',0)}% "
              f"난배송노드{len(self.hard_nodes)}개")

    # ── 구역 변경 (외부 호출) ──────────────────────────────────
    def set_zone(self, zone_idx: int):
        """환경 탭에서 동 선택 시 호출 — 해당 동 파일 온디맨드 로드"""
        if zone_idx < 0 or zone_idx >= len(self.dong_list):
            return
        self._load_dong(zone_idx)

    # ── 폴백 / 샘플 ───────────────────────────────────────────
    def _load_fallback(self):
        """구버전 gwanak_graph.json 호환"""
        with open(self.FALLBACK_FILE, encoding="utf-8") as f:
            d = json.load(f)
        nodes = [tuple(n) for n in d["nodes"]]
        adj_raw = d["adj"]
        edges = []
        seen  = set()
        for k, nbrs in adj_raw.items():
            na = int(k)
            for nb, slope, width, *_ in nbrs:
                key = (min(na, nb), max(na, nb))
                if key not in seen:
                    seen.add(key)
                    edges.append([na, nb, slope, width])
        self.graph.load(nodes, edges)
        self.hard_nodes   = d.get("hard_nodes", [])
        self.map_segments = [
            {"slat": s["slat"], "slon": s["slon"],
             "elat": s["elat"], "elon": s["elon"],
             "sl": s["sl"], "w": s["w"]}
            for s in d.get("map_segs", [])
        ]
        self.center      = tuple(d.get("center", [37.470, 126.932]))
        self.region_name = "관악구 (구버전)"
        self.loaded      = True
        pool   = self.hard_nodes if self.hard_nodes else list(range(len(nodes)))
        sample = random.sample(pool, min(20, len(pool)))
        self.delivery_stops = [self.graph.nodes[i] for i in sample]

    def _load_sample(self):
        cx, cy = 37.470, 126.932
        nodes, edges = [], []
        grid = {}
        for i in range(10):
            for j in range(10):
                nid = len(nodes)
                nodes.append((cx - 0.004 + i*0.001, cy - 0.004 + j*0.001))
                grid[(i, j)] = nid
        for i in range(10):
            for j in range(10):
                na = grid[(i, j)]
                for di, dj in [(0,1),(1,0)]:
                    ni, nj = i+di, j+dj
                    if (ni, nj) in grid:
                        nb    = grid[(ni, nj)]
                        w     = 1.5 if (i+j) % 3 == 0 else 4.0
                        s     = (i+j) * 1.5
                        edges.append([na, nb, s, w])
        self.graph.load(nodes, edges)
        self.hard_nodes     = list(range(len(nodes)))
        self.delivery_stops = random.sample(nodes, 10)
        self.center         = (cx, cy)
        # 샘플 map_segments 생성 (지도 표시용)
        self.map_segments = [
            {"slat": nodes[na][0], "slon": nodes[na][1],
             "elat": nodes[nb][0], "elon": nodes[nb][1],
             "sl": s, "w": w}
            for na, nb, s, w in edges
        ]
        self.dong_list = [{"name": "샘플(GeoJSON 없음)", "center": list(self.center), "file": "", "bounds": [], "stats": {}}]

    # ── 에이전트용 API ─────────────────────────────────────────
    def find_path(self, from_lat, from_lon, to_lat, to_lon) -> List[Tuple[float, float]]:
        src = self.graph.nearest_node(from_lat, from_lon)
        dst = self.graph.nearest_node(to_lat, to_lon)
        path = self.graph.dijkstra(src, dst)
        if not path: return [(to_lat, to_lon)]
        return [self.graph.nodes[n] for n in path]

    def nearest_road(self, lat, lon) -> Optional[RoadSegment]:
        nid = self.graph.nearest_node(lat, lon)
        return self.graph.road_at(nid)

    def stats(self) -> dict:
        if not self.graph.nodes: return {}
        total_e = sum(len(v) for v in self.graph.adj.values()) // 2
        narrow  = sum(1 for v in self.graph.adj.values() for _, s, w in v if w <= 2.0) // 2
        steep   = sum(1 for v in self.graph.adj.values() for _, s, w in v if abs(s) >= 15) // 2
        return {
            "total":        len(self.graph.nodes),
            "edges":        total_e,
            "hard_nodes":   len(self.hard_nodes),
            "narrow_count": narrow,
            "narrow_pct":   round(narrow / total_e * 100, 1) if total_e else 0,
            "steep_count":  steep,
            "steep_pct":    round(steep  / total_e * 100, 1) if total_e else 0,
        }

    @property
    def ZONE_PRESETS(self):
        """main.py 호환용 — dong_list를 ZONE_PRESETS처럼 사용"""
        return [{"name": d["name"], "center": d["center"],
                 "radius": 0.02} for d in self.dong_list]