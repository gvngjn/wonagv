using System.Net.Http;
using LaundryTime.Core;
using Windows.Devices.Geolocation;

namespace LaundryTime.App.Services;

public enum LocationSource
{
    /// <summary>Windows 위치 서비스 (Wi-Fi · GPS)</summary>
    Device,
    /// <summary>인터넷 연결(IP) 기준 대략 위치</summary>
    Network,
}

public sealed record LocatedPlace(Place Place, LocationSource Source);

/// <summary>
/// 현재 위치를 찾는다. Windows 위치 서비스를 먼저 쓰고,
/// 꺼져 있거나 권한이 없으면 인터넷 연결 기준 대략 위치로 대신한다.
/// </summary>
public sealed class LocationService(LocationLookupClient lookup)
{
    public async Task<LocatedPlace?> LocateAsync(CancellationToken ct = default)
    {
        if (await TryDeviceLocationAsync() is { } c)
        {
            try
            {
                return new(await lookup.LookupAsync(c.Latitude, c.Longitude, ct), LocationSource.Device);
            }
            catch (Exception e) when (e is HttpRequestException or TaskCanceledException or FormatException)
            {
                // 좌표는 있으니 이름만 없이 사용
                return new(new Place("현재 위치", c.Latitude, c.Longitude), LocationSource.Device);
            }
        }

        try
        {
            return new(await lookup.LookupAsync(null, null, ct), LocationSource.Network);
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or FormatException)
        {
            return null;
        }
    }

    private static async Task<(double Latitude, double Longitude)?> TryDeviceLocationAsync()
    {
        try
        {
            var access = await Geolocator.RequestAccessAsync();
            if (access != GeolocationAccessStatus.Allowed)
                return null;

            var geolocator = new Geolocator { DesiredAccuracy = PositionAccuracy.Default };
            var position = await geolocator.GetGeopositionAsync(
                maximumAge: TimeSpan.FromMinutes(15),
                timeout: TimeSpan.FromSeconds(10));
            var p = position.Coordinate.Point.Position;
            return (p.Latitude, p.Longitude);
        }
        catch (Exception)
        {
            // 위치 서비스 꺼짐, 시간 초과, 지원하지 않는 환경 등 → 대략 위치로 대체
            return null;
        }
    }
}
