// ── 콜 팝업: 지도 위 슬라이드업 카드 ────────────────────────
let callData    = null;
let timerSec    = 30;
let timerHandle = null;
let openChip    = null;   // 현재 열린 칩: 'store' | 'dest' | null

function openCallPopup(data) {
    callData = data;
    timerSec = data.expires_in || 30;

    // 지도에 마커/경로
    drawCallOnMap(data);

    // 난배송 배지
    const hasTerrain = data.terrain && data.terrain.warnings && data.terrain.warnings.length;
    document.getElementById('hard-badge').style.display = hasTerrain ? 'inline-block' : 'none';

    // 칩 정보
    document.getElementById('chip-store-name').textContent = data.store_name || '—';
    document.getElementById('chip-dest-name').textContent  = data.dest_name  || '—';
    document.getElementById('chip-store-dist').textContent =
        `${(data.tmap.distance_km * 0.4).toFixed(1)}km`;
    document.getElementById('chip-dest-dist').textContent  =
        `${data.actual.distance_km.toFixed(1)}km · ${data.actual.minutes.toFixed(0)}분`;

    // 세부 패널 내용 채우기
    document.getElementById('d-tmap-min').textContent  = `${data.tmap.minutes.toFixed(0)}분`;
    document.getElementById('d-tmap-dist').textContent = `${data.tmap.distance_km.toFixed(1)}km`;
    document.getElementById('d-real-min').textContent  = `${data.actual.minutes.toFixed(0)}분`;
    document.getElementById('d-real-dist').textContent =
        `협로 도보 ${data.actual.walk_minutes.toFixed(0)}분 포함`;

    const wl = document.getElementById('warn-list');
    wl.innerHTML = (data.terrain.warnings || []).map(w =>
        `<div class="warn-row">⚠️ ${w}</div>`
    ).join('');

    // 배달료
    const sf = data.safe_fare;
    document.getElementById('fare-safe').textContent  = `${sf.total.toLocaleString()}원`;
    document.getElementById('fare-plat').textContent  = `앱 제시 ${data.tmap.fare.toLocaleString()}원`;
    document.getElementById('btn-fare').textContent   = `${sf.total.toLocaleString()}원`;

    // 패널 닫기
    openChip = null;
    setDetailPanel(null);

    // 오버레이 표시
    document.getElementById('call-overlay').classList.add('visible');
    setTimeout(() => document.getElementById('call-mini-card').classList.add('show'), 50);

    startTimer();
}

function startTimer() {
    clearInterval(timerHandle);
    renderTimer(timerSec);
    timerHandle = setInterval(() => {
        timerSec--;
        renderTimer(timerSec);
        if (timerSec <= 0) { clearInterval(timerHandle); autoDecline(); }
    }, 1000);
}

function renderTimer(s) {
    document.getElementById('t-num').textContent = s;
    const pct = s / 30;
    const circ = 2 * Math.PI * 18;
    document.getElementById('t-arc').style.strokeDasharray = `${circ * pct} ${circ}`;
    document.getElementById('t-arc').style.stroke =
        s <= 10 ? '#ff3b30' : s <= 20 ? '#ffcc00' : '#00C896';
}

function toggleDetail(which) {
    // 같은 칩 다시 누르면 닫기
    if (openChip === which) {
        openChip = null;
        setDetailPanel(null);
        document.getElementById('chip-store').classList.remove('selected');
        document.getElementById('chip-dest').classList.remove('selected');
    } else {
        openChip = which;
        setDetailPanel(which);
        document.getElementById('chip-store').classList.toggle('selected', which === 'store');
        document.getElementById('chip-dest').classList.toggle('selected', which === 'dest');
    }
}

function setDetailPanel(which) {
    const panel = document.getElementById('detail-panel');
    if (!which) {
        panel.classList.remove('open');
        panel.classList.add('closed');
    } else {
        panel.classList.add('open');
        panel.classList.remove('closed');
        // dest 탭이면 지형 경고 포함, store 탭이면 경로 정보만
        document.getElementById('warn-list').style.display =
            which === 'dest' ? 'block' : 'none';
    }
}

function acceptCall() {
    clearInterval(timerHandle);
    closeCallPopup();
    startNavigation('to_store');
}

function rejectCall() {
    clearInterval(timerHandle);
    closeCallPopup();
    showToast('배차 거절됨');
}

function autoDecline() {
    closeCallPopup();
    showToast('⏱ 시간 초과 — 자동 거절');
}

function closeCallPopup() {
    clearCallOnMap();
    const card = document.getElementById('call-mini-card');
    card.classList.remove('show');
    setTimeout(() => document.getElementById('call-overlay').classList.remove('visible'), 350);
    openChip = null;
}