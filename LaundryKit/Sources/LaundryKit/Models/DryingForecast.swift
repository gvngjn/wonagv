import Foundation

/// 빨래 건조 적합도 등급.
public enum DryingLevel: String, Codable, Sendable, CaseIterable, Comparable {
    case poor, fair, good, excellent

    public init(score: Int) {
        switch score {
        case 80...: self = .excellent
        case 60..<80: self = .good
        case 40..<60: self = .fair
        default: self = .poor
        }
    }

    public var title: String {
        switch self {
        case .excellent: "최고"
        case .good: "좋음"
        case .fair: "보통"
        case .poor: "비추천"
        }
    }

    /// SF Symbol 이름 (앱·위젯·워치 공통 사용)
    public var symbolName: String {
        switch self {
        case .excellent: "sun.max.fill"
        case .good: "cloud.sun.fill"
        case .fair: "cloud.fill"
        case .poor: "cloud.rain.fill"
        }
    }

    private var rank: Int { Self.allCases.firstIndex(of: self)! }
    public static func < (lhs: Self, rhs: Self) -> Bool { lhs.rank < rhs.rank }
}

/// 시간별 건조 점수.
public struct HourlyDryingScore: Codable, Hashable, Sendable, Identifiable {
    public var weather: HourlyWeather
    /// 0~100
    public var score: Int
    /// 비 때문에 널면 안 되는 시간인지
    public var isRainBlocked: Bool

    public var id: Date { weather.date }
    public var level: DryingLevel { DryingLevel(score: score) }

    public init(weather: HourlyWeather, score: Int, isRainBlocked: Bool) {
        self.weather = weather
        self.score = score
        self.isRainBlocked = isRainBlocked
    }
}

/// 연속된 "널기 좋은" 시간대.
public struct DryingWindow: Codable, Hashable, Sendable, Identifiable {
    public var start: Date
    /// 구간의 끝 (마지막 시간 + 1시간)
    public var end: Date
    public var averageScore: Int
    public var averageHumidity: Double

    public var id: Date { start }
    public var level: DryingLevel { DryingLevel(score: averageScore) }
    public var duration: TimeInterval { end.timeIntervalSince(start) }
    public var hours: Int { Int((duration / 3600).rounded()) }

    public init(start: Date, end: Date, averageScore: Int, averageHumidity: Double) {
        self.start = start
        self.end = end
        self.averageScore = averageScore
        self.averageHumidity = averageHumidity
    }
}

/// 한 지역에 대한 전체 건조 예보. 위젯/워치에 그대로 전달되는 단위.
public struct DryingForecast: Codable, Hashable, Sendable {
    public var locationName: String?
    public var generatedAt: Date
    public var hours: [HourlyDryingScore]
    /// 점수가 높은 순서
    public var windows: [DryingWindow]

    public init(locationName: String?, generatedAt: Date, hours: [HourlyDryingScore], windows: [DryingWindow]) {
        self.locationName = locationName
        self.generatedAt = generatedAt
        self.hours = hours
        self.windows = windows
    }

    /// 가장 추천하는 시간대
    public var bestWindow: DryingWindow? { windows.first }

    /// 주어진 시각이 속한 시간의 점수
    public func current(at date: Date = .now) -> HourlyDryingScore? {
        hours.last { $0.weather.date <= date } ?? hours.first
    }

    /// 주어진 시각 이후에 시작하거나 진행 중인 가장 이른 추천 시간대
    public func nextWindow(after date: Date = .now) -> DryingWindow? {
        windows.filter { $0.end > date }.min { $0.start < $1.start }
    }
}
