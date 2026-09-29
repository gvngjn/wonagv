using System.Windows.Media;
using LaundryTime.Core;

namespace LaundryTime.App.ViewModels;

/// <summary>추천 시간대 목록의 한 줄.</summary>
public sealed record WindowItem(string TimeRange, string Detail, string LevelTitle, Brush LevelBrush)
{
    public static WindowItem From(DryingWindow w, DateTimeOffset now) => new(
        $"{DryingAdvisor.TimeText(w.Start, now)} ~ {DryingAdvisor.TimeText(w.End, now)}",
        $"{w.Hours}시간 · 평균 습도 {w.AverageHumidity:0}%",
        w.Level.Title(),
        LevelStyle.BrushOf(w.Level));
}

/// <summary>시간별 차트의 막대 하나.</summary>
public sealed record HourBar(double BarHeight, Brush Brush, string Label, string ToolTip, bool IsUnavailable)
{
    /// <summary>빨래 못 너는 시간은 흐리게 표시.</summary>
    public double Opacity => IsUnavailable ? 0.35 : 1;

    public const double MaxHeight = 120;

    public static HourBar From(HourlyDryingScore h, DateTimeOffset now, bool isUnavailable)
    {
        var t = h.Weather.Time;
        // 3시간마다 라벨, 자정에는 날짜 표시
        var label = t.Hour == 0 ? $"{t:M/d}" : t.Hour % 3 == 0 ? $"{t.Hour}" : "";
        var tip = $"{DryingAdvisor.TimeText(t, now)}\n습도 {h.Weather.Humidity:0}% · 기온 {h.Weather.Temperature:0}°C\n" +
                  (h.IsRainBlocked ? "비 예보 — 널지 마세요" : $"건조 점수 {h.Score} ({h.Level.Title()})") +
                  (isUnavailable ? "\n빨래 못 너는 시간" : "");
        return new HourBar(
            Math.Max(3, h.Score / 100.0 * MaxHeight),
            h.IsRainBlocked ? Brushes.LightSteelBlue : LevelStyle.BrushOf(h.Level),
            label,
            tip,
            isUnavailable);
    }
}

public sealed record ScoringModeOption(ScoringMode Mode, string Title)
{
    public static readonly ScoringModeOption[] All =
    [
        new(ScoringMode.HumidityOnly, "습도만 (기본)"),
        new(ScoringMode.Combined, "종합 (습도·기온·햇빛·바람)"),
    ];
}

/// <summary>요일 선택 체크박스 하나.</summary>
public sealed class DayToggle(DayOfWeek day, bool isChecked) : ObservableObject
{
    public DayOfWeek Day { get; } = day;
    public string Name { get; } = UnavailablePeriod.DayName(day);

    private bool _isChecked = isChecked;
    public bool IsChecked { get => _isChecked; set => Set(ref _isChecked, value); }
}
