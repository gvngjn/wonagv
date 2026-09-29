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

    /// <summary>"오후 2시", "내일 오전 10시" 형태. <paramref name="date"/>의 오프셋 기준으로 표시한다.</summary>
    public static string TimeText(DateTimeOffset date, DateTimeOffset now)
    {
        var local = date;
        var today = now.ToOffset(date.Offset).Date;
        var ampm = local.Hour < 12 ? "오전" : "오후";
        var hour12 = local.Hour % 12 == 0 ? 12 : local.Hour % 12;
        var time = $"{ampm} {hour12}시";

        var days = (local.Date - today).Days;
        return days switch
        {
            0 => time,
            1 => $"내일 {time}",
            2 => $"모레 {time}",
            _ => $"{days}일 뒤 {time}",
        };
    }
}
