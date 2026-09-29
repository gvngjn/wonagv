import Foundation

/// 날씨 → 예보 → 사람이 읽을 추천 문구까지 한 번에 만들어 주는 진입점.
public struct DryingAdvisor: Sendable {
    public var scorer: DryingScorer
    public var finder: DryingWindowFinder

    public init(scorer: DryingScorer = .init(), finder: DryingWindowFinder = .init()) {
        self.scorer = scorer
        self.finder = finder
    }

    public func forecast(for weather: [HourlyWeather], locationName: String?, now: Date = .now) -> DryingForecast {
        let hours = scorer.scores(weather)
        return DryingForecast(
            locationName: locationName,
            generatedAt: now,
            hours: hours,
            windows: finder.windows(in: hours, now: now)
        )
    }

    /// 한 줄 요약 (앱 헤더, 위젯, 워치 컴플리케이션용)
    public static func headline(for forecast: DryingForecast, now: Date = .now, calendar: Calendar = .current) -> String {
        guard let window = forecast.nextWindow(after: now) else {
            return "당분간 실내 건조를 추천해요"
        }
        if window.start <= now {
            return "지금 널기 좋아요! \(timeText(window.end, now: now, calendar: calendar))까지"
        }
        return "\(timeText(window.start, now: now, calendar: calendar))에 널어보세요"
    }

    /// "오후 2시", "내일 오전 10시" 형태
    public static func timeText(_ date: Date, now: Date = .now, calendar: Calendar = .current) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "ko_KR")
        formatter.calendar = calendar
        formatter.timeZone = calendar.timeZone
        formatter.dateFormat = "a h시"
        let time = formatter.string(from: date)

        let startOfToday = calendar.startOfDay(for: now)
        let startOfDate = calendar.startOfDay(for: date)
        let days = calendar.dateComponents([.day], from: startOfToday, to: startOfDate).day ?? 0
        switch days {
        case 0: return time
        case 1: return "내일 \(time)"
        case 2: return "모레 \(time)"
        default: return "\(days)일 뒤 \(time)"
        }
    }
}
