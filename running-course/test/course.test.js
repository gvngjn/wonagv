// 실행: node --test running-course/test
const test = require('node:test');
const assert = require('node:assert');
const Course = require('../course.js');

// 가상의 동네: 100m 간격 격자 (60x60), 5줄마다 큰 도로, 북동쪽에 공원, 남쪽에 하천과 하천변 산책로
const HOME = [37.5, 127.0];
function makeCity() {
  const N = 60, step = 100;
  const dLat = step / 111195, dLon = step / (111195 * Math.cos(HOME[0] * Math.PI / 180));
  const lat0 = HOME[0] - (N / 2) * dLat, lon0 = HOME[1] - (N / 2) * dLon;
  const els = [];
  const id = (i, j) => i * 1000 + j + 1;
  for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) {
    els.push({ type: 'node', id: id(i, j), lat: lat0 + i * dLat, lon: lon0 + j * dLon });
  }
  let wid = 1;
  for (let i = 0; i < N; i++) {
    els.push({ type: 'way', id: wid++, nodes: Array.from({ length: N }, (_, j) => id(i, j)),
      tags: { highway: i % 5 === 0 ? 'primary' : 'residential', name: `가로${i}` } });
    els.push({ type: 'way', id: wid++, nodes: Array.from({ length: N }, (_, j) => id(j, i)),
      tags: { highway: i % 5 === 0 ? 'primary' : 'residential', name: `세로${i}` } });
  }
  // 공원 (행 32~42, 열 32~42) + 공원 안 대각선 산책로
  const P = (i, j) => ({ lat: lat0 + i * dLat, lon: lon0 + j * dLon });
  els.push({ type: 'way', id: wid++, tags: { leisure: 'park' },
    geometry: [P(32, 32), P(32, 42), P(42, 42), P(42, 32), P(32, 32)] });
  els.push({ type: 'way', id: wid++, nodes: [33, 34, 35, 36, 37, 38, 39, 40, 41].map((k) => id(k, k)),
    tags: { highway: 'footway', name: '공원산책로' } });
  // 하천 (행 14.5 를 따라 동서로) + 바로 옆 산책로 (행 14)
  els.push({ type: 'way', id: wid++, tags: { waterway: 'river' },
    geometry: [P(14.5, 0), P(14.5, N - 1)] });
  // 계단 하나
  els.push({ type: 'way', id: wid++, nodes: [id(31, 29), id(31, 30)], tags: { highway: 'steps' } });
  // 통행 불가 길 (무시되어야 함)
  els.push({ type: 'way', id: wid++, nodes: [id(1, 1), id(2, 2)], tags: { highway: 'service', access: 'private' } });
  return { elements: els };
}

const city = makeCity();
const g = Course.buildGraph(city);
const start = Course.nearestNode(g, HOME[0], HOME[1]).node;

test('그래프가 만들어지고 특징이 붙는다', () => {
  assert.ok(g.n >= 3600);
  assert.strictEqual(g.compSizes[g.mainComp], 3600);
  let park = 0, water = 0;
  for (let e = 0; e < g.m; e++) {
    if (g.eFlags[e] & 1) park++;
    if (g.eFlags[e] & 2) water++;
  }
  assert.ok(park > 100, `공원 간선 ${park}`);
  assert.ok(water > 50, `하천변 간선 ${water}`);
});

test('걸을 수 없는 길은 제외한다', () => {
  assert.strictEqual(Course.classifyWay({ highway: 'service', access: 'private' }), null);
  assert.strictEqual(Course.classifyWay({ highway: 'trunk', foot: 'no' }), null);
  assert.ok(Course.classifyWay({ highway: 'service', access: 'no', foot: 'yes' }));
  assert.strictEqual(Course.classifyWay({ highway: 'footway' }).kind, Course.KIND.FOOT);
});

for (const km of [3, 5, 10]) {
  test(`${km}km 순환 코스가 목표 거리 ±3% 안이고 집에서 시작·끝난다`, async () => {
    const courses = await Course.generateLoops(g, start, { target: km * 1000, seed: 42 });
    assert.ok(courses.length >= 1);
    const c = courses[0];
    assert.ok(Math.abs(c.error) <= 0.03, `오차 ${(c.error * 100).toFixed(1)}% (${c.length.toFixed(0)}m)`);
    assert.deepStrictEqual(c.coords[0], c.coords[c.coords.length - 1]);
    assert.deepStrictEqual(c.coords[0], [g.lat[start], g.lon[start]]);
    assert.ok(c.repeatRatio < 0.3, `반복 ${c.repeatRatio}`);
    assert.strictEqual(c.kmMarks.length, Math.floor(c.length / 1000));
    // 연속한 점들은 실제로 길로 이어져 있어야 한다 (100m 격자 → 최대 ~142m)
    for (let i = 1; i < c.coords.length; i++) {
      const d = Course.haversine(...c.coords[i - 1], ...c.coords[i]);
      assert.ok(d < 150, `점 사이 ${d}m`);
    }
  });
}

test('큰 도로 회피 설정이 큰 도로 비중을 줄인다', async () => {
  const avoid = await Course.generateLoops(g, start, { target: 5000, seed: 1, prefs: { bigRoad: 'avoid' } });
  const prefer = await Course.generateLoops(g, start, { target: 5000, seed: 1, prefs: { bigRoad: 'prefer', park: 'normal', water: 'normal', footpath: 'normal' } });
  assert.ok(avoid[0].share.big < prefer[0].share.big,
    `회피 ${avoid[0].share.big.toFixed(2)} vs 선호 ${prefer[0].share.big.toFixed(2)}`);
});

test('하천변 선호 + 방향 지정 시 하천 쪽으로 간다', async () => {
  const c = (await Course.generateLoops(g, start, { target: 8000, seed: 3, direction: 180, prefs: { water: 'prefer' } }))[0];
  assert.ok(c.share.water > 0.1, `하천변 ${c.share.water}`);
});

test('GPX 출력', async () => {
  const c = (await Course.generateLoops(g, start, { target: 3000, seed: 5 }))[0];
  const gpx = Course.toGPX(c, '테스트 <코스>');
  assert.match(gpx, /<trkpt lat="/);
  assert.match(gpx, /테스트 &lt;코스&gt;/);
});

test('Overpass 쿼리 반경', () => {
  assert.strictEqual(Course.fetchRadiusFor(5000), 2067);
  assert.match(Course.buildOverpassQuery(37.5, 127, 2000), /around:2000,37\.500000,127\.000000/);
});
