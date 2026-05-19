"""
data_prep.py — 관악구 GeoJSON 전처리 스크립트 (1회 실행)

실행:
    python data_prep.py --input 관악구_smoothDEM.geojson --outdir data/graphs

결과:
    data/graphs/
    ├── index.json          ← 동 목록 + 중심좌표 + 파일경로
    ├── 난곡동.json
    ├── 신림동.json
    ├── 봉천동.json
    └── ...

각 동 파일 구조 (최소화):
{
  "dong": "난곡동",
  "center": [lat, lon],
  "bounds": [lat_min, lon_min, lat_max, lon_max],
  "nodes": [[lat, lon], ...],          ← 교차점 좌표
  "edges": [[na, nb, slope, width], ...]  ← 인접 리스트 (4가지만)
  "hard_nodes": [idx, ...]             ← 난배송 노드 (협로 or 급경사)
  "map_segs": [[slat,slon,elat,elon,slope,width], ...]  ← 지도 표시용 샘플
}
"""
import argparse
import json
import math
import os
import random
import sys
from collections import defaultdict

# ── 좌표 변환 (EPSG:5179 → WGS84) ───────────────────────────────
def epsg5179_to_wgs84(x: float, y: float):
    a  = 6378137.0; f = 1 / 298.257222101; k0 = 1.0
    lon0 = math.radians(127.5); lat0 = math.radians(38.0)
    FE = 1_000_000.0; FN = 2_000_000.0
    e2 = 2*f - f*f; ep2 = e2/(1-e2)
    e1 = (1 - math.sqrt(1-e2)) / (1 + math.sqrt(1-e2))

    def M(lat):
        return a * ((1 - e2/4 - 3*e2**2/64) * lat
                    - (3*e2/8 + 3*e2**2/32) * math.sin(2*lat)
                    + (15*e2**2/256) * math.sin(4*lat))

    X = x - FE; Y = y - FN
    M0 = M(lat0); Mm = M0 + Y / k0
    mu = Mm / (a * (1 - e2/4 - 3*e2**2/64))
    phi1 = (mu
            + (3*e1/2 - 27*e1**3/32) * math.sin(2*mu)
            + (21*e1**2/16 - 55*e1**4/32) * math.sin(4*mu)
            + (151*e1**3/96) * math.sin(6*mu))
    N1 = a / math.sqrt(1 - e2*math.sin(phi1)**2)
    R1 = a * (1-e2) / (1 - e2*math.sin(phi1)**2)**1.5
    T1 = math.tan(phi1)**2; C1 = ep2 * math.cos(phi1)**2
    D  = X / (N1 * k0)
    lat = phi1 - (N1*math.tan(phi1)/R1) * (
        D**2/2
        - (5 + 3*T1 + 10*C1 - 4*C1**2 - 9*ep2) * D**4/24
        + (61 + 90*T1 + 298*C1 + 45*T1**2 - 252*ep2 - 3*C1**2) * D**6/720
    )
    lon = lon0 + (
        D - (1 + 2*T1 + C1) * D**3/6
        + (5 - 2*C1 + 28*T1 - 3*C1**2 + 8*ep2 + 24*T1**2) * D**5/120
    ) / math.cos(phi1)
    return round(math.degrees(lat), 6), round(math.degrees(lon), 6)


