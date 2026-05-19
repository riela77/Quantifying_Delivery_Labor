// LastMile Labor — WebSocket 클라이언트

// ── 전역 상태 ─────────────────────────────────────────────────
let ws = null;
let leafletMap = null;
let roadLayer  = null;
let stopLayer  = null;
let routeLayer = null;
let driverMarkers = {};  // id → { marker, line }
let isRunning = false;

// ── 아이콘 헬퍼 ───────────────────────────────────────────────
function mkDivIcon(html, size) {
    return L.divIcon({
        html: `<div style="margin:-${size/2}px 0 0 -${size/2}px">${html}</div>`,
        iconSize: [size, size],
        className: ''
    });
}
function truckIcon(c) {
    return mkDivIcon(`<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M1 3h15v13H1z"/><path d="M16 8h4l3 5v4h-7V8z"/><circle cx="5.5" cy="18.5" r="2.5" fill="${c}" stroke="none"/><circle cx="18.5" cy="18.5" r="2.5" fill="${c}" stroke="none"/></svg>`, 28);
}
function walkIcon(c) {
    return mkDivIcon(`<svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="4" r="2" fill="${c}" stroke="none"/><path d="M9 22l1-7-2-3 3-4 2 3h3"/><path d="M15 22l-1-7"/><path d="M7 13l-2 2"/><path d="M17 9l2 2"/></svg>`, 26);
}
function doneIcon() {
    return mkDivIcon(`<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#8957e5" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>`, 22);
}
function getIcon(d) {
    if (d.over)    return doneIcon();
    if (d.walking) return walkIcon('#f0883e');
    return truckIcon('#388bfd');
}

// ── 지도 초기화 ───────────────────────────────────────────────
function initMap(center) {
    if (leafletMap) return;
    leafletMap = L.map('map', { zoomControl: true }).setView(center, 16);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '© CartoDB', maxZoom: 19
    }).addTo(leafletMap);
    roadLayer  = L.layerGroup().addTo(leafletMap);
    stopLayer  = L.layerGroup().addTo(leafletMap);
    routeLayer = L.layerGroup().addTo(leafletMap);
    console.log('[Map] initialized at', center);
}

// ── 도로 렌더 ─────────────────────────────────────────────────
function renderRoads(segs) {
    if (!leafletMap || !segs || !segs.length) return;
    roadLayer.clearLayers();
    segs.forEach(s => {
        const slope  = Math.abs(s.sl);
        const color  = slope >= 25 ? '#f85149' : slope >= 15 ? '#d29922' : '#238636';
        const narrow = s.w <= 2.0;
        L.polyline([[s.slat, s.slon], [s.elat, s.elon]], {
            color, weight: narrow ? 2 : 4, opacity: 0.75,
            dashArray: narrow ? '4 3' : null
        }).addTo(roadLayer);
    });
    console.log('[Map] roads rendered:', segs.length);
}

// ── 배송지 마커 ───────────────────────────────────────────────
function renderStops(stops) {
    if (!leafletMap || !stops || !stops.length) return;
    stopLayer.clearLayers();
    stops.forEach((s, i) => {
        L.marker([s[0], s[1]], {
            icon: L.divIcon({
                html: '<div style="width:8px;height:8px;border-radius:2px;background:#238636;opacity:.9;margin:-4px 0 0 -4px"></div>',
                iconSize: [8, 8], className: ''
            })
        }).bindTooltip(`📦 배송지 ${i+1}`).addTo(stopLayer);
    });
    console.log('[Map] stops rendered:', stops.length);
}

