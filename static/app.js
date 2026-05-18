// ── WebSocket 연결 ────────────────────────────────────────────────────────
let ws = null;
let mapReady = false;
let leafletMap = null;
let roadLayer = null;
let stopLayer = null;
let driverLayers = {};   // agent_id → Leaflet marker
let isRunning = false;

// SVG 아이콘
function truckIcon(color) {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"
        fill="none" stroke="${color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M1 3h15v13H1z"/>
        <path d="M16 8h4l3 5v4h-7V8z"/>
        <circle cx="5.5" cy="18.5" r="2.5" fill="${color}" stroke="none"/>
        <circle cx="18.5" cy="18.5" r="2.5" fill="${color}" stroke="none"/>
    </svg>`;
    return L.divIcon({ html: `<div style="margin:-14px 0 0 -14px">${svg}</div>`, iconSize: [28,28], className: '' });
}

function walkIcon(color) {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" viewBox="0 0 24 24"
        fill="none" stroke="${color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="4" r="2" fill="${color}" stroke="none"/>
        <path d="M9 22l1-7-2-3 3-4 2 3h3"/><path d="M15 22l-1-7"/>
        <path d="M7 13l-2 2"/><path d="M17 9l2 2"/>
    </svg>`;
    return L.divIcon({ html: `<div style="margin:-13px 0 0 -13px">${svg}</div>`, iconSize: [26,26], className: '' });
}