# ── 관악구 행정동 경계 (WGS84 bounding box) ─────────────────────
# 실제 행정동 경계 대신 격자 분할 사용
# 관악구 전체: lat 37.44~37.51, lon 126.88~126.98
# 각 동을 0.01도(약 1km) 격자로 분할 후 주요 도로명으로 동 이름 할당
DONG_GRID = [
    # (name, lat_min, lat_max, lon_min, lon_max)
    ("난곡동",    37.463, 37.475, 126.920, 126.940),
    ("난향동",    37.463, 37.475, 126.940, 126.955),
    ("신림동",    37.470, 37.485, 126.910, 126.930),
    ("신사동",    37.470, 37.485, 126.930, 126.950),
    ("조원동",    37.455, 37.470, 126.910, 126.930),
    ("서원동",    37.455, 37.470, 126.930, 126.950),
    ("중앙동",    37.478, 37.492, 126.920, 126.940),
    ("청룡동",    37.478, 37.492, 126.940, 126.960),
    ("성현동",    37.478, 37.492, 126.960, 126.978),
    ("행운동",    37.462, 37.478, 126.950, 126.965),
    ("낙성대동",  37.462, 37.478, 126.965, 126.980),
    ("인헌동",    37.478, 37.492, 126.978, 126.992),
    ("남현동",    37.490, 37.505, 126.960, 126.982),
    ("봉천동",    37.490, 37.507, 126.935, 126.960),
    ("은천동",    37.490, 37.507, 126.910, 126.935),
    ("관악구 전체", 37.440, 37.515, 126.880, 126.998),  # 마지막: 전체
]


def find_dong(lat: float, lon: float) -> str:
    """좌표가 속하는 동 반환 (첫 번째 매칭, 전체 제외)"""
    for name, la_min, la_max, lo_min, lo_max in DONG_GRID[:-1]:
        if la_min <= lat <= la_max and lo_min <= lon <= lo_max:
            return name
    return "기타"


# ── 노드 그래프 구축 ─────────────────────────────────────────────
def build_graph(features: list, lat_min, lat_max, lon_min, lon_max):
    """
    주어진 bounding box 안의 feature들로 노드+엣지 그래프 구축
    반환: nodes, adj
      nodes: [(lat, lon), ...]
      adj:   {node_id: [(nb_id, slope, width, length), ...]}
    """
    node_map = {}
    nodes    = []
    adj      = defaultdict(list)

    def get_node(lat, lon, prec=4):
        key = (round(lat, prec), round(lon, prec))
        if key not in node_map:
            nid = len(nodes)
            node_map[key] = nid
            nodes.append((lat, lon))
        return node_map[key]

    for feat in features:
        p      = feat["properties"]
        coords = feat["geometry"]["coordinates"]
        slat, slon = epsg5179_to_wgs84(coords[0][0],  coords[0][1])
        elat, elon = epsg5179_to_wgs84(coords[-1][0], coords[-1][1])
        mlat = (slat + elat) / 2
        mlon = (slon + elon) / 2

        if not (lat_min <= mlat <= lat_max and lon_min <= mlon <= lon_max):
            continue

        na = get_node(slat, slon)
        nb = get_node(elat, elon)
        if na == nb:
            continue

        slope  = round(p.get("slope_deg", 0.0), 2)
        width  = p.get("min_width", 5.0)
        length = round(p.get("length_m", 5.0), 1)

        adj[na].append((nb,  slope,  width, length))
        adj[nb].append((na, -slope,  width, length))

    return nodes, dict(adj)


def build_dong_data(features, dong_name, lat_min, lat_max, lon_min, lon_max):
    nodes, adj = build_graph(features, lat_min, lat_max, lon_min, lon_max)
    if not nodes:
        return None

    # 중심 좌표
    lats = [n[0] for n in nodes]; lons = [n[1] for n in nodes]
    center = [round(sum(lats)/len(lats), 5), round(sum(lons)/len(lons), 5)]

    # 엣지 리스트 (4가지만: na, nb, slope, width)
    edges = []
    seen  = set()
    for na, nbrs in adj.items():
        for nb, slope, width, length in nbrs:
            key = (min(na, nb), max(na, nb))
            if key not in seen:
                seen.add(key)
                edges.append([na, nb, slope, width])

    # 난배송 노드 (협로 or 급경사)
    hard_nodes = sorted(set(
        na
        for na, nbrs in adj.items()
        for nb, slope, width, _ in nbrs
        if width <= 2.0 or abs(slope) >= 15
    ))

    # 지도 표시용 — 전체 엣지 (끊김 없이 전체 도로망 표시)
    map_segs = [
        [nodes[na][0], nodes[na][1], nodes[nb][0], nodes[nb][1], slope, width]
        for na, nb, slope, width in edges
    ]

    return {
        "dong":       dong_name,
        "center":     center,
        "bounds":     [round(lat_min,4), round(lon_min,4), round(lat_max,4), round(lon_max,4)],
        "nodes":      nodes,
        "edges":      edges,       # [na, nb, slope, width]
        "hard_nodes": hard_nodes,
        "map_segs":   map_segs,    # [slat, slon, elat, elon, slope, width]
        "stats": {
            "total_nodes":  len(nodes),
            "total_edges":  len(edges),
            "hard_nodes":   len(hard_nodes),
            "narrow_pct":   round(sum(1 for _,_,_,w in edges if w <= 2.0) / max(len(edges),1) * 100, 1),
            "steep_pct":    round(sum(1 for _,_,s,_ in edges if abs(s) >= 15) / max(len(edges),1) * 100, 1),
        }
    }


