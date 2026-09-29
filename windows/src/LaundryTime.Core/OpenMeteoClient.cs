using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace LaundryTime.Core;

/// <summary>검색으로 찾은 지역.</summary>
public sealed record Place(string Name, double Latitude, double Longitude)
{
    public static readonly Place Seoul = new("서울", 37.5665, 126.9780);
}

/// <summary>
/// <see href="https://open-meteo.com">Open-Meteo</see> 날씨 · 지역 검색 클라이언트.
/// API 키가 필요 없고 비상업적 용도로 무료다.
/// </summary>
public sealed class OpenMeteoClient(HttpClient http)
{
    private const string ForecastUrl = "https://api.open-meteo.com/v1/forecast";
    private const string GeocodingUrl = "https://geocoding-api.open-meteo.com/v1/search";

    public int ForecastDays { get; init; } = 3;

    public async Task<IReadOnlyList<HourlyWeather>> GetHourlyForecastAsync(
        double latitude, double longitude, CancellationToken ct = default)
    {
        var json = await http.GetStringAsync(ForecastUri(latitude, longitude), ct);
        return ParseForecast(json);
    }

    public async Task<IReadOnlyList<Place>> SearchPlacesAsync(string query, CancellationToken ct = default)
    {
        if (string.IsNullOrWhiteSpace(query))
            return [];
        var url = $"{GeocodingUrl}?name={Uri.EscapeDataString(query.Trim())}&count=8&language=ko&format=json";
        var json = await http.GetStringAsync(url, ct);
        return ParsePlaces(json);
    }

    internal Uri ForecastUri(double latitude, double longitude)
    {
        var inv = CultureInfo.InvariantCulture;
        var hourly = string.Join(',',
            "temperature_2m", "relative_humidity_2m", "precipitation_probability",
            "precipitation", "wind_speed_10m", "cloud_cover", "is_day");
        return new Uri(
            $"{ForecastUrl}?latitude={latitude.ToString("F4", inv)}&longitude={longitude.ToString("F4", inv)}" +
            $"&hourly={hourly}&wind_speed_unit=ms&timeformat=unixtime&timezone=auto&forecast_days={ForecastDays}");
    }

    internal static IReadOnlyList<HourlyWeather> ParseForecast(string json)
    {
        var response = JsonSerializer.Deserialize<ForecastResponse>(json)
            ?? throw new FormatException("날씨 데이터를 해석할 수 없어요");
        var h = response.Hourly;
        var n = h.Time.Length;
        if (new[] { h.Temperature.Length, h.Humidity.Length, h.PrecipitationProbability.Length,
                    h.Precipitation.Length, h.WindSpeed.Length, h.CloudCover.Length, h.IsDay.Length }
            .Any(len => len != n))
            throw new FormatException("날씨 데이터의 길이가 맞지 않아요");

        // 해당 지역의 현지 시각으로 표시하기 위해 응답의 UTC 오프셋을 적용
        var offset = TimeSpan.FromSeconds(response.UtcOffsetSeconds);
        var result = new List<HourlyWeather>(n);
        for (var i = 0; i < n; i++)
        {
            // 값이 비어 있는(null) 시간은 건너뛴다
            if (h.Temperature[i] is not { } temp || h.Humidity[i] is not { } humidity)
                continue;
            result.Add(new HourlyWeather(
                DateTimeOffset.FromUnixTimeSeconds(h.Time[i]).ToOffset(offset),
                temp,
                humidity,
                h.PrecipitationProbability[i] ?? 0,
                h.Precipitation[i] ?? 0,
                h.WindSpeed[i] ?? 0,
                h.CloudCover[i] ?? 0,
                (h.IsDay[i] ?? 1) == 1));
        }
        return result;
    }

    internal static IReadOnlyList<Place> ParsePlaces(string json)
    {
        var response = JsonSerializer.Deserialize<GeocodingResponse>(json);
        return response?.Results?
            .Select(r => new Place(
                string.Join(", ", new[] { r.Name, r.Admin1, r.Country }
                    .Where(s => !string.IsNullOrWhiteSpace(s)).Distinct()),
                r.Latitude, r.Longitude))
            .ToList() ?? [];
    }

    private sealed class ForecastResponse
    {
        [JsonPropertyName("utc_offset_seconds")] public int UtcOffsetSeconds { get; set; }
        [JsonPropertyName("hourly")] public HourlyData Hourly { get; set; } = new();
    }

    private sealed class HourlyData
    {
        [JsonPropertyName("time")] public long[] Time { get; set; } = [];
        [JsonPropertyName("temperature_2m")] public double?[] Temperature { get; set; } = [];
        [JsonPropertyName("relative_humidity_2m")] public double?[] Humidity { get; set; } = [];
        [JsonPropertyName("precipitation_probability")] public double?[] PrecipitationProbability { get; set; } = [];
        [JsonPropertyName("precipitation")] public double?[] Precipitation { get; set; } = [];
        [JsonPropertyName("wind_speed_10m")] public double?[] WindSpeed { get; set; } = [];
        [JsonPropertyName("cloud_cover")] public double?[] CloudCover { get; set; } = [];
        [JsonPropertyName("is_day")] public int?[] IsDay { get; set; } = [];
    }

    private sealed class GeocodingResponse
    {
        [JsonPropertyName("results")] public List<GeocodingResult>? Results { get; set; }
    }

    private sealed class GeocodingResult
    {
        [JsonPropertyName("name")] public string Name { get; set; } = "";
        [JsonPropertyName("admin1")] public string? Admin1 { get; set; }
        [JsonPropertyName("country")] public string? Country { get; set; }
        [JsonPropertyName("latitude")] public double Latitude { get; set; }
        [JsonPropertyName("longitude")] public double Longitude { get; set; }
    }
}
