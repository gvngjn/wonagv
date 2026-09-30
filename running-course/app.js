/* 런루프 화면 로직: 지도, 출발지 지정, 설정 저장, 데이터 받기, 결과 표시 */
(function () {
  'use strict';

  const STORE_KEY = 'runloop.v1';
  const OVERPASS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
    'https://maps.mail.ru/osm/tools/overpass/api/interpreter',
  ];
  const COLORS = ['#ff5a36', '#2f80ed', '#8e44ad'];
  const PREF_ITEMS = [
    { key: 'park', name: '공원·녹지', desc: '공원, 숲, 정원 안의 길' },
    { key: 'water', name: '강·하천변', desc: '한강, 하천 산책로 주변' },
    { key: 'footpath', name: '보행자 전용길', desc: '산책로, 보행로, 자전거길' },
    { key: 'bigRoad', name: '큰 도로 옆', desc: '차가 많은 간선도로' },
    { key: 'stairs', name: '계단', desc: '' },
    { key: 'unpaved', name: '비포장길', desc: '흙길, 등산로' },
    { key: 'lit', name: '가로등 있는 길', desc: '밤에 달릴 때 (데이터가 적을 수 있음)' },
    { key: 'repeat', name: '같은 길 두 번', desc: '왕복 구간' },
  ];
  const PACE_DEFAULT = { run: '6:00', walk: '12:00' };

  // ---------------------------------------------------------------------------
  // 상태 & 저장
  // ---------------------------------------------------------------------------
  const state = Object.assign({
    home: null, // {lat, lon, label}
    mode: 'distance',
    distanceKm: 5,
    timeMin: 30,
    activity: 'run',
    pace: '6:00',
    direction: '',
    prefs: Object.assign({}, Course.DEFAULT_PREFS),
  }, load());
  state.prefs = Object.assign({}, Course.DEFAULT_PREFS, state.prefs);

  function load() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; } catch (e) { return {}; }
  }
  function save() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (e) { /* 저장 불가(사생활 보호 모드 등) */ }
  }

  const $ = (id) => document.getElementById(id);

  // ---------------------------------------------------------------------------
  // 지도
  // ---------------------------------------------------------------------------
  const map = L.map('map', { zoomControl: true }).setView(state.home ? [state.home.lat, state.home.lon] : [37.5665, 126.978], state.home ? 15 : 12);
  // 배경 지도: API 키가 필요 없는 OpenStreetMap 기본 지도 + 위성 사진(Esri) 선택
  const baseMaps = {
    '기본 지도': L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> 기여자',
    }),
    '위성 사진': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 19,
      attribution: '© Esri, Maxar, Earthstar Geographics',
    }),
  };
  baseMaps['기본 지도'].addTo(map);
  L.control.layers(baseMaps, null, { position: 'topright' }).addTo(map);

  const courseLayer = L.layerGroup().addTo(map);
  let homeMarker = null;

  function setHome(lat, lon, label, fly) {
    state.home = { lat, lon, label: label || `${lat.toFixed(5)}, ${lon.toFixed(5)}` };
    save();
    if (!homeMarker) {
      homeMarker = L.marker([lat, lon], {
        draggable: true,
        icon: L.divIcon({ className: 'home-mark', html: '🏠', iconSize: [26, 26], iconAnchor: [13, 13] }),
        zIndexOffset: 1000,
      }).addTo(map);
      homeMarker.on('dragend', () => {
        const p = homeMarker.getLatLng();
        setHome(p.lat, p.lng, null, false);
        reverseGeocode(p.lat, p.lng);
      });
    } else {
      homeMarker.setLatLng([lat, lon]);
    }
    const el = $('homeLabel');
    el.textContent = '🏠 ' + state.home.label;
    el.classList.add('set');
    if (fly) map.setView([lat, lon], Math.max(map.getZoom(), 15));
    clearResults();
  }

  map.on('click', (ev) => {
    setHome(ev.latlng.lat, ev.latlng.lng, null, false);
    reverseGeocode(ev.latlng.lat, ev.latlng.lng);
  });

  // ---------------------------------------------------------------------------
  // 주소 검색 / 현재 위치
  // ---------------------------------------------------------------------------
  $('searchForm').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const q = $('searchInput').value.trim();
    const list = $('searchResults');
    if (!q) return;
    list.hidden = false;
    list.innerHTML = '<li>검색 중…</li>';
    try {
      const url = 'https://nominatim.openstreetmap.org/search?format=jsonv2&limit=6&accept-language=ko&q=' + encodeURIComponent(q);
      const res = await fetch(url);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const items = await res.json();
      list.innerHTML = '';
      if (!items.length) { list.innerHTML = '<li>결과가 없어요. 다른 이름으로 검색해 보세요.</li>'; return; }
      for (const it of items) {
        const li = document.createElement('li');
        li.textContent = it.display_name;
        li.addEventListener('click', () => {
          setHome(Number(it.lat), Number(it.lon), shortName(it.display_name), true);
          list.hidden = true;
        });
        list.appendChild(li);
      }
    } catch (e) {
      list.innerHTML = '<li>검색에 실패했어요. 잠시 후 다시 시도해 주세요.</li>';
    }
  });

  function shortName(display) {
    return display.split(',').slice(0, 3).map((s) => s.trim()).join(', ');
  }

  async function reverseGeocode(lat, lon) {
    try {
      const url = `https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=17&accept-language=ko&lat=${lat}&lon=${lon}`;
      const res = await fetch(url);
      if (!res.ok) return;
      const j = await res.json();
      if (j && j.display_name && state.home && state.home.lat === lat && state.home.lon === lon) {
        state.home.label = shortName(j.display_name);
        $('homeLabel').textContent = '🏠 ' + state.home.label;
        save();
      }
    } catch (e) { /* 이름이 없어도 좌표로 동작 */ }
  }

  $('locateBtn').addEventListener('click', () => {
    if (!navigator.geolocation) { showStatus('이 브라우저는 위치 기능을 지원하지 않아요.', true); return; }
    showStatus('현재 위치를 찾는 중…');
    navigator.geolocation.getCurrentPosition((pos) => {
      hideStatus();
      setHome(pos.coords.latitude, pos.coords.longitude, null, true);
      reverseGeocode(pos.coords.latitude, pos.coords.longitude);
    }, (err) => {
      showStatus('위치를 가져오지 못했어요: ' + (err.code === 1 ? '위치 권한을 허용해 주세요.' : err.message), true);
    }, { enableHighAccuracy: true, timeout: 15000 });
  });

  // ---------------------------------------------------------------------------
  // 목표 / 페이스 / 방향
  // ---------------------------------------------------------------------------
  function paceSec() {
    const m = /^(\d{1,2}):(\d{2})$/.exec(state.pace.trim());
    if (!m) return state.activity === 'walk' ? 720 : 360;
    return Number(m[1]) * 60 + Number(m[2]);
  }
  function targetMeters() {
    if (state.mode === 'distance') return state.distanceKm * 1000;
    return (state.timeMin * 60 / paceSec()) * 1000;
  }

  function renderTarget() {
    document.querySelectorAll('#targetMode button').forEach((b) => b.classList.toggle('on', b.dataset.v === state.mode));
    const input = $('targetInput');
    const chips = $('quickChips');
    chips.innerHTML = '';
    let values;
    if (state.mode === 'distance') {
      input.value = state.distanceKm;
      input.step = '0.1'; input.min = '0.5'; input.max = '42.2';
      $('targetUnit').textContent = 'km';
      values = [3, 5, 10, 21.1];
    } else {
      input.value = state.timeMin;
      input.step = '5'; input.min = '5'; input.max = '300';
      $('targetUnit').textContent = `분 (≈ ${(targetMeters() / 1000).toFixed(1)}km)`;
      values = [20, 30, 45, 60];
    }
    for (const v of values) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'chip';
      b.textContent = state.mode === 'distance' ? `${v}km` : `${v}분`;
      b.addEventListener('click', () => {
        if (state.mode === 'distance') state.distanceKm = v; else state.timeMin = v;
        save(); renderTarget();
      });
      chips.appendChild(b);
    }
  }

  $('targetMode').addEventListener('click', (ev) => {
    const v = ev.target.dataset && ev.target.dataset.v;
    if (!v) return;
    state.mode = v; save(); renderTarget();
  });
  $('targetInput').addEventListener('input', () => {
    const v = parseFloat($('targetInput').value);
    if (!(v > 0)) return;
    if (state.mode === 'distance') state.distanceKm = v; else state.timeMin = v;
    if (state.mode === 'time') $('targetUnit').textContent = `분 (≈ ${(targetMeters() / 1000).toFixed(1)}km)`;
    save();
  });

  $('activity').value = state.activity;
  $('pace').value = state.pace;
  $('direction').value = state.direction;
  $('activity').addEventListener('change', () => {
    state.activity = $('activity').value;
    state.pace = PACE_DEFAULT[state.activity];
    $('pace').value = state.pace;
    save(); renderTarget();
  });
  $('pace').addEventListener('change', () => { state.pace = $('pace').value; save(); renderTarget(); });
  $('direction').addEventListener('change', () => { state.direction = $('direction').value; save(); });

  // ---------------------------------------------------------------------------
  // 선호 설정
  // ---------------------------------------------------------------------------
  function renderPrefs() {
    const box = $('prefs');
    box.innerHTML = '';
    for (const item of PREF_ITEMS) {
      const row = document.createElement('div');
      row.className = 'pref';
      const labels = item.key === 'repeat'
        ? [['avoid', '피하기'], ['normal', '괜찮음']]
        : [['avoid', '피하기'], ['normal', '상관없음'], ['prefer', '선호']];
      row.innerHTML = `<div class="name">${item.name}${item.desc ? `<small>${item.desc}</small>` : ''}</div>`;
      const seg = document.createElement('div');
      seg.className = 'seg';
      seg.setAttribute('role', 'radiogroup');
      seg.setAttribute('aria-label', item.name);
      for (const [v, text] of labels) {
        const b = document.createElement('button');
        b.type = 'button';
        b.dataset.v = v;
        b.textContent = text;
        b.setAttribute('role', 'radio');
        const on = state.prefs[item.key] === v;
        b.classList.toggle('on', on);
        b.setAttribute('aria-checked', String(on));
        b.addEventListener('click', () => { state.prefs[item.key] = v; save(); renderPrefs(); });
        seg.appendChild(b);
      }
      row.appendChild(seg);
      box.appendChild(row);
    }
  }

  // ---------------------------------------------------------------------------
  // 데이터 받기 (같은 동네·반경이면 다시 받지 않음)
  // ---------------------------------------------------------------------------
  let cache = null; // {lat, lon, radius, graph}

  async function fetchOverpass(query) {
    let lastErr;
    for (const url of OVERPASS) {
      try {
        const res = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: 'data=' + encodeURIComponent(query),
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return await res.json();
      } catch (e) {
        lastErr = e;
      }
    }
    throw lastErr || new Error('길 정보를 받지 못했어요');
  }

  async function getGraph(lat, lon, radius) {
    if (cache && cache.radius >= radius &&
        Course.haversine(lat, lon, cache.lat, cache.lon) + radius <= cache.radius + 50) {
      return cache.graph;
    }
    showStatus(`주변 ${(radius / 1000).toFixed(1)}km 길 정보를 받는 중… (처음엔 10~30초 걸릴 수 있어요)`);
    setProgress(0.05);
    const osm = await fetchOverpass(Course.buildOverpassQuery(lat, lon, radius));
    showStatus('길 지도를 만드는 중…');
    setProgress(0.15);
    await new Promise((r) => setTimeout(r, 20));
    const graph = Course.buildGraph(osm);
    if (!graph.n) throw new Error('이 근처에서 걸을 수 있는 길을 찾지 못했어요.');
    cache = { lat, lon, radius, graph };
    return graph;
  }

  // ---------------------------------------------------------------------------
  // 코스 만들기
  // ---------------------------------------------------------------------------
  let courses = [];
  let selected = 0;
  let busy = false;

  $('generateBtn').addEventListener('click', () => generate());

  async function generate() {
    if (busy) return;
    if (!state.home) { showStatus('먼저 출발지(집)를 지정해 주세요.', true); return; }
    const target = targetMeters();
    if (!(target >= 300) || target > 60000) { showStatus('목표 거리는 0.3km ~ 60km 사이로 정해 주세요.', true); return; }
    busy = true;
    $('generateBtn').disabled = true;
    $('generateBtn').textContent = '만드는 중…';
    clearResults();
    try {
      const { lat, lon } = state.home;
      const graph = await getGraph(lat, lon, Course.fetchRadiusFor(target));
      const snap = Course.nearestNode(graph, lat, lon);
      if (snap.node < 0 || snap.dist > 400) throw new Error('출발지 근처에 연결된 길이 없어요. 출발지를 길 가까이로 옮겨 주세요.');
      showStatus('코스를 계산하는 중…');
      courses = await Course.generateLoops(graph, snap.node, {
        target,
        prefs: state.prefs,
        direction: state.direction === '' ? null : Number(state.direction),
        alternatives: 3,
        onProgress: (p) => setProgress(0.2 + p * 0.8),
      });
      if (!courses.length) throw new Error('코스를 만들지 못했어요. 거리나 출발지를 바꿔 보세요.');
      hideStatus();
      selected = 0;
      renderResults();
    } catch (e) {
      console.error(e);
      showStatus('⚠️ ' + (e.message && !/^HTTP|Failed to fetch|NetworkError/.test(e.message) ? e.message : '인터넷 연결을 확인하거나 잠시 후 다시 시도해 주세요. (' + e.message + ')'), true);
    } finally {
      busy = false;
      $('generateBtn').disabled = false;
      $('generateBtn').textContent = courses.length ? '다른 코스 만들기' : '코스 만들기';
    }
  }

  function fmtTime(sec) {
    const m = Math.round(sec / 60);
    return m >= 60 ? `${Math.floor(m / 60)}시간 ${m % 60}분` : `${m}분`;
  }
  const pct = (x) => Math.round(x * 100) + '%';

  function renderResults() {
    const box = $('results');
    box.innerHTML = '';
    courses.forEach((c, i) => {
      const km = c.length / 1000;
      const diff = c.length - c.target;
      const div = document.createElement('div');
      div.className = 'result' + (i === selected ? ' on' : '');
      const mix = [];
      if (c.share.park > 0.01) mix.push(`🌳 공원 <b>${pct(c.share.park)}</b>`);
      if (c.share.water > 0.01) mix.push(`🌊 하천변 <b>${pct(c.share.water)}</b>`);
      if (c.share.foot > 0.01) mix.push(`🚶 보행로 <b>${pct(c.share.foot)}</b>`);
      if (c.share.big > 0.01) mix.push(`🚗 큰 도로 <b>${pct(c.share.big)}</b>`);
      if (c.share.steps > 0.001) mix.push(`🪜 계단 <b>${Math.round(c.share.steps * c.length)}m</b>`);
      if (c.share.unpaved > 0.01) mix.push(`🟫 비포장 <b>${pct(c.share.unpaved)}</b>`);
      if (c.repeatRatio > 0.01) mix.push(`↩️ 같은 길 <b>${pct(c.repeatRatio)}</b>`);
      const streets = c.streets.map((s) => s.name).join(' · ');
      div.innerHTML = `
        <div class="top">
          <span class="swatch" style="background:${COLORS[i % COLORS.length]}"></span>
          <span class="dist">${km.toFixed(2)} km</span>
          <span class="diff">목표 대비 ${diff >= 0 ? '+' : '−'}${Math.abs(Math.round(diff))}m</span>
          <span class="time">약 ${fmtTime(km * paceSec())}</span>
        </div>
        <div class="mix">${mix.join('') ? mix.map((m) => `<span>${m}</span>`).join('') : '<span>일반 도로 위주</span>'}</div>
        ${streets ? `<div class="streets">지나는 길: ${escapeHtml(streets)}</div>` : ''}
        <div class="actions">
          <button type="button" class="btn small" data-act="gpx">GPX 저장</button>
          <button type="button" class="btn small" data-act="reverse">반대 방향으로</button>
        </div>`;
      div.addEventListener('click', (ev) => {
        const act = ev.target.dataset && ev.target.dataset.act;
        if (act === 'gpx') { downloadGPX(c, i); return; }
        if (act === 'reverse') { reverseCourse(c); selected = i; renderResults(); return; }
        selected = i; renderResults();
      });
      box.appendChild(div);
    });
    drawCourses();
  }

  function reverseCourse(c) {
    c.coords.reverse();
    c.clockwise = !c.clockwise;
    const L0 = c.length;
    c.kmMarks = [];
    let acc = 0, next = 1000;
    for (let i = 1; i < c.coords.length; i++) {
      const [a, b] = [c.coords[i - 1], c.coords[i]];
      const d = Course.haversine(a[0], a[1], b[0], b[1]);
      while (acc + d >= next && next <= L0) {
        const t = (next - acc) / d;
        c.kmMarks.push({ km: next / 1000, lat: a[0] + (b[0] - a[0]) * t, lon: a[1] + (b[1] - a[1]) * t });
        next += 1000;
      }
      acc += d;
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  }

  function drawCourses() {
    courseLayer.clearLayers();
    courses.forEach((c, i) => {
      if (i === selected) return;
      L.polyline(c.coords, { color: COLORS[i % COLORS.length], weight: 4, opacity: 0.35 })
        .on('click', () => { selected = i; renderResults(); })
        .addTo(courseLayer);
    });
    const c = courses[selected];
    if (!c) return;
    const color = COLORS[selected % COLORS.length];
    L.polyline(c.coords, { color: '#fff', weight: 9, opacity: 0.9 }).addTo(courseLayer);
    const line = L.polyline(c.coords, { color, weight: 5, opacity: 1 }).addTo(courseLayer);
    // 진행 방향 화살표 (1/8 지점마다)
    const cum = [0];
    for (let i = 1; i < c.coords.length; i++) cum.push(cum[i - 1] + Course.haversine(...c.coords[i - 1], ...c.coords[i]));
    const total = cum[cum.length - 1];
    for (let k = 1; k < 8; k++) {
      const d = (total * k) / 8;
      let i = 1;
      while (i < cum.length - 1 && cum[i] < d) i++;
      const a = c.coords[i - 1], b = c.coords[i];
      const br = Course.bearing(a[0], a[1], b[0], b[1]);
      const t = cum[i] > cum[i - 1] ? (d - cum[i - 1]) / (cum[i] - cum[i - 1]) : 0;
      L.marker([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], {
        interactive: false,
        icon: L.divIcon({ className: '', html: `<div class="arrow-mark" style="transform:rotate(${br - 90}deg)">➤</div>`, iconSize: [16, 16], iconAnchor: [8, 8] }),
      }).addTo(courseLayer);
    }
    for (const m of c.kmMarks) {
      L.marker([m.lat, m.lon], {
        icon: L.divIcon({ className: '', html: `<div class="km-mark" style="border-color:${color}">${m.km}</div>`, iconSize: [22, 22], iconAnchor: [11, 11] }),
        title: `${m.km}km 지점`,
      }).addTo(courseLayer);
    }
    map.fitBounds(line.getBounds(), { padding: [30, 30] });
  }

  function downloadGPX(c, i) {
    const name = `런루프 ${(c.length / 1000).toFixed(2)}km 코스 ${i + 1}`;
    const blob = new Blob([Course.toGPX(c, name)], { type: 'application/gpx+xml' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `runloop-${(c.length / 1000).toFixed(1)}km-${i + 1}.gpx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  function clearResults() {
    courses = [];
    $('results').innerHTML = '';
    courseLayer.clearLayers();
    $('generateBtn').textContent = '코스 만들기';
  }

  // ---------------------------------------------------------------------------
  // 상태 표시
  // ---------------------------------------------------------------------------
  function showStatus(text, isError) {
    const s = $('status');
    s.hidden = false;
    s.classList.toggle('error', !!isError);
    $('statusText').textContent = text;
    s.querySelector('.bar').style.display = isError ? 'none' : '';
  }
  function hideStatus() { $('status').hidden = true; setProgress(0); }
  function setProgress(p) { $('progress').style.width = Math.round(p * 100) + '%'; }

  // ---------------------------------------------------------------------------
  renderTarget();
  renderPrefs();
  if (state.home) setHome(state.home.lat, state.home.lon, state.home.label, false);
})();
