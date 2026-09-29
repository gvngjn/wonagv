using static LaundryTime.Core.Tests.Samples;

namespace LaundryTime.Core.Tests;

public class AdvisorTests
{
    [Theory]
    [InlineData(0, 14, "오늘 오후 2시")]
    [InlineData(0, 0, "오늘 오전 12시")]
    [InlineData(0, 12, "오늘 오후 12시")]
    [InlineData(1, 10, "내일(수) 오전 10시")]
    [InlineData(2, 9, "10월 1일(목) 오전 9시")]
    [InlineData(5, 9, "10월 4일(일) 오전 9시")]
    public void TimeText(int dayOffset, int hour, string expected)
    {
        var date = new DateTimeOffset(Base.Date.AddDays(dayOffset).AddHours(hour), Base.Offset);
        Assert.Equal(expected, DryingAdvisor.TimeText(date, Base));
    }

    [Fact]
    public void HeadlineWithoutWindow()
    {
        var forecast = new DryingForecast("서울", Base, [], []);
        Assert.Equal("당분간 실내 건조를 추천해요", DryingAdvisor.Headline(forecast, Base));
    }

    [Fact]
    public void HeadlineForUpcomingAndOngoingWindow()
    {
        var weather = Enumerable.Range(0, 8)
            .Select(i => Weather(Base.AddHours(i), humidity: i is >= 3 and <= 5 ? 40 : 80))
            .ToList();
        var forecast = new DryingAdvisor().CreateForecast(weather, "서울", Base);

        Assert.Equal("오늘 오후 12시에 널어보세요", DryingAdvisor.Headline(forecast, Base));
        Assert.Equal("지금 널기 좋아요! 오늘 오후 3시까지", DryingAdvisor.Headline(forecast, Base.AddHours(4)));
    }

    [Fact]
    public void RangeTextShowsDateOnceForSameDay()
    {
        var start = Base.AddDays(1).AddHours(1);   // 내일 10시
        Assert.Equal("내일(수) 오전 10시 ~ 오후 3시", DryingAdvisor.RangeText(start, start.AddHours(5), Base));
        Assert.Equal("내일(수) 오후 10시 ~ 10월 1일(목) 오전 2시",
            DryingAdvisor.RangeText(start.AddHours(12), start.AddHours(16), Base));
    }

    [Fact]
    public void ClockTextShowsMinutes() =>
        Assert.Equal("오전 7시 30분", DryingAdvisor.ClockText(Base.AddMinutes(-90)));
}

public class ShortHeadlineTests
{
    [Fact]
    public void ShortHeadlineCoversAllStates()
    {
        var b = Samples.Base;
        Assert.Equal("실내 건조", DryingAdvisor.ShortHeadline(new DryingForecast("서울", b, [], []), b));

        var weather = Enumerable.Range(0, 8)
            .Select(i => Samples.Weather(b.AddHours(i), humidity: i is >= 3 and <= 5 ? 40 : 80))
            .ToList();
        var forecast = new DryingAdvisor().CreateForecast(weather, "서울", b);
        Assert.Equal("오늘 오후 12시", DryingAdvisor.ShortHeadline(forecast, b));
        Assert.Equal("지금 널기 OK", DryingAdvisor.ShortHeadline(forecast, b.AddHours(4)));
    }
}
