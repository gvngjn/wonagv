using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace LaundryTime.Core;

/// <summary>
/// <see href="https://www.bigdatacloud.com/free-api/free-reverse-geocode-to-city-api">BigDataCloud</see>
/// 무료 위치 조회 (API 키 불필요).
/// 좌표를 주면 지역 이름을 찾고, 좌표 없이 호출하면 인터넷 연결(IP) 기준 대략 위치를 알려준다.
/// </summary>
public sealed class LocationLookupClient(HttpClient http)
{
    private const string Url = "https://api.bigdatacloud.net/data/reverse-geocode-client";

    /// <param name="latitude">null이면 IP 기반 대략 위치</param>
    public async Task<Place> LookupAsync(double? latitude, double? longitude, CancellationToken ct = default)
    {
        var inv = CultureInfo.InvariantCulture;
        var url = latitude is { } lat && longitude is { } lon
            ? $"{Url}?latitude={lat.ToString("F5", inv)}&longitude={lon.ToString("F5", inv)}&localityLanguage=ko"
            : $"{Url}?localityLanguage=ko";
        return Parse(await http.GetStringAsync(url, ct));
    }

    internal static Place Parse(string json)
    {
        var r = JsonSerializer.Deserialize<Response>(json) ?? throw new FormatException("위치 정보를 해석할 수 없어요");
        if (r.Latitude == 0 && r.Longitude == 0)
            throw new FormatException("위치를 확인할 수 없어요");

        // "서울특별시 종로구"처럼 시/도 + 동네, 중복 제거
        var parts = new[] { r.City, r.Locality }
            .Where(s => !string.IsNullOrWhiteSpace(s))
            .Distinct()
            .ToList();
        if (parts.Count == 0 && !string.IsNullOrWhiteSpace(r.PrincipalSubdivision))
            parts.Add(r.PrincipalSubdivision);
        var name = parts.Count > 0 ? string.Join(" ", parts) : "현재 위치";
        return new Place(name, r.Latitude, r.Longitude);
    }

    private sealed class Response
    {
        [JsonPropertyName("latitude")] public double Latitude { get; set; }
        [JsonPropertyName("longitude")] public double Longitude { get; set; }
        [JsonPropertyName("city")] public string? City { get; set; }
        [JsonPropertyName("locality")] public string? Locality { get; set; }
        [JsonPropertyName("principalSubdivision")] public string? PrincipalSubdivision { get; set; }
    }
}