// ── 에이전트 렌더 ─────────────────────────────────────────────
function updateDrivers(drivers) {
    if (!leafletMap || !drivers || !drivers.length) return;

    const seen = new Set();
    drivers.forEach(d => {
        seen.add(d.id);
        const icon  = getIcon(d);
        const color = d.over ? '#8957e5' : d.walking ? '#f0883e' : '#388bfd';
        const nlat  = d.next_lat != null ? d.next_lat : d.lat;
        const nlon  = d.next_lon != null ? d.next_lon : d.lon;
        const tip   = `기사${d.id} | ${d.hours.toFixed(1)}h/${d.max_h}h | ${d.delivered}건 | 건당${d.eff_mins}분`;

        if (driverMarkers[d.id]) {
            driverMarkers[d.id].marker.setLatLng([d.lat, d.lon]).setIcon(icon);
            driverMarkers[d.id].marker.setTooltipContent(tip);
            driverMarkers[d.id].line.setLatLngs([[d.lat, d.lon], [nlat, nlon]]);
        } else {
            const marker = L.marker([d.lat, d.lon], { icon })
                .bindTooltip(tip)
                .addTo(leafletMap);
            const line = L.polyline(
                [[d.lat, d.lon], [nlat, nlon]],
                { color, weight: 1, opacity: 0.3, dashArray: '3 5' }
            ).addTo(routeLayer);
            driverMarkers[d.id] = { marker, line };
        }
    });

    // 없어진 마커 제거
    Object.keys(driverMarkers).forEach(id => {
        const numId = parseInt(id);
        if (!seen.has(numId)) {
            leafletMap.removeLayer(driverMarkers[id].marker);
            routeLayer.removeLayer(driverMarkers[id].line);
            delete driverMarkers[id];
        }
    });
}

// ── 마커 전체 제거 ────────────────────────────────────────────
function clearDriverMarkers() {
    Object.values(driverMarkers).forEach(dm => {
        try { if (leafletMap) leafletMap.removeLayer(dm.marker); } catch(e) {}
        try { if (routeLayer) routeLayer.removeLayer(dm.line); } catch(e) {}
    });
    driverMarkers = {};
}

// ── UI 업데이트 ───────────────────────────────────────────────
function updateSummary(s) {
    document.getElementById('m-active').textContent = s.active;
    document.getElementById('m-over').textContent   = s.over;
    document.getElementById('m-done').textContent   = s.done;
    document.getElementById('m-walk').textContent   = s.walking;

    const pct = s.total ? Math.round(s.done / s.total * 100) : 0;
    document.getElementById('pct-lbl').textContent  = pct + '%';
    const bar = document.getElementById('prog-bar');
    bar.style.width      = pct + '%';
    bar.style.background = pct === 100 ? '#238636' : s.over > 0 ? '#f85149' : '#388bfd';

    const ab = document.getElementById('alert-box');
    if (s.over > 0) {
        ab.style.display = 'block';
        document.getElementById('alert-txt').textContent = `${s.over}명 법정시간 초과 — 강제 퇴근`;
    } else {
        ab.style.display = 'none';
    }

    const sb = document.getElementById('status-bar');
    if (!s.total) {
        sb.style.color = '#8b949e';
        sb.textContent = '▶ 파라미터 탭에서 설정 후 실행하세요';
        return;
    }
    sb.style.color = s.remain === 0 ? '#238636' : s.over > 0 ? '#f85149' : '#388bfd';
    sb.textContent = s.remain === 0
        ? `🏁 완료 · ${s.done}/${s.total}건 · ${s.over}명 초과`
        : `▶ 진행 · ${s.done}/${s.total}건 · ⛔${s.over}명 · 🚶${s.walking}명 · 틱${s.tick}`;
}

function updateDriverCards(drivers) {
    const list = document.getElementById('driver-list');
    if (!drivers || !drivers.length) {
        list.innerHTML = '<div style="color:#8b949e;font-size:11px;text-align:center;margin-top:16px">실행 후 표시됩니다</div>';
        return;
    }
    list.innerHTML = drivers.map(d => {
        const pct = Math.min(100, Math.round(d.hours / d.max_h * 100));
        const col = d.over ? '#f85149' : pct > 80 ? '#d29922' : '#238636';
        const cls = d.over ? 'dc over' : pct > 80 ? 'dc warn' : 'dc';
        const icon = d.over ? '🏠' : d.walking ? '🚶' : '🚛';
        const st   = d.over ? '⛔퇴근' : d.walking ? '🚶도보' : '🚛운행';
        return `<div class="${cls}">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
            <span style="font-weight:500;color:#e6edf3">
              <span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${col};margin-right:4px;vertical-align:middle"></span>
              ${icon} 기사${d.id}
            </span>
            <span style="font-size:10px;color:${col}">${st}</span>
          </div>
          <div style="display:flex;justify-content:space-between;color:#8b949e;font-size:10px;margin-bottom:3px">
            <span>🕐 ${d.hours.toFixed(1)}h / ${d.max_h}h</span>
            <span>📦 ${d.delivered}/${d.assigned}건</span>
          </div>
          <div style="background:#21262d;border-radius:3px;height:4px;margin-bottom:3px">
            <div style="width:${pct}%;background:${col};border-radius:3px;height:4px;transition:width .3s"></div>
          </div>
          <div style="font-size:9px;color:#8b949e">${d.road || '—'} · 건당 ${d.eff_mins}분</div>
        </div>`;
    }).join('');
}

