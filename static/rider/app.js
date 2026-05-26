// ── 앱 라우터 ─────────────────────────────────────────────────
function showScreen(name) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    const t = document.getElementById('screen-' + name);
    if (t) t.classList.add('active');
}
function goStats() {
    loadStats();
    showScreen('stats');
}

// 상태바 시계
function updateClock() {
    const d = new Date();
    document.getElementById('sb-time').textContent =
        `${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`;
}
setInterval(updateClock, 10000);
updateClock();

// 토스트
function showToast(msg, ms = 2200) {
    let el = document.getElementById('_toast');
    if (!el) { el = document.createElement('div'); el.id = '_toast'; el.className = 'toast'; document.body.appendChild(el); }
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.remove('show'), ms);
}

window.addEventListener('DOMContentLoaded', () => {
    // TMap SDK는 index.html 맨 아래서 동적 로드됨
    // → SDK onload 콜백에서 initTmap() 호출됨
    // 혹시 이미 로드된 경우 대비
    if (typeof Tmapv2 !== 'undefined') initTmap();
    refreshEarnings();
});

function refreshEarnings() {
    const h = JSON.parse(localStorage.getItem('rh') || '[]');
    const today = new Date().toISOString().slice(0,10);
    const t = h.filter(r => r.ts && r.ts.startsWith(today)).reduce((s,r) => s+(r.fare||0), 0);
    document.getElementById('today-earn').textContent = t > 0 ? `오늘 ${t.toLocaleString()}원` : '오늘 0원';
}