using static LaundryTime.Core.Tests.Samples;

namespace LaundryTime.Core.Tests;

public class UnavailablePeriodTests
{
    // Samples.Base = 2026-09-29(화) 09:00 +09:00
    private static DateTimeOffset At(int dayOffset, int hour, int minute = 0) =>
        new(Base.Date.AddDays(dayOffset).AddHours(hour).AddMinutes(minute), Base.Offset);

    private static readonly UnavailablePeriod Commute = new(new(7, 0), new(9, 0), UnavailablePeriod.Weekdays);

    [Fact]
    public void ContainsRespectsTimeAndWeekday()
    {
        Assert.True(Commute.Contains(At(0, 7)));        // 화 07:00
        Assert.True(Commute.Contains(At(0, 8, 59)));
        Assert.False(Commute.Contains(At(0, 9)));       // 끝 시각은 제외
        Assert.False(Commute.Contains(At(0, 6, 59)));
        Assert.False(Commute.Contains(At(4, 8)));       // 토요일
    }

    [Fact]
    public void OvernightPeriodUsesStartDay()
    {
        var night = new UnavailablePeriod(new(22, 0), new(6, 0), [DayOfWeek.Friday]);
        Assert.True(night.Contains(At(3, 23)));   // 금 23:00
        Assert.True(night.Contains(At(4, 5)));    // 토 05:00 (금요일 밤에 시작)
        Assert.False(night.Contains(At(4, 23)));  // 토 23:00
        Assert.False(night.Contains(At(3, 5)));   // 금 05:00 (목요일 밤)
    }

    [Theory]
    [InlineData(new[] { DayOfWeek.Monday, DayOfWeek.Tuesday, DayOfWeek.Wednesday, DayOfWeek.Thursday, DayOfWeek.Friday }, "평일")]
    [InlineData(new[] { DayOfWeek.Sunday, DayOfWeek.Saturday }, "주말")]
    [InlineData(new[] { DayOfWeek.Wednesday, DayOfWeek.Monday }, "월·수")]
    public void DaysText(DayOfWeek[] days, string expected) =>
        Assert.Equal(expected, UnavailablePeriod.DaysText(days));

    [Fact]
    public void Description() => Assert.Equal("평일 07:00~09:00", Commute.Description);

    [Fact]
    public void WindowStartingInBlockedTimeIsTrimmed()
    {
        // 06시부터 좋은 날씨, 07~09시 출근: 06시에 널 수 있으므로 그대로 06시 시작
        var from6 = HoursFrom(At(0, 6), 90, 90, 90, 90, 90, 90);
        var finder = new DryingWindowFinder { Unavailable = [Commute] };
        Assert.Equal(At(0, 6), Assert.Single(finder.FindWindows(from6, At(0, 5))).Start);

        // 07시부터 좋은 날씨: 07·08시는 널 수 없으니 09시 시작
        var from7 = HoursFrom(At(0, 7), 90, 90, 90, 90, 90);
        var window = Assert.Single(finder.FindWindows(from7, At(0, 5)));
        Assert.Equal(At(0, 9), window.Start);
        Assert.Equal(3, window.Hours);
    }

    [Fact]
    public void TrimmedWindowShorterThanMinimumIsDropped()
    {
        var hours = HoursFrom(At(0, 7), 90, 90, 90, 10);
        var finder = new DryingWindowFinder { Unavailable = [Commute] };
        Assert.Empty(finder.FindWindows(hours, At(0, 5)));
    }

    [Fact]
    public void OngoingWindowUsesCurrentTime()
    {
        // 06시부터 좋은 날씨지만 지금은 07:30 (출근 중) → 09시부터 추천
        var hours = HoursFrom(At(0, 6), 90, 90, 90, 90, 90, 90);
        var finder = new DryingWindowFinder { Unavailable = [Commute] };
        Assert.Equal(At(0, 9), Assert.Single(finder.FindWindows(hours, At(0, 7, 30))).Start);
    }

    [Fact]
    public void WeekendIsNotBlocked()
    {
        var saturday = HoursFrom(At(4, 7), 90, 90, 90);
        var finder = new DryingWindowFinder { Unavailable = [Commute] };
        Assert.Equal(At(4, 7), Assert.Single(finder.FindWindows(saturday, At(4, 5))).Start);
    }

    private static List<HourlyDryingScore> HoursFrom(DateTimeOffset start, params int[] scores) =>
        scores.Select((s, i) => new HourlyDryingScore(Weather(start.AddHours(i)), s, false)).ToList();
}
