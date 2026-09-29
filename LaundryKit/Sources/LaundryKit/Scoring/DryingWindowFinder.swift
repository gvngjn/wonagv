import Foundation

/// 시간별 점수에서 "빨래 널기 좋은 연속 구간"을 찾는다.
public struct DryingWindowFinder: Sendable {
    /// 구간에 포함되기 위한 최소 시간별 점수
    public var minimumScore: Int
    /// 최소 연속 시간
    public var minimumHours: Int

    public init(minimumScore: Int = 60, minimumHours: Int = 2) {
        self.minimumScore = minimumScore
        self.minimumHours = minimumHours
    }

    /// - Parameters:
    ///   - hours: 시간 순으로 정렬된 시간별 점수
    ///   - now: 이 시각이 속한 시간 이전은 무시한다
    /// - Returns: 평균 점수가 높은 순(같으면 긴 순)으로 정렬된 구간
    public func windows(in hours: [HourlyDryingScore], now: Date = .now) -> [DryingWindow] {
        let currentHourStart = now.addingTimeInterval(-3600)
        let upcoming = hours
            .filter { $0.weather.date > currentHourStart }
            .sorted { $0.weather.date < $1.weather.date }

        var result: [DryingWindow] = []
        var run: [HourlyDryingScore] = []

        func flush() {
            defer { run.removeAll() }
            guard run.count >= minimumHours, let first = run.first, let last = run.last else { return }
            let avgScore = Double(run.map(\.score).reduce(0, +)) / Double(run.count)
            let avgHumidity = run.map(\.weather.humidity).reduce(0, +) / Double(run.count)
            result.append(DryingWindow(
                start: first.weather.date,
                end: last.weather.date.addingTimeInterval(3600),
                averageScore: Int(avgScore.rounded()),
                averageHumidity: avgHumidity
            ))
        }

        for hour in upcoming {
            // 시간 간격이 끊기면 구간도 끊는다
            if let last = run.last, hour.weather.date.timeIntervalSince(last.weather.date) > 3600 {
                flush()
            }
            if hour.score >= minimumScore && !hour.isRainBlocked {
                run.append(hour)
            } else {
                flush()
            }
        }
        flush()

        return result.sorted {
            $0.averageScore != $1.averageScore ? $0.averageScore > $1.averageScore : $0.duration > $1.duration
        }
    }
}
