using static LaundryTime.Core.Tests.Samples;

namespace LaundryTime.Core.Tests;

public class DryingWindowFinderTests
{
    [Fact]
    public void FindsContiguousWindowsSortedByScore()
    {
        var hours = Hours(30, 70, 75, 80, 20, 90, 95, 92, 91, 10);

        var windows = new DryingWindowFinder().FindWindows(hours, Base);

        Assert.Equal(2, windows.Count);
        Assert.Equal(Base.AddHours(5), windows[0].Start);
        Assert.Equal(Base.AddHours(9), windows[0].End);
        Assert.Equal(4, windows[0].Hours);
        Assert.Equal(92, windows[0].AverageScore);
        Assert.Equal(Base.AddHours(1), windows[1].Start);
    }

    [Fact]
    public void IgnoresPastHoursAndShortRuns()
    {
        var hours = Hours(90, 90, 90, 10, 90, 10);
        // 2시 30분: 0·1시는 지났고 2시만 남아 최소 2시간 미달
        var windows = new DryingWindowFinder().FindWindows(hours, Base.AddMinutes(150));
        Assert.Empty(windows);
    }

    [Fact]
    public void BreaksWindowOnTimeGap()
    {
        var hours = Hours(90, 90);
        hours.Add(new HourlyDryingScore(Weather(Base.AddHours(5)), 90, false));
        hours.Add(new HourlyDryingScore(Weather(Base.AddHours(6)), 90, false));

        var windows = new DryingWindowFinder().FindWindows(hours, Base);

        Assert.Equal(2, windows.Count);
        Assert.All(windows, w => Assert.Equal(2, w.Hours));
    }
}
