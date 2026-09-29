using System.Text.Json;
using System.Text.Json.Serialization;

namespace LaundryTime.Core;

/// <summary>사용자 설정. %APPDATA%\LaundryTime\settings.json 에 저장된다.</summary>
public sealed record AppSettings
{
    public Place Place { get; init; } = Place.Seoul;
    /// <summary>켜져 있으면 새로고침할 때마다 현재 위치로 지역을 갱신한다.</summary>
    public bool AutoLocation { get; init; } = true;
    /// <summary>빨래를 널 수 없는 시간대 (출근 시간 등).</summary>
    public IReadOnlyList<UnavailablePeriod> UnavailablePeriods { get; init; } = [];
    public ScoringMode ScoringMode { get; init; } = ScoringMode.HumidityOnly;
    public bool NotificationsEnabled { get; init; } = true;
    /// <summary>추천 시간대 시작 몇 분 전에 알릴지.</summary>
    public int NotifyLeadMinutes { get; init; } = 30;
    public bool MiniWidgetVisible { get; init; }
    /// <summary>미니 위젯 최소화 모드 (습도와 짧은 추천만 표시).</summary>
    public bool MiniWidgetCompact { get; init; }
    public double? MiniWidgetLeft { get; init; }
    public double? MiniWidgetTop { get; init; }

    // 목록 속성을 값으로 비교
    public bool Equals(AppSettings? other) =>
        other is not null &&
        Place == other.Place && AutoLocation == other.AutoLocation &&
        UnavailablePeriods.SequenceEqual(other.UnavailablePeriods) &&
        ScoringMode == other.ScoringMode && NotificationsEnabled == other.NotificationsEnabled &&
        NotifyLeadMinutes == other.NotifyLeadMinutes && MiniWidgetVisible == other.MiniWidgetVisible &&
        MiniWidgetCompact == other.MiniWidgetCompact &&
        MiniWidgetLeft == other.MiniWidgetLeft && MiniWidgetTop == other.MiniWidgetTop;

    public override int GetHashCode() => HashCode.Combine(Place, AutoLocation, ScoringMode, UnavailablePeriods.Count);
}

public sealed class SettingsStore(string path)
{
    public static string DefaultPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "LaundryTime", "settings.json");

    private static readonly JsonSerializerOptions Options = new()
    {
        WriteIndented = true,
        Converters = { new JsonStringEnumConverter() },
    };

    public string FilePath => path;

    public AppSettings Load()
    {
        try
        {
            return File.Exists(path)
                ? JsonSerializer.Deserialize<AppSettings>(File.ReadAllText(path), Options) ?? new()
                : new();
        }
        catch (Exception e) when (e is JsonException or IOException or UnauthorizedAccessException)
        {
            // 설정 파일이 깨졌으면 기본값으로 시작
            return new();
        }
    }

    public void Save(AppSettings settings)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, JsonSerializer.Serialize(settings, Options));
    }
}