function updateEnvStats(stats, region) {
    if (!stats || !stats.total) return;
    const el = document.getElementById('region-name');
    if (el) el.textContent = region || '';
    document.getElementById('env-stats').innerHTML = `
      <div style="font-size:11px">
        <div style="display:flex;justify-content:space-between;border-bottom:0.5px solid #21262d;padding:4px 0">
          <span style="color:#8b949e">도로 노드</span>
          <span style="color:#e6edf3;font-weight:500">${stats.total.toLocaleString()}개</span>
        </div>
        <div style="display:flex;justify-content:space-between;border-bottom:0.5px solid #21262d;padding:4px 0">
          <span style="color:#8b949e">협로(≤2m)</span>
          <span style="color:#f85149;font-weight:500">${stats.narrow_pct}%</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:4px 0">
          <span style="color:#8b949e">급경사(≥15°)</span>
          <span style="color:#d29922;font-weight:500">${stats.steep_pct}%</span>
        </div>
      </div>`;
}

function populateZones(zones, current) {
    const sel = document.getElementById('zone-select');
    if (!sel) return;
    // 이미 같은 옵션이면 재생성 안 함
    if (sel.options.length === zones.length) return;
    sel.innerHTML = '';
    zones.forEach((z, i) => {
        const opt = document.createElement('option');
        opt.value = i; opt.textContent = z;
        if (i === current) opt.selected = true;
        sel.appendChild(opt);
    });
}

function updateRunBtn() {
    const btn = document.getElementById('btn-run');
    if (!btn) return;
    btn.textContent      = isRunning ? '⏸ 일시정지' : '▶ 실행';
    btn.style.background = isRunning ? '#388bfd'    : '#1f6feb';
}

// ── 탭 전환 ───────────────────────────────────────────────────
function switchTab(name) {
    ['status', 'params', 'env'].forEach((n, i) => {
        document.querySelectorAll('.tab-btn')[i].classList.toggle('active', n === name);
        document.getElementById('tab-' + n).classList.toggle('active', n === name);
    });
}

// ── WebSocket 메시지 핸들러 ───────────────────────────────────
function handleMessage(msg) {
    console.log('[WS] received:', msg.type, msg);

    if (msg.type === 'snapshot' || msg.type === 'zone_changed') {
        console.log('[WS] center:', msg.center, 'has_data:', msg.has_data, 'stops:', msg.stops && msg.stops.length);
        initMap(msg.center);
        if (msg.map_segs && msg.map_segs.length) renderRoads(msg.map_segs);
        if (msg.stops     && msg.stops.length)    renderStops(msg.stops);
        if (msg.drivers   && msg.drivers.length) {
            updateDrivers(msg.drivers);
            updateDriverCards(msg.drivers);
        }
        updateSummary(msg.summary);
        if (msg.env_stats) updateEnvStats(msg.env_stats, msg.region);
        if (msg.zones)     populateZones(msg.zones, (msg.params && msg.params.zone) || 0);
        isRunning = msg.running;
        updateRunBtn();
        if (msg.type === 'zone_changed' && leafletMap) leafletMap.setView(msg.center, 16);
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
        if (msg.stops   && msg.stops.length)   renderStops(msg.stops);
        if (msg.drivers && msg.drivers.length) {
            updateDrivers(msg.drivers);
            updateDriverCards(msg.drivers);
        }
        console.log('[WS] simulation started, drivers:', msg.drivers && msg.drivers.length);
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
}

// ── 컨트롤 이벤트 ─────────────────────────────────────────────
function onRun() {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        console.warn('[WS] not connected');
        return;
    }
    if (!isRunning) {
        const payload = {
            action:          'start',
            max_legal_hours: parseInt(document.getElementById('p-hours').value),
            n_drivers:       parseInt(document.getElementById('p-drivers').value),
            daily_volume:    parseInt(document.getElementById('p-vol').value),
        };
        console.log('[WS] sending start:', payload);
        ws.send(JSON.stringify(payload));
    } else {
        ws.send(JSON.stringify({ action: 'pause' }));
    }
}

