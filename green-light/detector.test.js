// 실행: node --test green-light/
const test = require('node:test');
const assert = require('node:assert');
const { classifyPixel, analyzePixels, GreenLightDetector } = require('./detector.js');

test('픽셀 색 판별', () => {
  assert.strictEqual(classifyPixel(255, 30, 20), 'red');
  assert.strictEqual(classifyPixel(20, 230, 120), 'green');
  assert.strictEqual(classifyPixel(30, 220, 210), 'green');   // 청록빛 LED
  assert.strictEqual(classifyPixel(255, 180, 0), null);       // 노란불
  assert.strictEqual(classifyPixel(240, 240, 240), null);     // 흰색
  assert.strictEqual(classifyPixel(60, 10, 10), null);        // 어두운 빨강(브레이크등 반사 등)
});

test('픽셀 배열 비율', () => {
  const px = (r, g, b) => [r, g, b, 255];
  const data = Uint8ClampedArray.from([...px(255, 0, 0), ...px(0, 255, 100), ...px(0, 0, 0), ...px(0, 0, 0)]);
  assert.deepStrictEqual(analyzePixels(data), { red: 0.25, green: 0.25 });
});

const RED = { red: 0.05, green: 0 };
const GREEN = { red: 0, green: 0.05 };
const NONE = { red: 0, green: 0 };

function run(det, frames) {
  // frames: [[ratios, durationMs], ...] — 100ms 간격으로 프레임 투입
  let t = 0; const events = [];
  for (const [r, dur] of frames) {
    for (let e = 0; e < dur; e += 100, t += 100) {
      if (det.update(r, t) === 'GREEN') events.push(t);
    }
  }
  return events;
}

test('빨간불 대기 후 초록불이 되면 한 번 알림', () => {
  const det = new GreenLightDetector();
  const ev = run(det, [[RED, 3000], [NONE, 300], [GREEN, 2000]]);
  assert.strictEqual(ev.length, 1);
  assert.ok(ev[0] >= 3300 + 400);
});

test('빨간불을 잠깐만 봤으면 알리지 않음 (지나가면서 본 경우)', () => {
  const det = new GreenLightDetector();
  assert.deepStrictEqual(run(det, [[RED, 800], [GREEN, 2000]]), []);
});

test('빨간불 없이 초록불만 보이면 알리지 않음', () => {
  const det = new GreenLightDetector();
  assert.deepStrictEqual(run(det, [[GREEN, 5000]]), []);
});

test('초록 깜빡임(짧은 반사)은 무시', () => {
  const det = new GreenLightDetector();
  assert.deepStrictEqual(run(det, [[RED, 3000], [GREEN, 200], [RED, 1000]]), []);
});

test('빨간불이 사라지고 오래 지나면 대기 해제', () => {
  const det = new GreenLightDetector();
  assert.deepStrictEqual(run(det, [[RED, 3000], [NONE, 6000], [GREEN, 2000]]), []);
});

test('쿨다운 후 다음 신호에서 다시 알림', () => {
  const det = new GreenLightDetector({ cooldownMs: 5000 });
  const ev = run(det, [[RED, 2000], [GREEN, 1000], [NONE, 6000], [RED, 2000], [GREEN, 1000]]);
  assert.strictEqual(ev.length, 2);
});
