using static LaundryTime.Core.Tests.Samples;

namespace LaundryTime.Core.Tests;

public class DryingScorerTests
{
    [Fact]
    public void DefaultModeIsHumidityOnly()
    {
        var scorer = new DryingScorer();
        Assert.Equal(ScoringMode.HumidityOnly, scorer.Mode);
        Assert.Equal(100, scorer.Score(Weather(humidity: 40)).Score);
        Assert.Equal(50, scorer.Score(Weather(humidity: 62.5)).Score);
        Assert.Equal(0, scorer.Score(Weather(humidity: 90)).Score);
    }

    [Fact]
    public void HumidityOnlyIgnoresOtherFactors()
    {
        var scorer = new DryingScorer();
        var calmNight = scorer.Score(Weather(humidity: 50, temperature: 5, wind: 0, cloud: 100, isDaytime: false));
        var sunnyDay = scorer.Score(Weather(humidity: 50, temperature: 30, wind: 4, cloud: 0, isDaytime: true));
        Assert.Equal(calmNight.Score, sunnyDay.Score);
    }

    [Theory]
    [InlineData(ScoringMode.HumidityOnly)]
    [InlineData(ScoringMode.Combined)]
    public void RainIsBlockedInEveryMode(ScoringMode mode)
    {
        var scorer = new DryingScorer { Mode = mode };
        Assert.True(scorer.Score(Weather(humidity: 40, precipitation: 0.5)).IsRainBlocked);
        var likelyRain = scorer.Score(Weather(humidity: 40, rainChance: 70));
        Assert.True(likelyRain.IsRainBlocked);
        Assert.Equal(0, likelyRain.Score);
    }

    [Fact]
    public void CombinedIdealWeatherScores100()
    {
        var scorer = new DryingScorer { Mode = ScoringMode.Combined };
        var result = scorer.Score(Weather(humidity: 35, temperature: 26, wind: 3, cloud: 0));
        Assert.Equal(100, result.Score);
        Assert.Equal(DryingLevel.Excellent, result.Level);
    }

    [Fact]
    public void CombinedPrefersDayOverNight()
    {
        var scorer = new DryingScorer { Mode = ScoringMode.Combined };
        Assert.True(scorer.Score(Weather(isDaytime: true)).Score > scorer.Score(Weather(isDaytime: false)).Score);
    }

    [Fact]
    public void WindFactorPenalizesCalmAndStorm()
    {
        Assert.True(DryingScorer.WindFactor(4) > DryingScorer.WindFactor(0));
        Assert.True(DryingScorer.WindFactor(4) > DryingScorer.WindFactor(14));
    }
}
