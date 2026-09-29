using System.Text.Json;
using System.Text.Json.Serialization;

namespace LaundryTime.Core;

/// <summary>사용자 설정. %APPDATA%\LaundryTime\settings.json 에 저장된다.</summary>
public sealed record AppSettings
{
    public Place Place { get; init; } = Place.Seoul;
    public ScoringMode ScoringMode { get; init; } = ScoringMode.HumidityOnly;
    public bool NotificationsEnabled { get; init; } = true;
    /// <summary>추천 시간대 시작 몇 분 전에 알릴지.</summary>
    public int NotifyLeadMinutes { get; init; } = 30;
    public bool MiniWidgetVisible { get; init; }
    public double? MiniWidgetLeft { get; init; }
    public double? MiniWidgetTop { get; init; }
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
