// ── 대기 화면: TMap + updateMarker 패턴 ─────────────────────
// 참고: https://ttaerrim.tistory.com/61
// currentMarker를 변수로 관리하고, 위치 변경 시
//   1. currentMarker?.setMap(null)  → 기존 마커 제거
//   2. new Tmapv2.Marker(...)       → 새 마커 생성
//   3. mapInstance.setCenter(pos)   → 지도 중심 이동
// 이 세 단계를 updateMarker() 하나로 캡슐화

let tmapObj    = null;
let riderLat   = 37.4704, riderLon = 126.9312;

// ── 마커 레지스트리: 역할별 currentMarker 관리 ────────────────
const markers = {
    rider:  null,   // 내 위치 (파란 원)
    store:  null,   // 픽업 매장 (파란 핀)
    dest:   null,   // 배달지 (주황 핀)
};

// 경로선 목록
let routeLines = [];

// ── 핵심: updateMarker ────────────────────────────────────────
/**
 * @param {string}  role   - 'rider' | 'store' | 'dest'
 * @param {number}  lat
 * @param {number}  lon
 * @param {object}  opts   - { icon, iconSize, moveCenter }
 *
 * 동작:
 *   1. 이전 마커가 있으면 setMap(null) 로 제거
 *   2. 위도/경도가 이전과 같으면 아무것도 안 함
 *   3. 새 마커 생성 후 markers[role] 에 저장
 *   4. moveCenter: true 이면 지도 중심 이동
 */
function updateMarker(role, lat, lon, opts = {}) {
    if (!tmapObj || typeof Tmapv2 === 'undefined') return;
    if (!lat || !lon) return;

    const prev = markers[role];

    // 이전 마커와 위치 동일하면 스킵
    if (prev) {
        const prevPos = prev.getPosition();
        if (prevPos._lat === lat && prevPos._lng === lon) return;
        prev.setMap(null);   // ← 기존 마커 제거
    }

    const position = new Tmapv2.LatLng(lat, lon);

    markers[role] = new Tmapv2.Marker({
        position,
        map:      tmapObj,
        icon:     opts.icon || riderDotIcon(),
        iconSize: opts.iconSize || new Tmapv2.Size(48, 48),
    });

    if (opts.moveCenter) {
        tmapObj.setCenter(position);
    }
}

// ── 마커 제거 헬퍼 ────────────────────────────────────────────
function removeMarker(role) {
    if (markers[role]) {
        markers[role].setMap(null);
        markers[role] = null;
    }
}

// ── TMap 초기화 ───────────────────────────────────────────────
function initTmap() {
    if (typeof Tmapv2 === 'undefined') {
        console.warn('[TMap] Tmapv2 없음 — SDK 미로드');
        renderMockBg(document.getElementById('tmap-wrap'));
        return;
    }
    tmapObj = new Tmapv2.Map('tmap-wrap', {
        center:      new Tmapv2.LatLng(riderLat, riderLon),
        width:       '100%',
        height:      '100%',
        zoom:        15,
        zoomControl: false,
    });

    // 내 위치 마커 최초 표시
    updateMarker('rider', riderLat, riderLon, {
        icon:       riderDotIcon(),
        iconSize:   new Tmapv2.Size(48, 48),
        moveCenter: false,
    });

    startGPS();
}

function renderMockBg(el) {
    el.style.cssText = 'position:absolute;inset:0;background:linear-gradient(160deg,#1a2035 0%,#0f1520 100%)';
    el.innerHTML = `
      <div style="position:absolute;inset:0;display:flex;align-items:center;
                  justify-content:center;flex-direction:column;gap:6px;opacity:.35">
        <div style="font-size:48px">🗺️</div>
        <div style="font-size:12px;color:#8b949e">TMap API 키 설정 후 실제 지도 표시</div>
      </div>`;
}

// ── GPS 실시간 추적 ───────────────────────────────────────────
function startGPS() {
    if (!navigator.geolocation) return;
    navigator.geolocation.watchPosition(pos => {
        riderLat = pos.coords.latitude;
        riderLon = pos.coords.longitude;
        // updateMarker로 내 위치 마커 업데이트
        updateMarker('rider', riderLat, riderLon, {
            icon:       riderDotIcon(),
            iconSize:   new Tmapv2.Size(48, 48),
            moveCenter: false,
        });
    }, null, { enableHighAccuracy: true, maximumAge: 3000 });
}

// ── 동 변경 ───────────────────────────────────────────────────
function onDongChange() {
    const v = document.getElementById('dong-select').value;
    const centers = {
        '난곡동': [37.4704, 126.9312],
        '신림동': [37.4812, 126.9224],
    };
    const c = centers[v] || centers['난곡동'];
    riderLat = c[0]; riderLon = c[1];
    if (tmapObj) tmapObj.setCenter(new Tmapv2.LatLng(riderLat, riderLon));
    // 내 위치 마커도 갱신
    updateMarker('rider', riderLat, riderLon, {
        icon: riderDotIcon(), iconSize: new Tmapv2.Size(48, 48),
    });
}

