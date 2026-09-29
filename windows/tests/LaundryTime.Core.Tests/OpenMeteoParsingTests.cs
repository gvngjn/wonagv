namespace LaundryTime.Core.Tests;

public class OpenMeteoParsingTests
{
    [Fact]
    public void ParsesForecastAndSkipsNullHours()
    {
        const string json = """
        {"utc_offset_seconds":32400,
         "hourly":{"time":[1790000000,1790003600],
         "temperature_2m":[21.5,null],"relative_humidity_2m":[55,60],
         "precipitation_probability":[10,null],"precipitation":[0,0],
         "wind_speed_10m":[2.1,3.0],"cloud_cover":[20,30],"is_day":[1,0]}}
        """;

        var hours = OpenMeteoClient.ParseForecast(json);

        var hour = Assert.Single(hours);
        Assert.Equal(55, hour.Humidity);
        Assert.Equal(2.1, hour.WindSpeed);
        Assert.True(hour.IsDaytime);
        Assert.Equal(TimeSpan.FromHours(9), hour.Time.Offset);
        Assert.Equal(1790000000, hour.Time.ToUnixTimeSeconds());
    }

    [Fact]
    public void RejectsMismatchedArrays()
    {
        const string json = """
        {"hourly":{"time":[1,2],"temperature_2m":[1],"relative_humidity_2m":[1,2],
         "precipitation_probability":[1,2],"precipitation":[1,2],"wind_speed_10m":[1,2],
         "cloud_cover":[1,2],"is_day":[1,2]}}
        """;
        Assert.Throws<FormatException>(() => OpenMeteoClient.ParseForecast(json));
    }

    [Fact]
    public void ParsesPlaces()
    {
        const string json = """
        {"results":[{"name":"수원시","admin1":"경기도","country":"대한민국","latitude":37.29,"longitude":127.01}]}
        """;
        var place = Assert.Single(OpenMeteoClient.ParsePlaces(json));
        Assert.Equal("수원시, 경기도, 대한민국", place.Name);
        Assert.Equal(37.29, place.Latitude);
    }

    [Fact]
    public void NoPlacesWhenResultsMissing() => Assert.Empty(OpenMeteoClient.ParsePlaces("{}"));
}