function onReset() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    clearDriverMarkers();
    ws.send(JSON.stringify({ action: 'reset' }));
    isRunning = false;
    updateRunBtn();
    updateDriverCards([]);
    updateSummary({ active:0, over:0, walking:0, done:0, total:0, remain:0, tick:0 });
}

function onZoneChange() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const idx = parseInt(document.getElementById('zone-select').value);
    clearDriverMarkers();
    console.log('[WS] set_zone:', idx);
    ws.send(JSON.stringify({ action: 'set_zone', zone: idx }));
}

function onParamChange() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({
        action:          'update_params',
        max_legal_hours: parseInt(document.getElementById('p-hours').value),
        n_drivers:       parseInt(document.getElementById('p-drivers').value),
        daily_volume:    parseInt(document.getElementById('p-vol').value),
    }));
}

// ── 슬라이더 ↔ 숫자입력 동기화 ───────────────────────────────
function setupSyncInput(sliderId, numberId) {
    const slider = document.getElementById(sliderId);
    const number = document.getElementById(numberId);
    if (!slider || !number) return;

    const clamp = v => Math.min(Math.max(v, parseInt(slider.min)), parseInt(slider.max));

    slider.addEventListener('input', () => {
        number.value = slider.value;
        onParamChange();
    });
    number.addEventListener('input', () => {
        const v = clamp(parseInt(number.value) || parseInt(slider.min));
        slider.value  = v;
        number.value  = v;
        onParamChange();
    });
    number.addEventListener('blur', () => {
        const v = clamp(parseInt(number.value) || parseInt(slider.min));
        slider.value = v;
        number.value = v;
    });
}

// ── WebSocket 연결 ────────────────────────────────────────────
function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const url   = `${proto}://${location.host}/ws`;
    console.log('[WS] connecting to', url);
    ws = new WebSocket(url);

    ws.onopen = () => {
        console.log('[WS] connected');
        document.getElementById('conn-dot').classList.add('connected');
        document.getElementById('conn-lbl').textContent = '연결됨';
    };
    ws.onclose = () => {
        console.log('[WS] disconnected, retrying...');
        document.getElementById('conn-dot').classList.remove('connected');
        document.getElementById('conn-lbl').textContent = '재연결 중...';
        setTimeout(connect, 2000);
    };
    ws.onerror = err => {
        console.error('[WS] error:', err);
        ws.close();
    };
    ws.onmessage = e => {
        try {
            handleMessage(JSON.parse(e.data));
        } catch(err) {
            console.error('[WS] parse error:', err, e.data);
        }
    };
}

// ── 진입점 ────────────────────────────────────────────────────
setupSyncInput('p-drivers', 'n-drivers');
setupSyncInput('p-vol', 'n-vol');
connect();

// ── GeoJSON 업로드 + 전처리 폴링 ─────────────────────────────
let prepPollTimer = null;

