// ── 내비 화면 ─────────────────────────────────────────────────
let navPhase = 'to_store';
let navMap   = null, navGpsId = null, navMyMarker = null;

function startNavigation(phase) {
    navPhase = phase;
    showScreen('nav');
    const d = callData;
    if (!d) return;

    if (phase === 'to_store') {
        document.getElementById('nav-phase').textContent   = '📍 매장으로 이동';
        document.getElementById('nav-dest').textContent    = d.store_name;
        document.getElementById('nav-dist').textContent    = `${(d.tmap.distance_km*0.4).toFixed(1)}km`;
        document.getElementById('nav-eta').textContent     = `약 ${Math.ceil(d.tmap.minutes*0.4)}분`;
        document.getElementById('nav-action-btn').textContent = '📦 픽업 완료';
    } else {
        document.getElementById('nav-phase').textContent   = '🚗 배달지로 이동';
        document.getElementById('nav-dest').textContent    = d.dest_name;
        document.getElementById('nav-dist').textContent    = `${d.actual.distance_km.toFixed(1)}km`;
        document.getElementById('nav-eta').textContent     = `약 ${d.actual.minutes.toFixed(0)}분`;
        document.getElementById('nav-action-btn').textContent = '✅ 배달 완료';
    }

    initNavMap(phase);
}

function initNavMap(phase) {
    const d = callData;
    if (!d) return;
    const wrap = document.getElementById('nav-map-wrap');

    if (typeof Tmapv2 === 'undefined' || window._tmapFailed) {
        wrap.style.cssText = 'position:absolute;inset:0;background:linear-gradient(160deg,#1a2035,#0f1520)';
        const color = phase === 'to_store' ? '#3A86FF' : '#FF6B35';
        const icon  = phase === 'to_store' ? '🏪' : '📦';
        wrap.innerHTML = `<div style="position:absolute;inset:0;display:flex;align-items:center;
          justify-content:center;flex-direction:column;gap:8px">
          <div style="font-size:56px">${icon}</div>
          <div style="font-size:14px;font-weight:600;color:${color}">내비 모드</div>
          <div style="font-size:11px;color:rgba(255,255,255,.3)">TMap API 키 설정 후 실제 내비 표시</div>
        </div>`;
        return;
    }

    if (!navMap) {
        navMap = new Tmapv2.Map('nav-map-wrap', {
            center: new Tmapv2.LatLng(riderLat, riderLon),
            width: '100%', height: '100%', zoom: 15,
        });
    }
    navMap.setCenter(new Tmapv2.LatLng(riderLat, riderLon));

    // 경로 그리기
    const poly = phase === 'to_store' ? d.polyline_to_store : d.polyline_to_dest;
    const color = phase === 'to_store' ? '#3A86FF' : '#FF6B35';
    if (poly && poly.length > 1) {
        new Tmapv2.Polyline({
            path: poly.map(c => new Tmapv2.LatLng(c[1], c[0])),
            strokeColor: color, strokeWeight: 6, map: navMap,
        });
        // 목적지 마커
        const ep = poly[poly.length - 1];
        new Tmapv2.Marker({
            position: new Tmapv2.LatLng(ep[1], ep[0]),
            icon: phase === 'to_store' ? storePinIcon() : destPinIcon(),
            map: navMap,
        });
    }

    // GPS 추적
    if (navGpsId) navigator.geolocation?.clearWatch(navGpsId);
    navGpsId = navigator.geolocation?.watchPosition(pos => {
        riderLat = pos.coords.latitude; riderLon = pos.coords.longitude;
        if (navMyMarker) navMyMarker.setPosition(new Tmapv2.LatLng(riderLat, riderLon));
        else navMyMarker = new Tmapv2.Marker({
            position: new Tmapv2.LatLng(riderLat, riderLon),
            icon: riderDotIcon(), map: navMap,
        });
        navMap.setCenter(new Tmapv2.LatLng(riderLat, riderLon));
    }, null, { enableHighAccuracy: true, maximumAge: 2000 });
}

function onNavAction() {
    if (navGpsId) navigator.geolocation?.clearWatch(navGpsId);
    if (navPhase === 'to_store') {
        showToast('📦 픽업 완료!');
        setTimeout(() => startNavigation('to_dest'), 600);
    } else {
        finishDelivery();
    }
}

function finishDelivery() {
    const d = callData;
    if (!d) { showScreen('standby'); return; }
    const rec = {
        ts: new Date().toISOString(), store: d.store_name, dest: d.dest_name,
        fare: d.tmap.fare, safe: d.safe_fare.total, gap: d.gap.fare,
        walk: d.actual.walk_minutes,
    };
    const h = JSON.parse(localStorage.getItem('rh') || '[]');
    h.push(rec); localStorage.setItem('rh', JSON.stringify(h));
    showToast(`✅ 완료! +${d.tmap.fare.toLocaleString()}원`);
    showScreen('standby');
    callData = null;
    refreshEarnings();
}