namespace LaundryTime.Core;

/// <summary>한 시간 단위의 날씨 예보 값.</summary>
/// <param name="Temperature">기온 (°C)</param>
/// <param name="Humidity">상대습도 (%)</param>
/// <param name="PrecipitationProbability">강수 확률 (%)</param>
/// <param name="Precipitation">시간당 강수량 (mm)</param>
/// <param name="WindSpeed">풍속 (m/s)</param>
/// <param name="CloudCover">운량 (%)</param>
public sealed record HourlyWeather(
    DateTimeOffset Time,
    double Temperature,
    double Humidity,
    double PrecipitationProbability,
    double Precipitation,
    double WindSpeed,
    double CloudCover,
    bool IsDaytime);

/// <summary>빨래 건조 적합도 등급.</summary>
public enum DryingLevel { Poor, Fair, Good, Excellent }

public static class DryingLevels
{
    public static DryingLevel FromScore(int score) => score switch
    {
        >= 80 => DryingLevel.Excellent,
        >= 60 => DryingLevel.Good,
        >= 40 => DryingLevel.Fair,
        _ => DryingLevel.Poor,
    };

    public static string Title(this DryingLevel level) => level switch
    {
        DryingLevel.Excellent => "최고",
        DryingLevel.Good => "좋음",
        DryingLevel.Fair => "보통",
        _ => "비추천",
    };
}

/// <summary>시간별 건조 점수 (0~100).</summary>
public sealed record HourlyDryingScore(HourlyWeather Weather, int Score, bool IsRainBlocked)
{
    public DryingLevel Level => DryingLevels.FromScore(Score);
}

/// <summary>연속된 "널기 좋은" 시간대. End는 마지막 시간 + 1시간.</summary>
public sealed record DryingWindow(DateTimeOffset Start, DateTimeOffset End, int AverageScore, double AverageHumidity)
{
    public DryingLevel Level => DryingLevels.FromScore(AverageScore);
    public int Hours => (int)Math.Round((End - Start).TotalHours);
}

/// <summary>한 지역의 전체 건조 예보.</summary>
/// <param name="Windows">점수가 높은 순서로 정렬된 추천 시간대</param>
public sealed record DryingForecast(
    string LocationName,
    DateTimeOffset GeneratedAt,
    IReadOnlyList<HourlyDryingScore> Hours,
    IReadOnlyList<DryingWindow> Windows)
{
    public DryingWindow? BestWindow => Windows.FirstOrDefault();

    /// <summary>주어진 시각이 속한 시간의 점수.</summary>
    public HourlyDryingScore? Current(DateTimeOffset now) =>
        Hours.LastOrDefault(h => h.Weather.Time <= now) ?? Hours.FirstOrDefault();

    /// <summary>진행 중이거나 앞으로 시작하는 가장 이른 추천 시간대.</summary>
    public DryingWindow? NextWindow(DateTimeOffset now) =>
        Windows.Where(w => w.End > now).OrderBy(w => w.Start).FirstOrDefault();
}
