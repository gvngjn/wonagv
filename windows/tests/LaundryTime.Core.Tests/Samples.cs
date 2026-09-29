using LaundryTime.Core;

namespace LaundryTime.Core.Tests;

internal static class Samples
{
    public static readonly DateTimeOffset Base = new(2026, 9, 29, 9, 0, 0, TimeSpan.FromHours(9));

    public static HourlyWeather Weather(
        DateTimeOffset? time = null,
        double humidity = 50,
        double temperature = 20,
        double wind = 3,
        double cloud = 20,
        double rainChance = 0,
        double precipitation = 0,
        bool isDaytime = true) =>
        new(time ?? Base, temperature, humidity, rainChance, precipitation, wind, cloud, isDaytime);

    public static List<HourlyDryingScore> Hours(params int[] scores) =>
        scores.Select((s, i) => new HourlyDryingScore(Weather(Base.AddHours(i)), s, false)).ToList();
}
