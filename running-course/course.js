/*
 * 러닝 코스 생성 엔진 (지도·UI와 무관한 순수 계산 부분)
 *
 * 1) OpenStreetMap(Overpass) 데이터로 보행 가능한 길 그래프를 만든다.
 * 2) 길마다 특징(공원, 하천변, 보행로, 큰 도로, 계단, 비포장, 가로등)을 붙인다.
 * 3) 선호 설정에 따라 길마다 "비용 배수"를 매긴다. (선호 < 1 < 회피)
 * 4) 집을 지나는 원 위에 경유지를 찍고 A* 로 이어 순환 코스를 만든 뒤,
 *    원의 반지름을 조절해 목표 거리에 맞춘다.
 *
 * 브라우저에서는 window.Course, Node(테스트)에서는 module.exports 로 쓴다.
 */
(function (root) {
  'use strict';

  const R_EARTH = 6371008.8;
  const DEG = Math.PI / 180;

  function haversine(lat1, lon1, lat2, lon2) {
    const dLat = (lat2 - lat1) * DEG;
    const dLon = (lon2 - lon1) * DEG;
    const a = Math.sin(dLat / 2) ** 2 +
      Math.cos(lat1 * DEG) * Math.cos(lat2 * DEG) * Math.sin(dLon / 2) ** 2;
    return 2 * R_EARTH * Math.asin(Math.min(1, Math.sqrt(a)));
  }

  /** 한 점에서 방위각(도, 북=0 시계방향)으로 d 미터 이동한 좌표 */
  function destination(lat, lon, bearingDeg, d) {
    const b = bearingDeg * DEG;
    const dr = d / R_EARTH;
    const la1 = lat * DEG, lo1 = lon * DEG;
    const la2 = Math.asin(Math.sin(la1) * Math.cos(dr) + Math.cos(la1) * Math.sin(dr) * Math.cos(b));
    const lo2 = lo1 + Math.atan2(Math.sin(b) * Math.sin(dr) * Math.cos(la1),
      Math.cos(dr) - Math.sin(la1) * Math.sin(la2));
    return [la2 / DEG, ((lo2 / DEG + 540) % 360) - 180];
  }

  function bearing(lat1, lon1, lat2, lon2) {
    const la1 = lat1 * DEG, la2 = lat2 * DEG, dLon = (lon2 - lon1) * DEG;
    const y = Math.sin(dLon) * Math.cos(la2);
    const x = Math.cos(la1) * Math.sin(la2) - Math.sin(la1) * Math.cos(la2) * Math.cos(dLon);
    return (Math.atan2(y, x) / DEG + 360) % 360;
  }

  // ---------------------------------------------------------------------------
  // Overpass 쿼리
  // ---------------------------------------------------------------------------

  /** 목표 거리(m)로 순환 코스를 만들 때 필요한 데이터 반경(m) */
  function fetchRadiusFor(targetM) {
    return Math.round(Math.min(15000, targetM / 3 + 400));
  }

  function buildOverpassQuery(lat, lon, radiusM) {
    const a = `(around:${radiusM},${lat.toFixed(6)},${lon.toFixed(6)})`;
    return `[out:json][timeout:90];
way[highway][highway!~"^(motorway|motorway_link|construction|proposed|planned|abandoned|raceway|bus_guideway|platform|elevator|corridor|via_ferrata|escape|busway)$"]${a}->.roads;
.roads out body qt;
.roads >;
out skel qt;
(
  way[leisure~"^(park|garden|nature_reserve|recreation_ground)$"]${a};
  relation[leisure~"^(park|garden|nature_reserve|recreation_ground)$"]${a};
  way[landuse~"^(forest|recreation_ground|village_green)$"]${a};
  relation[landuse=forest]${a};
);
out geom qt;
(
  way[waterway~"^(river|stream|canal)$"]${a};
  way[natural=water]${a};
  relation[natural=water]${a};
  way[natural=coastline]${a};
);
out geom qt;`;
  }

  // ---------------------------------------------------------------------------
  // 길 분류
  // ---------------------------------------------------------------------------

  const KIND = { MINOR: 0, FOOT: 1, BIG: 2, MID: 3, STEPS: 4, SIDEWALK: 5 };
  const F_PARK = 1, F_WATER = 2, F_UNPAVED = 4, F_LIT = 8;

  const BIG_ROADS = new Set(['trunk', 'trunk_link', 'primary', 'primary_link', 'secondary', 'secondary_link']);
  const MID_ROADS = new Set(['tertiary', 'tertiary_link']);
  const FOOT_WAYS = new Set(['footway', 'path', 'pedestrian', 'track', 'cycleway', 'bridleway']);
  const UNPAVED_RE = /^(unpaved|dirt|earth|ground|gravel|fine_gravel|sand|mud|grass|compacted|woodchips|pebblestone|rock|grass_paver)$/;
  const FOOT_OK = new Set(['yes', 'designated', 'permissive']);

  /** 걸을 수 없는 길이면 null, 아니면 {kind, flags} */
  function classifyWay(tags) {
    const hw = tags.highway;
    if (!hw) return null;
    if (tags.area === 'yes' && hw !== 'pedestrian' && hw !== 'footway') return null;
    const foot = tags.foot;
    if (foot === 'no' || foot === 'private' || foot === 'use_sidepath') return null;
    if ((tags.access === 'no' || tags.access === 'private') && !FOOT_OK.has(foot)) return null;
    if (tags.motorroad === 'yes') return null;

    let kind;
    if (hw === 'steps') kind = KIND.STEPS;
    else if (BIG_ROADS.has(hw)) kind = KIND.BIG;
    else if (MID_ROADS.has(hw)) kind = KIND.MID;
    else if (hw === 'footway' && (tags.footway === 'sidewalk' || tags.footway === 'crossing')) kind = KIND.SIDEWALK;
    else if (FOOT_WAYS.has(hw) || hw === 'living_street') kind = KIND.FOOT;
    else kind = KIND.MINOR;

    let flags = 0;
    const surface = tags.surface || '';
    // 표면 정보가 없는 track/path(주로 등산로·흙길)는 비포장으로 본다
    if (surface ? UNPAVED_RE.test(surface) : (hw === 'track' || hw === 'path')) flags |= F_UNPAVED;
    if (tags.lit === 'yes' || tags.lit === '24/7' || tags.lit === 'automatic') flags |= F_LIT;
    return { kind, flags };
  }

  // ---------------------------------------------------------------------------
  // 공원 폴리곤 / 하천 근접 판정
  // ---------------------------------------------------------------------------

  /** 끝점이 맞닿은 선분들을 이어 닫힌 고리들로 만든다 (멀티폴리곤 relation 용) */
  function assembleRings(lines) {
    const rings = [];
    const pool = lines.filter((l) => l.length >= 2).map((l) => l.slice());
    const same = (a, b) => Math.abs(a[0] - b[0]) < 1e-7 && Math.abs(a[1] - b[1]) < 1e-7;
    while (pool.length) {
      let ring = pool.pop();
      let grown = true;
      while (!same(ring[0], ring[ring.length - 1]) && grown) {
        grown = false;
        for (let i = 0; i < pool.length; i++) {
          const l = pool[i];
          const end = ring[ring.length - 1];
          if (same(end, l[0])) ring = ring.concat(l.slice(1));
          else if (same(end, l[l.length - 1])) ring = ring.concat(l.slice(0, -1).reverse());
          else continue;
          pool.splice(i, 1);
          grown = true;
          break;
        }
      }
      if (ring.length >= 4 && same(ring[0], ring[ring.length - 1])) rings.push(ring);
    }
    return rings;
  }

  function makePolygon(ring) {
    let minLat = Infinity, maxLat = -Infinity, minLon = Infinity, maxLon = -Infinity;
    for (const [la, lo] of ring) {
      if (la < minLat) minLat = la; if (la > maxLat) maxLat = la;
      if (lo < minLon) minLon = lo; if (lo > maxLon) maxLon = lo;
    }
    return { ring, minLat, maxLat, minLon, maxLon };
  }

  function pointInRing(lat, lon, ring) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [yi, xi] = ring[i], [yj, xj] = ring[j];
      if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }

  /** 격자에 폴리곤을 넣어 두고 점이 어느 폴리곤 안에 있는지 빠르게 확인 */
  function PolygonIndex(polys, cell) {
    this.cell = cell;
    this.map = new Map();
    polys.forEach((p) => {
      const i0 = Math.floor(p.minLat / cell), i1 = Math.floor(p.maxLat / cell);
      const j0 = Math.floor(p.minLon / cell), j1 = Math.floor(p.maxLon / cell);
      if ((i1 - i0 + 1) * (j1 - j0 + 1) > 40000) return; // 비정상적으로 큰 영역은 무시
      for (let i = i0; i <= i1; i++) {
        for (let j = j0; j <= j1; j++) {
          const k = i * 100000 + j;
          let arr = this.map.get(k);
          if (!arr) this.map.set(k, (arr = []));
          arr.push(p);
        }
      }
    });
  }
  PolygonIndex.prototype.contains = function (lat, lon) {
    const arr = this.map.get(Math.floor(lat / this.cell) * 100000 + Math.floor(lon / this.cell));
    if (!arr) return false;
    for (const p of arr) {
      if (lat < p.minLat || lat > p.maxLat || lon < p.minLon || lon > p.maxLon) continue;
      if (pointInRing(lat, lon, p.ring)) return true;
    }
    return false;
  };

  /** 물가 선을 촘촘한 점으로 바꿔 격자에 넣고, 주어진 점이 물가에서 radius 이내인지 확인 */
  function NearIndex(lines, radiusM) {
    this.r = radiusM;
    this.cell = 0.002; // 약 200m
    this.map = new Map();
    const step = Math.max(10, radiusM / 3);
    for (const line of lines) {
      for (let i = 0; i < line.length; i++) {
        const [la, lo] = line[i];
        this._add(la, lo);
        if (i + 1 < line.length) {
          const [la2, lo2] = line[i + 1];
          const d = haversine(la, lo, la2, lo2);
          const n = Math.floor(d / step);
          for (let s = 1; s <= n; s++) {
            const t = s / (n + 1);
            this._add(la + (la2 - la) * t, lo + (lo2 - lo) * t);
          }
        }
      }
    }
  }
  NearIndex.prototype._add = function (la, lo) {
    const k = Math.floor(la / this.cell) * 100000 + Math.floor(lo / this.cell);
    let arr = this.map.get(k);
    if (!arr) this.map.set(k, (arr = []));
    arr.push(la, lo);
  };
  NearIndex.prototype.near = function (la, lo) {
    const ci = Math.floor(la / this.cell), cj = Math.floor(lo / this.cell);
    for (let i = ci - 1; i <= ci + 1; i++) {
      for (let j = cj - 1; j <= cj + 1; j++) {
        const arr = this.map.get(i * 100000 + j);
        if (!arr) continue;
        for (let t = 0; t < arr.length; t += 2) {
          if (haversine(la, lo, arr[t], arr[t + 1]) <= this.r) return true;
        }
      }
    }
    return false;
  };

  function geomOf(el) {
    return (el.geometry || []).filter(Boolean).map((p) => [p.lat, p.lon]);
  }

  // ---------------------------------------------------------------------------
  // 그래프
  // ---------------------------------------------------------------------------

  /**
   * Overpass JSON → 그래프
   * 노드는 인덱스(0..n-1), 간선은 양방향 하나로 저장하고 인접 리스트(CSR)를 만든다.
   */
  function buildGraph(osm, options) {
    const waterRadius = (options && options.waterRadius) || 120;
    const elements = osm.elements || [];
    const coord = new Map();
    const roadWays = [];
    const parkPolys = [];
    const waterLines = [];

    for (const el of elements) {
      if (el.type === 'node') {
        if (el.lat != null) coord.set(el.id, [el.lat, el.lon]);
        continue;
      }
      const tags = el.tags || {};
      const hasGeom = el.geometry || el.members;
      if (hasGeom) {
        const isPark = /^(park|garden|nature_reserve|recreation_ground)$/.test(tags.leisure || '') ||
          /^(forest|recreation_ground|village_green)$/.test(tags.landuse || '');
        const isWater = !!tags.waterway || tags.natural === 'water' || tags.natural === 'coastline';
        let lines;
        if (el.type === 'way') lines = [geomOf(el)];
        else lines = (el.members || []).filter((m) => m.type === 'way' && m.geometry && m.role !== 'inner').map(geomOf);
        if (isPark) {
          for (const ring of assembleRings(lines)) parkPolys.push(makePolygon(ring));
        }
        if (isWater) for (const l of lines) waterLines.push(l);
        continue;
      }
      if (el.type === 'way' && tags.highway && el.nodes) {
        const c = classifyWay(tags);
        if (c) roadWays.push({ id: el.id, nodes: el.nodes, tags, kind: c.kind, flags: c.flags });
      }
    }

    const parkIdx = new PolygonIndex(parkPolys, 0.005);
    const waterIdx = new NearIndex(waterLines, waterRadius);

    // 노드 번호 매기기
    const idx = new Map();
    const lat = [], lon = [];
    const nodeIndex = (id) => {
      let i = idx.get(id);
      if (i === undefined) {
        const c = coord.get(id);
        if (!c) return -1;
        i = lat.length;
        idx.set(id, i);
        lat.push(c[0]); lon.push(c[1]);
      }
      return i;
    };

    const eFrom = [], eTo = [], eLen = [], eKind = [], eFlags = [], eWay = [];
    const wayNames = [];
    const seen = new Set();
    for (const w of roadWays) {
      const wi = wayNames.length;
      wayNames.push(w.tags.name || '');
      for (let k = 0; k + 1 < w.nodes.length; k++) {
        const a = nodeIndex(w.nodes[k]);
        const b = nodeIndex(w.nodes[k + 1]);
        if (a < 0 || b < 0 || a === b) continue;
        const key = a < b ? a * 4294967296 + b : b * 4294967296 + a;
        if (seen.has(key)) continue; // 같은 구간이 두 번 그려진 경우
        seen.add(key);
        const len = haversine(lat[a], lon[a], lat[b], lon[b]);
        const mLat = (lat[a] + lat[b]) / 2, mLon = (lon[a] + lon[b]) / 2;
        let flags = w.flags;
        if (parkIdx.contains(mLat, mLon)) flags |= F_PARK;
        if (waterIdx.near(mLat, mLon)) flags |= F_WATER;
        eFrom.push(a); eTo.push(b); eLen.push(len);
        eKind.push(w.kind); eFlags.push(flags); eWay.push(wi);
      }
    }

    const n = lat.length, m = eFrom.length;
    const deg = new Int32Array(n + 1);
    for (let e = 0; e < m; e++) { deg[eFrom[e] + 1]++; deg[eTo[e] + 1]++; }
    for (let i = 0; i < n; i++) deg[i + 1] += deg[i];
    const adjNode = new Int32Array(2 * m), adjEdge = new Int32Array(2 * m);
    const fill = deg.slice(0, n);
    for (let e = 0; e < m; e++) {
      const a = eFrom[e], b = eTo[e];
      adjNode[fill[a]] = b; adjEdge[fill[a]++] = e;
      adjNode[fill[b]] = a; adjEdge[fill[b]++] = e;
    }

    const g = {
      n, m,
      lat: Float64Array.from(lat), lon: Float64Array.from(lon),
      eFrom: Int32Array.from(eFrom), eTo: Int32Array.from(eTo),
      eLen: Float64Array.from(eLen), eKind: Uint8Array.from(eKind),
      eFlags: Uint8Array.from(eFlags), eWay: Int32Array.from(eWay),
      wayNames, adjStart: deg, adjNode, adjEdge,
      parkCount: parkPolys.length, waterCount: waterLines.length,
    };
    computeComponents(g);
    buildNodeGrid(g);
    return g;
  }

  function computeComponents(g) {
    const comp = new Int32Array(g.n).fill(-1);
    const sizes = [];
    const stack = new Int32Array(g.n);
    for (let s = 0; s < g.n; s++) {
      if (comp[s] >= 0) continue;
      const c = sizes.length;
      let top = 0, size = 0;
      stack[top++] = s; comp[s] = c;
      while (top) {
        const u = stack[--top]; size++;
        for (let k = g.adjStart[u]; k < g.adjStart[u + 1]; k++) {
          const v = g.adjNode[k];
          if (comp[v] < 0) { comp[v] = c; stack[top++] = v; }
        }
      }
      sizes.push(size);
    }
    let main = 0;
    for (let c = 1; c < sizes.length; c++) if (sizes[c] > sizes[main]) main = c;
    g.comp = comp;
    g.mainComp = main;
    g.compSizes = sizes;
  }

  function buildNodeGrid(g) {
    const cell = 0.002;
    const map = new Map();
    for (let i = 0; i < g.n; i++) {
      if (g.comp[i] !== g.mainComp) continue;
      const k = Math.floor(g.lat[i] / cell) * 100000 + Math.floor(g.lon[i] / cell);
      let arr = map.get(k);
      if (!arr) map.set(k, (arr = []));
      arr.push(i);
    }
    g.grid = { cell, map };
  }

  /** 가장 큰 연결 요소 안에서 가장 가까운 노드 {node, dist} */
  function nearestNode(g, la, lo, maxRing) {
    const { cell, map } = g.grid;
    const ci = Math.floor(la / cell), cj = Math.floor(lo / cell);
    let best = -1, bestD = Infinity;
    const ringMeters = cell * 111000 * Math.cos(la * DEG);
    const limit = maxRing || 60;
    for (let r = 0; r <= limit; r++) {
      for (let i = ci - r; i <= ci + r; i++) {
        for (let j = cj - r; j <= cj + r; j++) {
          if (Math.max(Math.abs(i - ci), Math.abs(j - cj)) !== r) continue;
          const arr = map.get(i * 100000 + j);
          if (!arr) continue;
          for (const v of arr) {
            const d = haversine(la, lo, g.lat[v], g.lon[v]);
            if (d < bestD) { bestD = d; best = v; }
          }
        }
      }
      if (best >= 0 && bestD < r * ringMeters) break;
    }
    return { node: best, dist: bestD };
  }

  // ---------------------------------------------------------------------------
  // 선호 설정 → 비용 배수
  // ---------------------------------------------------------------------------

  const DEFAULT_PREFS = {
    park: 'prefer',     // 공원·녹지
    water: 'prefer',    // 강·하천변
    footpath: 'prefer', // 보행자 전용길
    bigRoad: 'avoid',   // 큰 도로
    stairs: 'avoid',    // 계단
    unpaved: 'normal',  // 비포장
    lit: 'normal',      // 가로등
    repeat: 'avoid',    // 같은 길 반복
  };

  // [선호, 보통, 회피] 배수
  const FACTORS = {
    park: [0.6, 1, 2.0],
    water: [0.6, 1, 2.0],
    footpath: [0.7, 1, 1.8],
    bigRoad: [0.8, 1, 2.5],
    stairs: [0.8, 1, 8],
    unpaved: [0.7, 1, 3],
    lit: [0.75, 1, 1.5],
  };
  const LEVEL = { prefer: 0, normal: 1, avoid: 2 };

  function factor(prefs, key) {
    const lv = LEVEL[prefs[key]];
    return FACTORS[key][lv === undefined ? 1 : lv];
  }

  function computeCosts(g, prefs) {
    const p = Object.assign({}, DEFAULT_PREFS, prefs);
    const fPark = factor(p, 'park'), fWater = factor(p, 'water'), fFoot = factor(p, 'footpath');
    const fBig = factor(p, 'bigRoad'), fStairs = factor(p, 'stairs'), fUnpaved = factor(p, 'unpaved'), fLit = factor(p, 'lit');
    const mult = new Float64Array(g.m);
    let minMult = Infinity;
    for (let e = 0; e < g.m; e++) {
      const kind = g.eKind[e], flags = g.eFlags[e];
      let f = 1;
      if (kind === KIND.FOOT) f *= fFoot;
      else if (kind === KIND.BIG) f *= fBig;
      else if (kind === KIND.MID) f *= Math.sqrt(fBig);
      else if (kind === KIND.SIDEWALK) f *= Math.sqrt(fBig) * Math.sqrt(fFoot);
      else if (kind === KIND.STEPS) f *= fStairs;
      if (flags & F_PARK) f *= fPark;
      if (flags & F_WATER) f *= fWater;
      if (flags & F_UNPAVED) f *= fUnpaved;
      if (flags & F_LIT) f *= fLit;
      else if (p.lit === 'prefer') f *= 1.15;
      f = Math.min(30, Math.max(0.2, f));
      mult[e] = f;
      if (f < minMult) minMult = f;
    }
    return { mult, minMult: isFinite(minMult) ? minMult : 1, reusePenalty: p.repeat === 'avoid' ? 6 : p.repeat === 'prefer' ? 0 : 1.5 };
  }

  // ---------------------------------------------------------------------------
  // A* 최단(최저 비용) 경로
  // ---------------------------------------------------------------------------

  function Router(g, costs) {
    this.g = g;
    this.costs = costs;
    this.dist = new Float64Array(g.n);
    this.prevEdge = new Int32Array(g.n);
    this.stamp = new Uint32Array(g.n);
    this.closed = new Uint32Array(g.n);
    this.gen = 0;
    this.heapNode = new Int32Array(1024);
    this.heapKey = new Float64Array(1024);
  }

  /**
   * src → dst 경로의 간선 목록. used[e] 가 0보다 크면 이미 달린 길이므로 비용을 올린다.
   * 반환: 간선 인덱스 배열 (src 쪽부터) / 경로가 없으면 null
   */
  Router.prototype.route = function (src, dst, used) {
    const g = this.g, mult = this.costs.mult, pen = this.costs.reusePenalty;
    const h0 = this.costs.minMult;
    if (src === dst) return [];
    const gen = ++this.gen;
    const dist = this.dist, prev = this.prevEdge, stamp = this.stamp, closed = this.closed;
    const tLat = g.lat[dst], tLon = g.lon[dst];
    const cosLat = Math.cos(tLat * DEG);
    // 빠른 평면 근사 거리 (짧은 거리에서 haversine 과 거의 같고, 약간 작게 잡아 허용 가능성 유지)
    const hk = h0 * 0.995 * 111194.9;
    const heur = (v) => {
      const dy = g.lat[v] - tLat, dx = (g.lon[v] - tLon) * cosLat;
      return hk * Math.sqrt(dy * dy + dx * dx);
    };
    let size = 0;
    let hn = this.heapNode, hkey = this.heapKey;
    const push = (v, key) => {
      if (size >= hn.length) {
        const nn = new Int32Array(hn.length * 2); nn.set(hn); hn = this.heapNode = nn;
        const nk = new Float64Array(hkey.length * 2); nk.set(hkey); hkey = this.heapKey = nk;
      }
      let i = size++;
      while (i > 0) {
        const p = (i - 1) >> 1;
        if (hkey[p] <= key) break;
        hn[i] = hn[p]; hkey[i] = hkey[p]; i = p;
      }
      hn[i] = v; hkey[i] = key;
    };
    const pop = () => {
      const top = hn[0];
      const lastN = hn[--size], lastK = hkey[size];
      let i = 0;
      for (;;) {
        let c = 2 * i + 1;
        if (c >= size) break;
        if (c + 1 < size && hkey[c + 1] < hkey[c]) c++;
        if (hkey[c] >= lastK) break;
        hn[i] = hn[c]; hkey[i] = hkey[c]; i = c;
      }
      hn[i] = lastN; hkey[i] = lastK;
      return top;
    };

    stamp[src] = gen; dist[src] = 0; prev[src] = -1;
    push(src, heur(src));
    let found = false;
    while (size) {
      const u = pop();
      if (closed[u] === gen) continue;
      closed[u] = gen;
      if (u === dst) { found = true; break; }
      const du = dist[u];
      for (let k = g.adjStart[u]; k < g.adjStart[u + 1]; k++) {
        const v = g.adjNode[k];
        if (closed[v] === gen) continue;
        const e = g.adjEdge[k];
        let w = g.eLen[e] * mult[e];
        if (used && used[e]) w *= 1 + pen * used[e];
        const nd = du + w;
        if (stamp[v] !== gen || nd < dist[v]) {
          stamp[v] = gen; dist[v] = nd; prev[v] = e;
          push(v, nd + heur(v));
        }
      }
    }
    if (!found) return null;
    const edges = [];
    let v = dst;
    while (v !== src) {
      const e = prev[v];
      edges.push(e);
      v = g.eFrom[e] === v ? g.eTo[e] : g.eFrom[e];
    }
    edges.reverse();
    return edges;
  };

  // ---------------------------------------------------------------------------
  // 순환 코스 만들기
  // ---------------------------------------------------------------------------

  /**
   * 간선 목록을 따라 노드 목록을 만들고 경유지 때문에 생긴 군더더기를 없앤다.
   *  - 막다른 길에 들어갔다 바로 되돌아오는 "가시"
   *  - 같은 교차로를 다시 지나며 생기는 짧은 곁고리 (전체의 15% 미만)
   */
  function tidyPath(g, start, edges) {
    const stackN = [start], stackE = [];
    let cur = start;
    for (const e of edges) {
      const next = g.eFrom[e] === cur ? g.eTo[e] : g.eFrom[e];
      if (stackE.length && stackE[stackE.length - 1] === e) {
        stackE.pop(); stackN.pop();
      } else {
        stackE.push(e); stackN.push(next);
      }
      cur = next;
    }
    let total = 0;
    for (const e of stackE) total += g.eLen[e];
    const maxCut = total * 0.15;
    const outN = [start], outE = [], cum = [0];
    const pos = new Map([[start, 0]]);
    for (let i = 0; i < stackE.length; i++) {
      const v = stackN[i + 1], e = stackE[i];
      const p = pos.get(v);
      const here = cum[cum.length - 1] + g.eLen[e];
      if (p !== undefined && p > 0 && here - cum[p] < maxCut) {
        while (outN.length > p + 1) { pos.delete(outN.pop()); outE.pop(); cum.pop(); }
        continue;
      }
      if (outE.length && outE[outE.length - 1] === e) { // 곁고리를 자른 뒤 생긴 가시
        pos.delete(outN.pop()); outE.pop(); cum.pop();
        continue;
      }
      outE.push(e); outN.push(v); cum.push(here);
      if (!pos.has(v)) pos.set(v, outN.length - 1);
    }
    return { nodes: outN, edges: outE };
  }

  function summarize(g, costs, path) {
    const count = new Map();
    let length = 0, weighted = 0, repeated = 0;
    const by = { park: 0, water: 0, foot: 0, big: 0, steps: 0, unpaved: 0, lit: 0 };
    for (const e of path.edges) count.set(e, (count.get(e) || 0) + 1);
    for (const e of path.edges) {
      const len = g.eLen[e];
      length += len;
      weighted += len * costs.mult[e];
      if (count.get(e) > 1) repeated += len;
      const k = g.eKind[e], f = g.eFlags[e];
      if (f & F_PARK) by.park += len;
      if (f & F_WATER) by.water += len;
      if (k === KIND.FOOT) by.foot += len;
      if (k === KIND.BIG) by.big += len;
      if (k === KIND.STEPS) by.steps += len;
      if (f & F_UNPAVED) by.unpaved += len;
      if (f & F_LIT) by.lit += len;
    }
    const share = {};
    for (const key in by) share[key] = length ? by[key] / length : 0;
    return { length, avgCost: length ? weighted / length : 1, repeatRatio: length ? repeated / length : 0, share };
  }

  /**
   * 집(start) → 경유지들 → 집. 경유지는 집을 지나는 반지름 r 의 원 위에 고르게 놓는다.
   * dir: 원의 중심이 놓일 방향(방위각), clockwise: 도는 방향
   */
  function buildLoop(g, router, start, r, dir, nWp, clockwise) {
    const sLat = g.lat[start], sLon = g.lon[start];
    const [cLat, cLon] = destination(sLat, sLon, dir, r);
    const back = (dir + 180) % 360;
    const wps = [];
    for (let i = 1; i <= nWp; i++) {
      const ang = back + (clockwise ? 1 : -1) * (360 * i) / (nWp + 1);
      const [la, lo] = destination(cLat, cLon, ang, r);
      const nn = nearestNode(g, la, lo, 25);
      if (nn.node < 0) return null;
      if (!wps.length || wps[wps.length - 1] !== nn.node) wps.push(nn.node);
    }
    const seq = [start].concat(wps.filter((w) => w !== start), [start]);
    const used = new Uint8Array(g.m);
    let all = [];
    for (let i = 0; i + 1 < seq.length; i++) {
      const leg = router.route(seq[i], seq[i + 1], used);
      if (!leg) return null;
      for (const e of leg) if (used[e] < 250) used[e]++;
      all = all.concat(leg);
    }
    const path = tidyPath(g, start, all);
    if (path.edges.length < 3) return null;
    return { path, waypoints: wps, r, dir, nWp, clockwise };
  }

  function edgeOverlap(a, b) {
    const setB = new Set(b.path.edges);
    let shared = 0, total = 0;
    for (const e of a.path.edges) {
      total++;
      if (setB.has(e)) shared++;
    }
    return total ? shared / total : 0;
  }

  const tick = () => new Promise((res) => setTimeout(res, 0));

  /**
   * 목표 거리에 맞는 순환 코스 후보들을 만든다.
   * opts: { target(m), prefs, direction(도|null), tolerance(비율), alternatives, onProgress(0..1) }
   * 반환: 점수가 좋은 순서의 코스 배열
   */
  async function generateLoops(g, startNode, opts) {
    const target = opts.target;
    const tol = opts.tolerance != null ? opts.tolerance : 0.03;
    const costs = computeCosts(g, opts.prefs || {});
    const router = new Router(g, costs);
    const rand = mulberry32(opts.seed != null ? opts.seed : (Date.now() & 0xffffffff));

    let dirs;
    if (opts.direction != null && !isNaN(opts.direction)) {
      const d = Number(opts.direction);
      dirs = [d, d - 25, d + 25, d - 50, d + 50];
    } else {
      const off = rand() * 45;
      dirs = [0, 45, 90, 135, 180, 225, 270, 315].map((d) => d + off);
    }
    dirs = dirs.map((d) => (d + 360) % 360);

    const candidates = [];
    let tortuosity = 1.35; // 실제 길 거리 / 원 둘레 (방향마다 학습)
    const maxIter = 8;
    const totalSteps = dirs.length * (maxIter + 4);
    let step = 0;
    const progress = () => opts.onProgress && opts.onProgress(Math.min(0.99, step / totalSteps));

    for (let di = 0; di < dirs.length; di++) {
      const dir = dirs[di];
      const clockwise = di % 2 === 0;
      const nWp = target < 2500 ? 2 : 3;
      let r = target / (2 * Math.PI * tortuosity);
      let best = null;
      const tried = [];
      const consider = (loop) => {
        if (!loop) return;
        const s = summarize(g, costs, loop.path);
        loop.summary = s;
        loop.error = Math.abs(s.length - target) / target;
        tried.push(loop);
        if (!best || loop.error < best.error) best = loop;
      };
      for (let it = 0; it < maxIter; it++) {
        const loop = buildLoop(g, router, startNode, r, dir, nWp, clockwise);
        step++;
        if (!loop) { r *= 0.8; continue; }
        consider(loop);
        const L = loop.summary.length;
        if (loop.error <= tol * 0.5) break;
        // 반지름 보정 (시컨트 대신 비율 보정 + 급격한 변화 제한)
        const ratio = Math.min(1.8, Math.max(0.55, target / L));
        r *= ratio;
        if (it % 2 === 1) await tick();
      }
      // 아직 멀면 반지름·방향을 조금씩 흔들어 본다
      for (let j = 0; best && best.error > tol * 0.5 && j < 4; j++) {
        const rr = best.r * (1 + (rand() - 0.5) * 0.12 + (target - best.summary.length) / target * 0.7);
        const dd = best.dir + (rand() - 0.5) * 20;
        consider(buildLoop(g, router, startNode, Math.max(30, rr), dd, best.nWp, clockwise));
        step++;
      }
      if (best) {
        tortuosity = Math.min(2.5, Math.max(1.0, best.summary.length / (2 * Math.PI * best.r)));
        candidates.push(best);
      }
      step = (di + 1) * (maxIter + 4);
      progress();
      await tick();
    }

    // 점수: 선호 길 비중(평균 비용) + 반복 구간 + 거리 오차
    for (const c of candidates) {
      const s = c.summary;
      c.score = s.avgCost + 2.5 * s.repeatRatio + 12 * Math.max(0, c.error - tol) + 2 * c.error;
    }
    candidates.sort((a, b) => a.score - b.score);
    const picked = [];
    const want = opts.alternatives || 3;
    for (const c of candidates) {
      if (picked.length >= want) break;
      if (picked.every((p) => edgeOverlap(c, p) < 0.6)) picked.push(c);
    }
    for (const c of candidates) {
      if (picked.length >= want) break;
      if (!picked.includes(c)) picked.push(c);
    }
    opts.onProgress && opts.onProgress(1);
    return picked.map((c) => finalizeCourse(g, c, target));
  }

  function finalizeCourse(g, c, target) {
    const coords = c.path.nodes.map((v) => [g.lat[v], g.lon[v]]);
    // 1km 마다 표시할 위치
    const kmMarks = [];
    let acc = 0, nextKm = 1000;
    for (let i = 0; i < c.path.edges.length; i++) {
      const len = g.eLen[c.path.edges[i]];
      while (acc + len >= nextKm) {
        const t = (nextKm - acc) / len;
        const [a, b] = [coords[i], coords[i + 1]];
        kmMarks.push({ km: nextKm / 1000, lat: a[0] + (b[0] - a[0]) * t, lon: a[1] + (b[1] - a[1]) * t });
        nextKm += 1000;
      }
      acc += len;
    }
    // 주요 길 이름 (긴 순서)
    const byName = new Map();
    for (const e of c.path.edges) {
      const name = g.wayNames[g.eWay[e]];
      if (name) byName.set(name, (byName.get(name) || 0) + g.eLen[e]);
    }
    const streets = [...byName.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).map(([name, len]) => ({ name, length: len }));
    return {
      coords,
      length: c.summary.length,
      target,
      error: (c.summary.length - target) / target,
      repeatRatio: c.summary.repeatRatio,
      share: c.summary.share,
      avgCost: c.summary.avgCost,
      direction: c.dir,
      clockwise: c.clockwise,
      waypoints: c.waypoints.map((v) => [g.lat[v], g.lon[v]]),
      kmMarks,
      streets,
    };
  }

  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function toGPX(course, name) {
    const esc = (s) => String(s).replace(/[<>&"]/g, (ch) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[ch]));
    const pts = course.coords.map(([la, lo]) => `      <trkpt lat="${la.toFixed(7)}" lon="${lo.toFixed(7)}"/>`).join('\n');
    return `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="RunLoop" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata><name>${esc(name)}</name></metadata>
  <trk>
    <name>${esc(name)}</name>
    <trkseg>
${pts}
    </trkseg>
  </trk>
</gpx>
`;
  }

  const api = {
    haversine, destination, bearing,
    fetchRadiusFor, buildOverpassQuery,
    classifyWay, buildGraph, nearestNode, computeCosts, Router,
    generateLoops, toGPX, assembleRings,
    DEFAULT_PREFS, KIND,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Course = api;
})(typeof self !== 'undefined' ? self : this);
