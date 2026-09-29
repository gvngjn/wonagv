using static LaundryTime.Core.Tests.Samples;

namespace LaundryTime.Core.Tests;

public class AdvisorTests
{
    [Theory]
    [InlineData(0, 14, "오후 2시")]
    [InlineData(0, 0, "오전 12시")]
    [InlineData(0, 12, "오후 12시")]
    [InlineData(1, 10, "내일 오전 10시")]
    [InlineData(2, 9, "모레 오전 9시")]
    [InlineData(3, 9, "3일 뒤 오전 9시")]
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

        Assert.Equal("오후 12시에 널어보세요", DryingAdvisor.Headline(forecast, Base));
        Assert.Equal("지금 널기 좋아요! 오후 3시까지", DryingAdvisor.Headline(forecast, Base.AddHours(4)));
    }
}
