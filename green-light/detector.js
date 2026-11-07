/*
 * 신호등 색 판별 + "빨간불 → 초록불" 전환 감지 로직.
 * 브라우저(<script>)와 Node(require) 양쪽에서 쓸 수 있도록 UI 코드와 분리했다.
 */
(function (root) {
  'use strict';

  /** RGB(0~255) → HSV (h: 0~360, s/v: 0~1) */
  function rgbToHsv(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    var max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
    var h = 0;
    if (d !== 0) {
      if (max === r) h = 60 * (((g - b) / d) % 6);
      else if (max === g) h = 60 * ((b - r) / d + 2);
      else h = 60 * ((r - g) / d + 4);
    }
    if (h < 0) h += 360;
    return { h: h, s: max === 0 ? 0 : d / max, v: max };
  }

  /**
   * 한 픽셀이 "켜진 빨간불" / "켜진 초록불" 색인지 판별.
   * 한국 신호등 초록불(LED)은 카메라에 청록색으로 찍히는 경우가 많아 초록 범위를 넓게 잡는다.
   */
  function classifyPixel(r, g, b) {
    var c = rgbToHsv(r, g, b);
    if (c.v < 0.45 || c.s < 0.4) return null;          // 어둡거나 색이 옅으면 무시
    if ((c.h <= 18 || c.h >= 335) && c.v >= 0.5) return 'red';
    if (c.h >= 120 && c.h <= 195) return 'green';
    return null;
  }

  /** RGBA 픽셀 배열에서 빨강/초록 픽셀 비율 계산 */
  function analyzePixels(data) {
    var red = 0, green = 0, total = data.length / 4;
    for (var i = 0; i < data.length; i += 4) {
      var k = classifyPixel(data[i], data[i + 1], data[i + 2]);
      if (k === 'red') red++;
      else if (k === 'green') green++;
    }
    return {
      red: total ? red / total : 0,
      green: total ? green / total : 0,
    };
  }

  var DEFAULTS = {
    minRatio: 0.004,       // 영역의 0.4% 이상이 해당 색이면 "불이 켜짐"으로 본다 (감도)
    dominance: 1.5,        // 다른 색보다 이 배수 이상 많아야 그 색으로 인정
    redArmMs: 1500,        // 빨간불이 이만큼 계속 보여야 "신호 대기 중"으로 판단
    greenConfirmMs: 400,   // 초록불이 이만큼 계속 보여야 알림 (깜빡임·반사 무시)
    redGapMs: 4000,        // 빨간불이 꺼진 뒤 이 시간 안에 초록불이 떠야 "신호가 바뀜"으로 인정
    cooldownMs: 15000,     // 한 번 알린 뒤 다시 알리지 않는 시간
  };

  /**
   * 상태 머신
   *   idle   : 아무것도 없음
   *   red    : 빨간불 보이는 중 (아직 대기 확정 전)
   *   armed  : 빨간불에서 대기 중 → 초록불 기다림
   *   cooldown: 방금 알림
   * update()가 'GREEN'을 반환하면 알림을 울리면 된다.
   */
  function GreenLightDetector(options) {
    this.opts = Object.assign({}, DEFAULTS, options || {});
    this.reset();
  }

  GreenLightDetector.prototype.reset = function () {
    this.state = 'idle';
    this.redSince = null;
    this.lastRedAt = null;
    this.greenSince = null;
    this.cooldownUntil = 0;
  };

  /** ratios: {red, green}, now: ms → 현재 프레임의 색('red'|'green'|null) */
  GreenLightDetector.prototype.colorOf = function (ratios) {
    var o = this.opts;
    if (ratios.red >= o.minRatio && ratios.red >= ratios.green * o.dominance) return 'red';
    if (ratios.green >= o.minRatio && ratios.green >= ratios.red * o.dominance) return 'green';
    return null;
  };

  GreenLightDetector.prototype.update = function (ratios, now) {
    var o = this.opts;
    var color = this.colorOf(ratios);

    if (this.state === 'cooldown') {
      if (now < this.cooldownUntil) return null;
      this.reset();
    }

    if (color === 'red') {
      this.greenSince = null;
      this.lastRedAt = now;
      if (this.redSince === null) this.redSince = now;
      if (this.state !== 'armed') {
        this.state = now - this.redSince >= o.redArmMs ? 'armed' : 'red';
      }
      return null;
    }

    this.redSince = null;

    if (this.state === 'armed') {
      if (color === 'green') {
        if (this.greenSince === null) this.greenSince = now;
        if (now - this.greenSince >= o.greenConfirmMs) {
          this.state = 'cooldown';
          this.cooldownUntil = now + o.cooldownMs;
          return 'GREEN';
        }
        return null;
      }
      this.greenSince = null;
      // 빨간불이 사라졌는데 초록불도 안 나오면(차가 움직였거나 화면에서 벗어남) 대기 해제
      if (now - this.lastRedAt > o.redGapMs) this.state = 'idle';
      return null;
    }

    this.state = 'idle';
    this.greenSince = null;
    return null;
  };

  var api = {
    rgbToHsv: rgbToHsv,
    classifyPixel: classifyPixel,
    analyzePixels: analyzePixels,
    GreenLightDetector: GreenLightDetector,
    DEFAULTS: DEFAULTS,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.GreenLight = api;
})(typeof self !== 'undefined' ? self : this);
