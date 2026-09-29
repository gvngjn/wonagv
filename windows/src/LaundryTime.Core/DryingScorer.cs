namespace LaundryTime.Core;

/// <summary>점수 계산 방식.</summary>
public enum ScoringMode
{
    /// <summary>습도만으로 판단 (기본값) — 빨래가 마르느냐 안 마르느냐는 습도가 결정한다.</summary>
    HumidityOnly,
    /// <summary>습도 · 기온 · 햇빛 · 바람을 함께 반영.</summary>
    Combined,
}

/// <summary>
/// 날씨 한 시간을 0~100점의 "빨래 건조 점수"로 환산한다.
/// 기본(<see cref="ScoringMode.HumidityOnly"/>)은 습도만 본다.
/// 어느 방식이든 비가 오거나 올 확률이 높은 시간은 차단한다.
/// </summary>
public sealed class DryingScorer
{
    public ScoringMode Mode { get; init; } = ScoringMode.HumidityOnly;

    // Combined 모드 가중치 (합계 1.0)
    public double HumidityWeight { get; init; } = 0.45;
    public double TemperatureWeight { get; init; } = 0.20;
    public double SunshineWeight { get; init; } = 0.20;
    public double WindWeight { get; init; } = 0.15;

    /// <summary>이 확률(%) 이상이면 비 때문에 차단.</summary>
    public double RainProbabilityLimit { get; init; } = 60;
    /// <summary>이 강수량(mm) 이상이면 비 때문에 차단.</summary>
    public double PrecipitationLimit { get; init; } = 0.1;

    public HourlyDryingScore Score(HourlyWeather w)
    {
        if (IsRainBlocked(w))
            return new HourlyDryingScore(w, 0, true);

        if (Mode == ScoringMode.HumidityOnly)
            return new HourlyDryingScore(w, ToScore(HumidityFactor(w.Humidity)), false);

        var raw = HumidityWeight * HumidityFactor(w.Humidity)
                + TemperatureWeight * TemperatureFactor(w.Temperature)
                + SunshineWeight * SunshineFactor(w.CloudCover, w.IsDaytime)
                + WindWeight * WindFactor(w.WindSpeed);

        // 비 올 확률이 20%를 넘으면 점진적으로 감점 (한계치에서 절반)
        if (w.PrecipitationProbability > 20)
        {
            var ratio = (w.PrecipitationProbability - 20) / (RainProbabilityLimit - 20);
            raw *= 1 - 0.5 * Clamp(ratio);
        }

        return new HourlyDryingScore(w, ToScore(raw), false);
    }

    public IReadOnlyList<HourlyDryingScore> Score(IEnumerable<HourlyWeather> hours) =>
        hours.Select(Score).ToList();

    public bool IsRainBlocked(HourlyWeather w) =>
        w.Precipitation >= PrecipitationLimit || w.PrecipitationProbability >= RainProbabilityLimit;

    // ── 요소별 0~1 점수 ─────────────────────────────────────

    /// <summary>40% 이하면 만점, 85% 이상이면 0점.</summary>
    internal static double HumidityFactor(double humidity) => Clamp((85 - humidity) / (85 - 40));

    /// <summary>5°C 이하 0점, 25°C 이상 만점.</summary>
    internal static double TemperatureFactor(double temperature) => Clamp((temperature - 5) / (25 - 5));

    /// <summary>밤은 0점, 낮에는 구름이 많을수록 감점 (완전히 흐려도 0.2).</summary>
    internal static double SunshineFactor(double cloudCover, bool isDaytime) =>
        isDaytime ? 1 - 0.8 * Clamp(cloudCover / 100) : 0;

    /// <summary>2~7 m/s가 가장 좋고, 무풍이거나 너무 강하면 감점.</summary>
    internal static double WindFactor(double speed) => speed switch
    {
        < 0.5 => 0.3,
        < 2 => 0.3 + 0.7 * (speed - 0.5) / 1.5,
        < 7 => 1,
        < 12 => 1 - 0.6 * (speed - 7) / 5,
        _ => 0.3,
    };

    private static int ToScore(double raw) => (int)Math.Round(Clamp(raw) * 100, MidpointRounding.AwayFromZero);

    private static double Clamp(double v) => Math.Clamp(v, 0, 1);
}
