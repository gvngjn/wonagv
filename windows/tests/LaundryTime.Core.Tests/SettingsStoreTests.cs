namespace LaundryTime.Core.Tests;

public class SettingsStoreTests : IDisposable
{
    private readonly string _dir = Path.Combine(Path.GetTempPath(), "laundrytime-" + Guid.NewGuid());

    [Fact]
    public void RoundTripsSettings()
    {
        var store = new SettingsStore(Path.Combine(_dir, "settings.json"));
        var settings = new AppSettings
        {
            Place = new Place("부산", 35.1, 129.0),
            ScoringMode = ScoringMode.Combined,
            MiniWidgetVisible = true,
            AutoLocation = false,
            UnavailablePeriods =
            [
                new(new TimeOnly(7, 0), new TimeOnly(9, 0), UnavailablePeriod.Weekdays),
                new(new TimeOnly(22, 30), new TimeOnly(6, 0), [DayOfWeek.Friday]),
            ],
        };

        store.Save(settings);

        Assert.Equal(settings, store.Load());
    }

    [Fact]
    public void DefaultsWhenMissingOrCorrupt()
    {
        var path = Path.Combine(_dir, "settings.json");
        var store = new SettingsStore(path);
        Assert.Equal(ScoringMode.HumidityOnly, store.Load().ScoringMode);
        Assert.True(store.Load().AutoLocation);
        Assert.Empty(store.Load().UnavailablePeriods);

        Directory.CreateDirectory(_dir);
        File.WriteAllText(path, "{ not json");
        Assert.Equal(new AppSettings(), store.Load());
    }

    public void Dispose()
    {
        if (Directory.Exists(_dir))
            Directory.Delete(_dir, recursive: true);
    }
}