# ── 메인 ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="관악구 GeoJSON 전처리")
    parser.add_argument("--input",  default="data/관악구_smoothDEM.geojson", help="원본 GeoJSON 경로")
    parser.add_argument("--outdir", default="data/graphs",                   help="출력 폴더")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"[ERROR] 파일 없음: {args.input}")
        sys.exit(1)

    os.makedirs(args.outdir, exist_ok=True)

    print(f"[1/3] GeoJSON 로드 중: {args.input}")
    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)
    features = data["features"]
    print(f"      총 {len(features):,}개 feature")

    index = []
    print(f"[2/3] 동별 그래프 생성 중...")

    for dong_name, la_min, la_max, lo_min, lo_max in DONG_GRID:
        print(f"      → {dong_name} ...", end=" ", flush=True)
        result = build_dong_data(features, dong_name, la_min, la_max, lo_min, lo_max)
        if result is None or not result["nodes"]:
            print("노드 없음, 건너뜀")
            continue

        # 파일명 (한글 안전 처리)
        safe_name = dong_name.replace(" ", "_")
        filename  = f"{safe_name}.json"
        filepath  = os.path.join(args.outdir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, separators=(",", ":"))

        sz = os.path.getsize(filepath)
        print(f"{result['stats']['total_nodes']}노드 {result['stats']['total_edges']}엣지 "
              f"협로{result['stats']['narrow_pct']}% "
              f"→ {sz//1024}KB")

        index.append({
            "name":    dong_name,
            "file":    filename,
            "center":  result["center"],
            "bounds":  result["bounds"],
            "stats":   result["stats"],
        })

    # index.json 저장
    index_path = os.path.join(args.outdir, "index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"\n[3/3] 완료!")
    print(f"      동 수: {len(index)}개")
    print(f"      index.json: {index_path}")
    print(f"\n실행 방법:")
    print(f"      uvicorn main:app --reload")


if __name__ == "__main__":
    main()


# ── 직접 호출용 함수 (EnvironmentAgent에서 사용) ─────────────────────────────
def run_prep(input_path: str, outdir: str):
    """subprocess 없이 직접 호출하는 전처리 함수"""
    os.makedirs(outdir, exist_ok=True)
    print(f"[data_prep] 로드: {input_path}")
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)
    features = data["features"]
    print(f"[data_prep] {len(features):,}개 feature 처리 중...")

    index = []
    for dong_name, la_min, la_max, lo_min, lo_max in DONG_GRID:
        result = build_dong_data(features, dong_name, la_min, la_max, lo_min, lo_max)
        if not result or not result["nodes"]:
            continue
        safe_name = dong_name.replace(" ", "_")
        filepath  = os.path.join(outdir, f"{safe_name}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
        print(f"[data_prep] {dong_name}: {result['stats']['total_nodes']}노드")
        index.append({
            "name":   dong_name,
            "file":   f"{safe_name}.json",
            "center": result["center"],
            "bounds": result["bounds"],
            "stats":  result["stats"],
        })

    index_path = os.path.join(outdir, "index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"[data_prep] 완료: {len(index)}개 동")
    return index