async function onGeoJsonUpload(input) {
    const file = input.files[0];
    if (!file) return;
    console.log('[Upload] 파일 선택:', file.name, file.size, 'bytes');

    const statusDiv = document.getElementById('prep-status');
    statusDiv.style.display = 'block';
    document.getElementById('prep-msg').textContent = file.name + ' 업로드 중...';
    document.getElementById('prep-pct').textContent = '0%';
    document.getElementById('prep-bar').style.width = '5%';
    document.getElementById('prep-bar').style.background = '#388bfd';

    // 업로드존 상태 변경
    const zone = document.getElementById('upload-zone');
    zone.style.borderColor = '#388bfd';
    zone.innerHTML = '<div style="font-size:14px;margin-bottom:4px">⏳</div>'
        + '<div style="font-size:11px;color:#388bfd">' + file.name + ' 업로드 중...</div>';

    const fd = new FormData();
    fd.append('file', file);
    try {
        console.log('[Upload] fetch /upload-geojson 시작');
        const res  = await fetch('/upload-geojson', { method: 'POST', body: fd });
        const data = await res.json();
        console.log('[Upload] 서버 응답:', data);
        if (data.error) { showPrepError(data.error); return; }
        zone.innerHTML = '<div style="font-size:14px;margin-bottom:4px">⚙️</div>'
            + '<div style="font-size:11px;color:#d29922">전처리 중... 잠시 기다려주세요</div>';
        startPrepPolling();
    } catch (e) {
        console.error('[Upload] 오류:', e);
        showPrepError('업로드 실패: ' + e.message);
    }
}

function startPrepPolling() {
    if (prepPollTimer) clearInterval(prepPollTimer);
    prepPollTimer = setInterval(async () => {
        try {
            const res  = await fetch('/prep-status');
            const data = await res.json();
            updatePrepUI(data);
            if (data.state === 'done' || data.state === 'error') {
                clearInterval(prepPollTimer); prepPollTimer = null;
            }
        } catch (e) {}
    }, 800);
}

function updatePrepUI(data) {
    document.getElementById('prep-msg').textContent = data.message || '';
    document.getElementById('prep-pct').textContent = (data.progress || 0) + '%';
    document.getElementById('prep-bar').style.width  = (data.progress || 0) + '%';

    if (data.state === 'done') {
        document.getElementById('prep-bar').style.background = '#238636';
        console.log('[Prep] 완료:', data.message);
        // 업로드존 완료 상태로 변경
        const zone = document.getElementById('upload-zone');
        if (zone) {
            zone.style.borderColor = '#238636';
            zone.innerHTML = '<div style="font-size:14px;margin-bottom:4px">✅</div>'
                + '<div style="font-size:11px;color:#238636;font-weight:500">' + data.message + '</div>'
                + '<div style="font-size:10px;color:#8b949e;margin-top:4px">다른 파일 업로드하려면 클릭</div>';
            zone.onclick = () => document.getElementById('geojson-input').click();
        }
        // 드롭다운 갱신
        if (data.zones && data.zones.length) {
            const sel = document.getElementById('zone-select');
            sel.innerHTML = '';
            data.zones.forEach((z, i) => {
                const opt = document.createElement('option');
                opt.value = i; opt.textContent = z;
                if (i === 0) opt.selected = true;
                sel.appendChild(opt);
            });
        }
        if (data.center   && leafletMap) leafletMap.setView(data.center, 15);
        if (data.map_segs) renderRoads(data.map_segs);
        if (data.stops)    renderStops(data.stops);
        if (data.env_stats) updateEnvStats(data.env_stats, data.region);
        const rn = document.getElementById('region-name');
        if (rn) rn.textContent = data.region || '';
    } else if (data.state === 'error') {
        showPrepError(data.message);
    }
}

function showPrepError(msg) {
    console.error('[Prep] 오류:', msg);
    document.getElementById('prep-bar').style.background = '#f85149';
    document.getElementById('prep-msg').textContent = '❌ ' + msg;
    document.getElementById('prep-pct').textContent = '';
    const zone = document.getElementById('upload-zone');
    if (zone) {
        zone.style.borderColor = '#f85149';
        zone.innerHTML = '<div style="font-size:14px;margin-bottom:4px">❌</div>'
            + '<div style="font-size:11px;color:#f85149">' + msg + '</div>'
            + '<div style="font-size:10px;color:#8b949e;margin-top:4px">다시 시도하려면 클릭</div>';
        zone.onclick = () => document.getElementById('geojson-input').click();
    }
}