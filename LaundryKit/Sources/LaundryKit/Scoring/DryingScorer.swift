import Foundation

/// 점수 계산 방식.
public enum ScoringMode: String, Codable, Sendable, CaseIterable, Identifiable {
    /// 습도만으로 판단 (기본값) — 빨래가 마르느냐 안 마르느냐는 습도가 결정한다.
    case humidityOnly
    /// 습도 · 기온 · 햇빛 · 바람을 함께 반영
    case combined

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .humidityOnly: "습도만"
        case .combined: "종합 (습도·기온·햇빛·바람)"
        }
    }
}

/// 날씨 한 시간을 0~100점의 "빨래 건조 점수"로 환산한다.
///
/// 기본(`.humidityOnly`)은 습도만으로 점수를 매긴다.
/// `.combined`는 습도에 기온 · 햇빛 · 바람을 보조 요소로 더한다.
/// 어느 방식이든 비가 오거나 올 확률이 높은 시간은 차단한다.
public struct DryingScorer: Sendable {
    public struct Weights: Sendable {
        public var humidity = 0.45
        public var temperature = 0.20
        public var sunshine = 0.20
        public var wind = 0.15
        public init() {}
    }

    public var mode: ScoringMode
    /// `.combined` 모드에서만 사용
    public var weights = Weights()
    /// 이 확률(%) 이상이면 비 때문에 차단
    public var rainProbabilityLimit = 60.0
    /// 이 강수량(mm) 이상이면 비 때문에 차단
    public var precipitationLimit = 0.1

    public init(mode: ScoringMode = .humidityOnly) {
        self.mode = mode
    }

    public func score(_ w: HourlyWeather) -> HourlyDryingScore {
        let blocked = isRainBlocked(w)
        guard !blocked else {
            return HourlyDryingScore(weather: w, score: 0, isRainBlocked: true)
        }

        if mode == .humidityOnly {
            let score = Int((humidityFactor(w.humidity) * 100).rounded())
            return HourlyDryingScore(weather: w, score: score, isRainBlocked: false)
        }

        var raw = weights.humidity * humidityFactor(w.humidity)
            + weights.temperature * temperatureFactor(w.temperature)
            + weights.sunshine * sunshineFactor(cloudCover: w.cloudCover, isDaytime: w.isDaytime)
            + weights.wind * windFactor(w.windSpeed)

        // 비 올 확률이 20%를 넘으면 점진적으로 감점 (60%에서 절반)
        if w.precipitationProbability > 20 {
            let ratio = (w.precipitationProbability - 20) / (rainProbabilityLimit - 20)
            raw *= 1 - 0.5 * clamp(ratio)
        }

        let score = Int((clamp(raw) * 100).rounded())
        return HourlyDryingScore(weather: w, score: score, isRainBlocked: false)
    }

    public func scores(_ hours: [HourlyWeather]) -> [HourlyDryingScore] {
        hours.map(score)
    }

    public func isRainBlocked(_ w: HourlyWeather) -> Bool {
        w.precipitation >= precipitationLimit || w.precipitationProbability >= rainProbabilityLimit
    }

    // MARK: - 요소별 0~1 점수

    /// 40% 이하면 만점, 85% 이상이면 0점
    func humidityFactor(_ humidity: Double) -> Double {
        clamp((85 - humidity) / (85 - 40))
    }

    /// 5°C 이하 0점, 25°C 이상 만점
    func temperatureFactor(_ temperature: Double) -> Double {
        clamp((temperature - 5) / (25 - 5))
    }

    /// 밤에는 0점, 낮에는 구름이 많을수록 감점 (완전히 흐려도 0.2)
    func sunshineFactor(cloudCover: Double, isDaytime: Bool) -> Double {
        guard isDaytime else { return 0 }
        return 1 - 0.8 * clamp(cloudCover / 100)
    }

    /// 2~7 m/s가 가장 좋고, 무풍이거나 너무 강하면 감점
    func windFactor(_ speed: Double) -> Double {
        switch speed {
        case ..<0.5: 0.3
        case 0.5..<2: 0.3 + 0.7 * (speed - 0.5) / 1.5
        case 2..<7: 1
        case 7..<12: 1 - 0.6 * (speed - 7) / 5
        default: 0.3
        }
    }
}

@inline(__always)
func clamp(_ value: Double, _ lower: Double = 0, _ upper: Double = 1) -> Double {
    min(max(value, lower), upper)
}