function doneIcon() {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24"
        fill="none" stroke="#8957e5" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
        <polyline points="9 22 9 12 15 12 15 22"/>
    </svg>`;
    return L.divIcon({ html: `<div style="margin:-11px 0 0 -11px">${svg}</div>`, iconSize: [22,22], className: '' });
}

function boxIcon() {
    return L.divIcon({
        html: `<div style="width:8px;height:8px;border-radius:2px;background:#238636;opacity:.7;margin:-4px 0 0 -4px"></div>`,
        iconSize: [8,8], className: ''
    });
}

// ── 지도 초기화 ────────────────────────────────────────────────────────────
function initMap(center) {
    if (leafletMap) return;
    leafletMap = L.map('map', { zoomControl: true }).setView(center, 15);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '© CartoDB',
        maxZoom: 19,
    }).addTo(leafletMap);
    roadLayer  = L.layerGroup().addTo(leafletMap);
    stopLayer  = L.layerGroup().addTo(leafletMap);
    mapReady   = true;
}

// ── 도로 렌더링 (최초 1회) ─────────────────────────────────────────────────
function renderRoads(segments) {
    if (!mapReady || !roadLayer) return;
    roadLayer.clearLayers();
    segments.forEach(seg => {
        const slope = Math.abs(seg.slope_deg);
        const color = slope >= 25 ? '#f85149' : slope >= 15 ? '#d29922' : '#238636';
        const isNarrow = seg.min_width <= 2.0;
        L.polyline(
            [[seg.s_lat, seg.s_lon], [seg.e_lat, seg.e_lon]],
            { color, weight: isNarrow ? 2 : 4, opacity: 0.75,
              dashArray: isNarrow ? '4 3' : null }
        ).bindTooltip(
            `경사 ${slope.toFixed(1)}° | 폭 ${seg.min_width}m | ${isNarrow ? '🚫협로' : '🚛가능'}`
        ).addTo(roadLayer);
    });
}

// ── 배송지 렌더링 ──────────────────────────────────────────────────────────
function renderStops(stops) {
    if (!mapReady || !stopLayer) return;
    stopLayer.clearLayers();
    stops.forEach((s, i) => {
        L.marker([s[0], s[1]], { icon: boxIcon() })
         .bindTooltip(`📦 배송지 ${i+1}`)
         .addTo(stopLayer);
    });
}

// ── 에이전트 렌더링 (위치만 업데이트) ─────────────────────────────────────
function updateDrivers(drivers) {
    if (!mapReady) return;

    const seen = new Set();
    drivers.forEach(d => {
        seen.add(d.id);
        const icon = d.over ? doneIcon() : d.walking ? walkIcon('#f0883e') : truckIcon('#388bfd');
        const color = d.over ? '#8957e5' : d.walking ? '#f0883e' : '#388bfd';
        const pct = Math.min(100, Math.round(d.hours / d.max_hours * 100));
        const tooltip = `기사 ${d.id} | ${d.hours.toFixed(1)}h/${d.max_hours}h | ${d.delivered}건 | 건당 ${d.effective_mins}분`;

        if (driverLayers[d.id]) {
            // 이미 있으면 위치 + 아이콘만 업데이트 (지도 재렌더 없음)
            driverLayers[d.id].setLatLng([d.lat, d.lon]);
            driverLayers[d.id].setIcon(icon);
            driverLayers[d.id].setTooltipContent(tooltip);
        } else {
            const marker = L.marker([d.lat, d.lon], { icon })
                .bindTooltip(tooltip)
                .addTo(leafletMap);
            driverLayers[d.id] = marker;
        }
    });

    // 없어진 마커 제거
    Object.keys(driverLayers).forEach(id => {
        if (!seen.has(parseInt(id))) {
            leafletMap.removeLayer(driverLayers[id]);
            delete driverLayers[id];
        }
    });
}

// ── UI 업데이트 ────────────────────────────────────────────────────────────
function updateSummary(s) {
    document.getElementById('m-active').textContent = s.active;
    document.getElementById('m-over').textContent   = s.over;
    document.getElementById('m-done').textContent   = s.done;
    document.getElementById('m-remain').textContent = s.remain;

    const pct = s.total ? Math.round(s.done / s.total * 100) : 0;
    document.getElementById('pct-label').textContent = pct + '%';
    document.getElementById('total-prog').style.width = pct + '%';
    document.getElementById('total-prog').style.background =
        pct === 100 ? '#238636' : s.over > 0 ? '#f85149' : '#388bfd';

    const ab = document.getElementById('alert-box');
    if (s.over > 0) {
        ab.style.display = 'block';
        document.getElementById('alert-txt').textContent =
            `${s.over}명 법정 근무시간 초과 — 강제 퇴근 처리`;
    } else {
        ab.style.display = 'none';
    }

    const sb = document.getElementById('status-bar');
    if (s.remain === 0 && s.total > 0) {
        sb.style.color = '#238636';
        sb.textContent = `🏁 완료 · ${s.done}/${s.total}건 · ${s.over}명 초과`;
    } else {
        sb.style.color = s.over > 0 ? '#f85149' : '#388bfd';
        sb.textContent = `▶ 진행 중 · 완료 ${s.done}/${s.total}건 · ⛔${s.over}명 · 🚶${s.walking}명 도보 · 틱${s.tick}`;
    }
}

function updateDriverCards(drivers) {
    const list = document.getElementById('driver-list');
    list.innerHTML = '';
    drivers.forEach(d => {
        const pct = Math.min(100, Math.round(d.hours / d.max_hours * 100));
        const col = d.over ? '#f85149' : pct > 80 ? '#d29922' : '#238636';
        const cls = d.over ? 'driver-card over' : pct > 80 ? 'driver-card warn' : 'driver-card';
        const icon = d.over ? '🏠' : d.walking ? '🚶' : '🚛';
        const status = d.over ? '⛔ 퇴근' : d.walking ? '🚶 도보' : '🚛 운행';
        list.innerHTML += `
        <div class="${cls}">
          <div class="driver-header">
            <span class="driver-name">
              <span style="display:inline-block;width:7px;height:7px;border-radius:50%;
                background:${col};margin-right:4px;vertical-align:middle"></span>
              ${icon} 기사 ${d.id}
            </span>
            <span class="driver-status" style="color:${col}">${status}</span>
          </div>
          <div class="driver-row">
            <span>🕐 ${d.hours.toFixed(1)}h / ${d.max_hours}h</span>
            <span>📦 ${d.delivered}/${d.assigned}건</span>
          </div>
          <div class="pbar-bg">
            <div class="pbar-fg" style="width:${pct}%;background:${col}"></div>
          </div>
          <div class="driver-road">${d.road_info || '도로정보 없음'} · 건당 ${d.effective_mins}분</div>
        </div>`;
    });
}

function updateEnvStats(stats) {
    if (!stats || !stats.total) return;
    document.getElementById('env-stats').innerHTML = `
    <div style="display:flex;justify-content:space-between;border-bottom:0.5px solid #21262d;padding:4px 0;font-size:11px">
        <span style="color:#8b949e">총 세그먼트</span><span style="color:#e6edf3;font-weight:500">${stats.total.toLocaleString()}개</span>
    </div>
    <div style="display:flex;justify-content:space-between;border-bottom:0.5px solid #21262d;padding:4px 0;font-size:11px">
        <span style="color:#8b949e">최대 경사</span><span style="color:#f85149;font-weight:500">${stats.max_slope}°</span>
    </div>
    <div style="display:flex;justify-content:space-between;border-bottom:0.5px solid #21262d;padding:4px 0;font-size:11px">
        <span style="color:#8b949e">최소 도로폭</span><span style="color:#d29922;font-weight:500">${stats.min_width}m</span>
    </div>
    <div style="display:flex;justify-content:space-between;border-bottom:0.5px solid #21262d;padding:4px 0;font-size:11px">
        <span style="color:#8b949e">협로 (≤2m)</span><span style="color:#f85149;font-weight:500">${stats.narrow_pct}% (${stats.narrow_count}개)</span>
    </div>
    <div style="display:flex;justify-content:space-between;padding:4px 0;font-size:11px">
        <span style="color:#8b949e">급경사 (≥25°)</span><span style="color:#f85149;font-weight:500">${stats.steep_pct}% (${stats.steep_count}개)</span>
    </div>`;
}

// ── WebSocket 메시지 처리 ──────────────────────────────────────────────────
function handleMessage(msg) {
    if (msg.type === 'snapshot') {
        initMap(msg.center);
        renderRoads(msg.map_segments || []);
        renderStops(msg.stops || []);
        if (msg.drivers.length) {
            updateDrivers(msg.drivers);
            updateDriverCards(msg.drivers);
        }
        updateSummary(msg.summary);
        if (msg.env_stats) updateEnvStats(msg.env_stats);
        isRunning = msg.running;
        updateRunBtn();
    }
    else if (msg.type === 'tick') {
        updateDrivers(msg.drivers);
        updateDriverCards(msg.drivers);
        updateSummary(msg.summary);
    }
    else if (msg.type === 'started') {
        isRunning = true;
        updateRunBtn();
        switchTab('status');
    }
    else if (msg.type === 'paused') {
        isRunning = msg.running;
        updateRunBtn();
    }
    else if (msg.type === 'done') {
        isRunning = false;
        updateRunBtn();
        updateSummary(msg.summary);
    }
    else if (msg.type === 'params_updated') {
        // 파라미터 실시간 반영 확인
    }
}

// ── 컨트롤 이벤트 ──────────────────────────────────────────────────────────
function onRunClick() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (!isRunning && !document.getElementById('m-done').textContent !== '0') {
        // 새 시뮬레이션 시작
        ws.send(JSON.stringify({
            action:           'start',
            max_legal_hours:  parseInt(document.getElementById('p-maxhours').value),
            n_drivers:        parseInt(document.getElementById('p-drivers').value),
            daily_volume:     parseInt(document.getElementById('p-volume').value),
        }));
    } else {
        ws.send(JSON.stringify({ action: 'pause' }));
    }
}

function onReset() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    // 드라이버 마커 전부 제거
    Object.values(driverLayers).forEach(m => leafletMap.removeLayer(m));
    driverLayers = {};
    ws.send(JSON.stringify({ action: 'reset' }));
    isRunning = false;
    updateRunBtn();
}

function onParamChange() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({
        action:           'update_params',
        max_legal_hours:  parseInt(document.getElementById('p-maxhours').value),
        n_drivers:        parseInt(document.getElementById('p-drivers').value),
        daily_volume:     parseInt(document.getElementById('p-volume').value),
    }));
}

function updateRunBtn() {
    const btn = document.getElementById('btn-run');
    btn.textContent = isRunning ? '⏸ 일시정지' : '▶ 실행';
    btn.style.background = isRunning ? '#388bfd' : '#1f6feb';
}

// ── 탭 전환 ───────────────────────────────────────────────────────────────
function switchTab(name) {
    document.querySelectorAll('.tab-btn').forEach((b, i) => {
        const names = ['status', 'params', 'env'];
        b.classList.toggle('active', names[i] === name);
    });
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
}

// ── WebSocket 연결 관리 ────────────────────────────────────────────────────
function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws`);

    ws.onopen = () => {
        document.getElementById('conn-dot').classList.add('connected');
        document.getElementById('conn-label').textContent = '연결됨';
    };
    ws.onclose = () => {
        document.getElementById('conn-dot').classList.remove('connected');
        document.getElementById('conn-label').textContent = '연결 끊김 — 재연결 중...';
        setTimeout(connect, 2000);  // 자동 재연결
    };
    ws.onerror = () => ws.close();
    ws.onmessage = e => handleMessage(JSON.parse(e.data));
}

connect();