// ── 콜 수신 시: 매장·배달지 마커 + 경로선 ─────────────────────
function drawCallOnMap(data) {
    clearCallOnMap();
    if (!tmapObj || typeof Tmapv2 === 'undefined') return;

    const sl = data.polyline_to_store;
    const dl = data.polyline_to_dest;

    // 매장 마커 — updateMarker 사용
    if (sl && sl.length) {
        const ep = sl[sl.length - 1];
        updateMarker('store', ep[1], ep[0], {
            icon:       storePinIcon(),
            iconSize:   new Tmapv2.Size(36, 44),
            moveCenter: false,
        });
    }

    // 배달지 마커 — updateMarker 사용
    if (dl && dl.length) {
        const ep = dl[dl.length - 1];
        updateMarker('dest', ep[1], ep[0], {
            icon:       destPinIcon(),
            iconSize:   new Tmapv2.Size(36, 44),
            moveCenter: false,
        });
    }

    // 경로선
    _drawLine(sl, '#3A86FF');
    _drawLine(dl, '#FF6B35');

    // 두 포인트가 모두 보이도록 지도 범위 조정
    _fitBounds([...(sl||[]), ...(dl||[])]);
}

function _drawLine(coords, color) {
    if (!coords || coords.length < 2) return;
    const poly = new Tmapv2.Polyline({
        path:          coords.map(c => new Tmapv2.LatLng(c[1], c[0])),
        strokeColor:   color,
        strokeWeight:  5,
        strokeOpacity: 0.85,
        map:           tmapObj,
    });
    routeLines.push(poly);
}

function _fitBounds(coords) {
    if (coords.length < 2) return;
    const lats = coords.map(c => c[1]), lons = coords.map(c => c[0]);
    const sw = new Tmapv2.LatLng(Math.min(...lats), Math.min(...lons));
    const ne = new Tmapv2.LatLng(Math.max(...lats), Math.max(...lons));
    try {
        tmapObj.fitBounds(new Tmapv2.LatLngBounds(sw, ne), { paddingBottom: 340 });
    } catch {
        // fitBounds 미지원 시 중간점으로 이동
        tmapObj.setCenter(new Tmapv2.LatLng(
            (Math.min(...lats) + Math.max(...lats)) / 2,
            (Math.min(...lons) + Math.max(...lons)) / 2,
        ));
    }
}

// 콜 종료 시 마커·경로선 제거
function clearCallOnMap() {
    removeMarker('store');
    removeMarker('dest');
    routeLines.forEach(l => { try { l.setMap(null); } catch(e){} });
    routeLines = [];
}

// ── 아이콘 SVG ────────────────────────────────────────────────
function riderDotIcon() {
    const s = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
      <circle cx="24" cy="24" r="20" fill="rgba(0,200,150,.2)"/>
      <circle cx="24" cy="24" r="10" fill="#00C896" stroke="white" stroke-width="2.5"/>
    </svg>`;
    return 'data:image/svg+xml;base64,' + btoa(s);
}
function storePinIcon() {
    const s = `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="44" viewBox="0 0 36 44">
      <path d="M18 0C8 0 0 8 0 18c0 13.5 18 26 18 26S36 31.5 36 18C36 8 28 0 18 0z" fill="#3A86FF"/>
      <text x="18" y="24" font-size="15" text-anchor="middle" fill="white">🏪</text>
    </svg>`;
    return 'data:image/svg+xml;base64,' + btoa(s);
}
function destPinIcon() {
    const s = `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="44" viewBox="0 0 36 44">
      <path d="M18 0C8 0 0 8 0 18c0 13.5 18 26 18 26S36 31.5 36 18C36 8 28 0 18 0z" fill="#FF6B35"/>
      <text x="18" y="24" font-size="15" text-anchor="middle" fill="white">📦</text>
    </svg>`;
    return 'data:image/svg+xml;base64,' + btoa(s);
}

// ── 콜 시뮬레이션 ─────────────────────────────────────────────
async function simulateCall() {
    const dong = document.getElementById('dong-select').value;
    try {
        const res = await fetch('/rider/sim-call', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rider_lat: riderLat, rider_lon: riderLon, dong_name: dong }),
        });
        openCallPopup(await res.json());
    } catch {
        openCallPopup(getMockCall());
    }
}

function getMockCall() {
    return {
        call_id: 'CALL-3847', expires_in: 30,
        store_name: '○○치킨 난곡점', dest_name: '난곡동 123-4 (5층)',
        tmap:   { distance_km: 1.2, minutes: 5.0, fare: 3500 },
        actual: { distance_km: 2.8, minutes: 19.0, walk_km: 1.6, walk_minutes: 15.0 },
        safe_fare: { base_fare: 3500, surcharge: 835, total: 4335, walk_over: 5 },
        terrain: {
            max_slope: 18.5, narrow_ratio: 0.38,
            warnings: ['이륜차 진입 불가 협로 38% 포함', '경사도 18.5° 급경사 구간'],
        },
        gap: { minutes: 14.0, fare: 835 },
        polyline_to_store: [[126.9312,37.4704],[126.9305,37.4700],[126.9298,37.4698]],
        polyline_to_dest:  [[126.9298,37.4698],[126.9285,37.4683],[126.9275,37.4671]],
        is_mock: true,
    };
}