namespace LaundryTime.Core;

/// <summary>날씨 → 예보 → 사람이 읽을 추천 문구까지 만들어 주는 진입점.</summary>
public sealed class DryingAdvisor
{
    public DryingScorer Scorer { get; init; } = new();
    public DryingWindowFinder Finder { get; init; } = new();

    public DryingForecast CreateForecast(IEnumerable<HourlyWeather> weather, string locationName, DateTimeOffset now)
    {
        var hours = Scorer.Score(weather);
        return new DryingForecast(locationName, now, hours, Finder.FindWindows(hours, now));
    }

    /// <summary>한 줄 요약 (메인 화면, 미니 위젯, 트레이 툴팁용).</summary>
    public static string Headline(DryingForecast forecast, DateTimeOffset now)
    {
        var window = forecast.NextWindow(now);
        if (window is null)
            return "당분간 실내 건조를 추천해요";
        if (window.Start <= now)
            return $"지금 널기 좋아요! {TimeText(window.End, now)}까지";
        return $"{TimeText(window.Start, now)}에 널어보세요";
    }

    /// <summary>
    /// "오늘 오후 2시", "내일(수) 오전 10시", "10월 1일(목) 오전 9시" 형태.
    /// <paramref name="date"/>의 오프셋(지역 현지 시각) 기준으로 표시한다.
    /// </summary>
    public static string TimeText(DateTimeOffset date, DateTimeOffset now) =>
        $"{DayText(date, now)} {ClockText(date)}";

    /// <summary>시간 범위. 같은 날이면 날짜는 한 번만: "내일(수) 오전 10시 ~ 오후 3시".</summary>
    public static string RangeText(DateTimeOffset start, DateTimeOffset end, DateTimeOffset now)
    {
        var endLocal = end.ToOffset(start.Offset);
        return endLocal.Date == start.Date
            ? $"{TimeText(start, now)} ~ {ClockText(endLocal)}"
            : $"{TimeText(start, now)} ~ {TimeText(endLocal, now)}";
    }

    /// <summary>"오늘", "내일(수)", "10월 1일(목)".</summary>
    public static string DayText(DateTimeOffset date, DateTimeOffset now)
    {
        var today = now.ToOffset(date.Offset).Date;
        var weekday = UnavailablePeriod.DayName(date.DayOfWeek);
        return (date.Date - today).Days switch
        {
            0 => "오늘",
            1 => $"내일({weekday})",
            _ => $"{date.Month}월 {date.Day}일({weekday})",
        };
    }

    /// <summary>"오전 9시", "오후 12시".</summary>
    public static string ClockText(DateTimeOffset date)
    {
        var ampm = date.Hour < 12 ? "오전" : "오후";
        var hour12 = date.Hour % 12 == 0 ? 12 : date.Hour % 12;
        return date.Minute == 0 ? $"{ampm} {hour12}시" : $"{ampm} {hour12}시 {date.Minute}분";
    }
}
