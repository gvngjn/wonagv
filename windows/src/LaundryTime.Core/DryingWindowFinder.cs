namespace LaundryTime.Core;

/// <summary>시간별 점수에서 "빨래 널기 좋은 연속 구간"을 찾는다.</summary>
public sealed class DryingWindowFinder
{
    /// <summary>구간에 포함되기 위한 최소 시간별 점수.</summary>
    public int MinimumScore { get; init; } = 60;
    /// <summary>최소 연속 시간.</summary>
    public int MinimumHours { get; init; } = 2;
    /// <summary>빨래를 널 수 없는 시간대. 구간이 이 시간에 시작하지 않도록 앞부분을 잘라낸다.</summary>
    public IReadOnlyList<UnavailablePeriod> Unavailable { get; init; } = [];

    /// <returns>평균 점수가 높은 순(같으면 긴 순)으로 정렬된 구간.</returns>
    public IReadOnlyList<DryingWindow> FindWindows(IEnumerable<HourlyDryingScore> hours, DateTimeOffset now)
    {
        var currentHourStart = now.AddHours(-1);
        var upcoming = hours
            .Where(h => h.Weather.Time > currentHourStart)
            .OrderBy(h => h.Weather.Time);

        var result = new List<DryingWindow>();
        var run = new List<HourlyDryingScore>();

        void Flush()
        {
            // 널 수 없는 시간에 시작하는 부분은 잘라낸다 (그 뒤로는 계속 말라도 됨).
            // 이미 시작된 시간은 지금 시각 기준으로 판단한다.
            var skip = 0;
            while (skip < run.Count && IsUnavailable(Max(run[skip].Weather.Time, now).ToOffset(run[skip].Weather.Time.Offset)))
                skip++;
            run.RemoveRange(0, skip);

            if (run.Count >= MinimumHours)
            {
                result.Add(new DryingWindow(
                    run[0].Weather.Time,
                    run[^1].Weather.Time.AddHours(1),
                    (int)Math.Round(run.Average(h => h.Score), MidpointRounding.AwayFromZero),
                    run.Average(h => h.Weather.Humidity)));
            }
            run.Clear();
        }

        foreach (var hour in upcoming)
        {
            // 시간 간격이 끊기면 구간도 끊는다
            if (run.Count > 0 && hour.Weather.Time - run[^1].Weather.Time > TimeSpan.FromHours(1))
                Flush();

            if (hour.Score >= MinimumScore && !hour.IsRainBlocked)
                run.Add(hour);
            else
                Flush();
        }
        Flush();

        return result
            .OrderByDescending(w => w.AverageScore)
            .ThenByDescending(w => w.End - w.Start)
            .ToList();
    }

    public bool IsUnavailable(DateTimeOffset time) => Unavailable.Any(p => p.Contains(time));

    private static DateTimeOffset Max(DateTimeOffset a, DateTimeOffset b) => a > b ? a : b;
}
