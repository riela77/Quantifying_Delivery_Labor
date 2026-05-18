"""
LastMile Labor — FastAPI + WebSocket 서버
- /ws  : 시뮬레이션 실시간 스트림
- /    : 프론트엔드 HTML 서빙
"""
from __future__ import annotations
import asyncio
import json
import random
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from agents.environment import EnvironmentAgent
from agents.simulation import DeliveryModel

app = FastAPI()

# ── 전역 상태 ──────────────────────────────────────────────────────────────
env: EnvironmentAgent = EnvironmentAgent()
model: Optional[DeliveryModel] = None
running: bool = False
params: dict = {
    "max_legal_hours": 8,
    "n_drivers": 8,
    "daily_volume": 120,
}

# ── Static 파일 서빙 ───────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def index():
    return FileResponse("static/index.html")


# ── 상태 스냅샷 생성 ───────────────────────────────────────────────────────
def make_snapshot() -> dict:
    global model
    drivers_data = []
    if model:
        for d in model.drivers:
            drivers_data.append({
                "id":       d.agent_id,
                "lat":      round(d.lat, 6),
                "lon":      round(d.lon, 6),
                "hours":    round(d.current_working_hours, 2),
                "max_hours":d.max_legal_hours,
                "delivered":d.delivered,
                "assigned": d.assigned_deliveries,
                "over":     d.over_limit,
                "walking":  d.walking,
                "fatigue":  d.fatigue_penalty,
                "slope_mult": d.slope_multiplier,
                "effective_mins": round(d.effective_mins, 1),
                "road_info": _road_info(d),
            })
        s = model.summary()
    else:
        s = {"active":0,"over":0,"walking":0,"done":0,"total":0,"remain":0,"tick":0}

    return {
        "type":    "snapshot",
        "running": running,
        "summary": s,
        "drivers": drivers_data,
        "params":  params,
        "map_segments": env.map_segments if not model else [],  # 최초 1회만
        "stops":   env.delivery_stops,
        "center":  list(env.center),
    }


def _road_info(d) -> str:
    if not d.current_road:
        return ""
    r = d.current_road
    return f"경사 {r.slope_abs:.0f}° · 폭 {r.min_width}m{'  🚫협로' if r.is_narrow else ''}"


# ── WebSocket 핸들러 ───────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    global model, running, params, env

    await ws.accept()

    # 접속 시 초기 스냅샷 (지도 세그먼트 포함)
    snap = make_snapshot()
    snap["map_segments"] = env.map_segments   # 항상 포함
    await ws.send_text(json.dumps(snap))

    try:
        while True:
            # 클라이언트 메시지 처리 (논블로킹)
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=0.05)
                msg = json.loads(raw)
                await _handle_message(msg, ws)
            except asyncio.TimeoutError:
                pass

            # 시뮬레이션 진행
            if running and model and not model.is_done:
                model.step(n_ticks=3)
                await ws.send_text(json.dumps({
                    "type":    "tick",
                    "summary": model.summary(),
                    "drivers": [
                        {
                            "id":      d.agent_id,
                            "lat":     round(d.lat, 6),
                            "lon":     round(d.lon, 6),
                            "hours":   round(d.current_working_hours, 2),
                            "delivered": d.delivered,
                            "assigned":  d.assigned_deliveries,
                            "over":    d.over_limit,
                            "walking": d.walking,
                            "effective_mins": round(d.effective_mins, 1),
                            "road_info": _road_info(d),
                        }
                        for d in model.drivers
                    ],
                }))
                await asyncio.sleep(0.12)

            elif running and model and model.is_done:
                running = False
                await ws.send_text(json.dumps({"type": "done", "summary": model.summary()}))

            else:
                await asyncio.sleep(0.05)

    except WebSocketDisconnect:
        running = False


async def _handle_message(msg: dict, ws: WebSocket):
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
        await ws.send_text(json.dumps({"type": "started", "params": params}))

    elif action == "pause":
        running = not running
        await ws.send_text(json.dumps({"type": "paused", "running": running}))

    elif action == "reset":
        running = False
        model   = None
        await ws.send_text(json.dumps(make_snapshot()))

    elif action == "update_params":
        # 실행 중 파라미터 실시간 반영
        if "max_legal_hours" in msg:
            params["max_legal_hours"] = int(msg["max_legal_hours"])
            if model:
                for d in model.drivers:
                    d.max_legal_hours = params["max_legal_hours"]
        if "n_drivers" in msg:
            params["n_drivers"] = int(msg["n_drivers"])
        if "daily_volume" in msg:
            params["daily_volume"] = int(msg["daily_volume"])
        await ws.send_text(json.dumps({"type": "params_updated", "params": params}))
