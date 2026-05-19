from __future__ import annotations
import asyncio, json, os, tempfile
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from agents.environment import EnvironmentAgent
from agents.simulation import DeliveryModel

app = FastAPI()

env     = EnvironmentAgent()
model:  Optional[DeliveryModel] = None
running = False
params  = {"max_legal_hours": 8, "n_drivers": 8, "daily_volume": 120, "zone": 0}
prep_status = {"state": "idle", "message": "", "progress": 0}  # 전처리 진행 상태

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def index():
    return FileResponse("static/index.html")


# ── GeoJSON 업로드 + 자동 전처리 ──────────────────────────────
@app.post("/upload-geojson")
async def upload_geojson(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """GeoJSON 업로드 → 백그라운드에서 전처리 자동 실행"""
    global prep_status

    if not file.filename.endswith((".geojson", ".json")):
        return JSONResponse({"error": "GeoJSON 파일만 업로드 가능합니다"}, status_code=400)

    # 임시 파일로 저장
    os.makedirs("data", exist_ok=True)
    tmp_path = f"data/_uploaded_{file.filename}"
    content  = await file.read()
    with open(tmp_path, "wb") as f_out:
        f_out.write(content)

    prep_status = {"state": "running", "message": "전처리 시작 중...", "progress": 0}
    background_tasks.add_task(_run_prep, tmp_path)
    return JSONResponse({"message": "전처리 시작됨", "filename": file.filename})


@app.get("/prep-status")
async def get_prep_status():
    """전처리 진행 상태 폴링용"""
    return JSONResponse(prep_status)


async def _run_prep(geojson_path: str):
    """백그라운드 전처리 태스크"""
    global prep_status, env
    import subprocess, sys

    try:
        prep_status = {"state": "running", "message": "GeoJSON 파싱 중...", "progress": 10}
        os.makedirs("data/graphs", exist_ok=True)

        # data_prep.py를 subprocess로 실행
        result = await asyncio.create_subprocess_exec(
            sys.executable, "data_prep.py",
            "--input",  geojson_path,
            "--outdir", "data/graphs",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # 진행 상황 파싱 (stdout 실시간 읽기)
        dong_count = 0
        async for line in result.stdout:
            line_str = line.decode("utf-8", errors="replace").strip()
            if "→" in line_str:
                dong_count += 1
                prep_status = {
                    "state":    "running",
                    "message":  line_str,
                    "progress": min(90, 10 + dong_count * 5),
                }

        await result.wait()

        if result.returncode != 0:
            err = (await result.stderr.read()).decode()
            prep_status = {"state": "error", "message": f"전처리 오류: {err[:200]}", "progress": 0}
            return

        # 전처리 완료 → EnvironmentAgent 재로드
        prep_status = {"state": "running", "message": "도로 그래프 로드 중...", "progress": 95}
        env = EnvironmentAgent()   # index.json 다시 읽음

        prep_status = {
            "state":    "done",
            "message":  f"{len(env.dong_list)}개 동 전처리 완료",
            "progress": 100,
            "zones":    [d["name"] for d in env.dong_list],
            "center":   list(env.center),
            "map_segs": env.map_segments,
            "stops":    [list(p) for p in env.delivery_stops],
            "env_stats": env.stats(),
            "region":   env.region_name,
        }

        # 임시 파일 삭제
        try: os.remove(geojson_path)
        except: pass

    except Exception as e:
        prep_status = {"state": "error", "message": str(e), "progress": 0}


# ── 공통 헬퍼 ──────────────────────────────────────────────────
def _road_str(d) -> str:
    if not d.current_road: return ""
    r = d.current_road
    return f"경사 {r.slope_abs:.0f}° · 폭 {r.min_width}m{'  협로' if r.is_narrow else ''}"


def _driver_data():
    if not model: return []
    result = []
    for d in model.drivers:
        next_lat = d.lat; next_lon = d.lon
        if d.route and d.route_idx < len(d.route):
            next_lat, next_lon = d.route[d.route_idx]
        result.append({
            "id":       d.agent_id,
            "lat":      round(d.lat, 6),
            "lon":      round(d.lon, 6),
            "hours":    round(d.current_working_hours, 2),
            "max_h":    d.max_legal_hours,
            "delivered": d.delivered,
            "assigned":  d.assigned_deliveries,
            "over":     d.over_limit,
            "walking":  d.walking,
            "eff_mins": round(d.effective_mins, 1),
            "road":     _road_str(d),
            "next_lat": round(next_lat, 6),
            "next_lon": round(next_lon, 6),
        })
    return result


def make_snapshot(include_map=False) -> dict:
    s = (model.summary() if model
         else {"active":0,"over":0,"walking":0,"done":0,"total":0,"remain":0,"tick":0})
    snap = {
        "type":      "snapshot",
        "running":   running,
        "summary":   s,
        "drivers":   _driver_data(),
        "params":    params,
        "stops":     [list(p) for p in env.delivery_stops],
        "center":    list(env.center),
        "region":    env.region_name,
        "zones":     [d["name"] for d in env.dong_list],
        "env_stats": env.stats(),
        "has_data":  env.loaded,
    }
    if include_map:
        snap["map_segs"] = env.map_segments
    return snap


# ── WebSocket ───────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    global model, running, params, env
    await ws.accept()
    await ws.send_text(json.dumps(make_snapshot(include_map=True)))

    try:
        while True:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=0.05)
                await _handle(json.loads(raw), ws)
            except asyncio.TimeoutError:
                pass

            if running and model and not model.is_done:
                model.step(n_ticks=3)
                await ws.send_text(json.dumps({
                    "type":    "tick",
                    "summary": model.summary(),
                    "drivers": _driver_data(),
                }))
                await asyncio.sleep(0.12)
            elif running and model and model.is_done:
                running = False
                await ws.send_text(json.dumps({"type": "done", "summary": model.summary()}))
            else:
                await asyncio.sleep(0.05)

    except WebSocketDisconnect:
        running = False


async def _handle(msg: dict, ws: WebSocket):
    global model, running, params, env

    action = msg.get("action")

    if action == "start":
        params.update({
            "max_legal_hours": int(msg.get("max_legal_hours", 8)),
            "n_drivers":       int(msg.get("n_drivers", 8)),
            "daily_volume":    int(msg.get("daily_volume", 120)),
        })
        model   = DeliveryModel(
            daily_volume=params["daily_volume"],
            n_drivers=params["n_drivers"],
            max_legal_hours=params["max_legal_hours"],
            env=env,
        )
        running = True
        await ws.send_text(json.dumps({
            "type":    "started",
            "params":  params,
            "stops":   [list(p) for p in env.delivery_stops],
            "drivers": _driver_data(),
        }))

    elif action == "pause":
        running = not running
        await ws.send_text(json.dumps({"type": "paused", "running": running}))

    elif action == "reset":
        running = False; model = None
        await ws.send_text(json.dumps(make_snapshot()))

    elif action == "set_zone":
        zone_idx = int(msg.get("zone", 0))
        params["zone"] = zone_idx
        env.set_zone(zone_idx)
        running = False; model = None
        snap = make_snapshot(include_map=True)
        snap["type"] = "zone_changed"
        await ws.send_text(json.dumps(snap))

    elif action == "update_params":
        for k in ["max_legal_hours", "n_drivers", "daily_volume"]:
            if k in msg: params[k] = int(msg[k])
        if model and "max_legal_hours" in msg:
            for d in model.drivers:
                d.max_legal_hours = params["max_legal_hours"]
        await ws.send_text(json.dumps({"type": "params_updated", "params": params}))