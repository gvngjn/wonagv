namespace LaundryTime.Core.Tests;

public class LocationLookupTests
{
    [Fact]
    public void ParsesCityAndLocality()
    {
        const string json = """
        {"latitude":37.5729,"longitude":126.9794,"city":"서울특별시","locality":"종로구","principalSubdivision":"서울특별시"}
        """;
        var place = LocationLookupClient.Parse(json);
        Assert.Equal("서울특별시 종로구", place.Name);
        Assert.Equal(37.5729, place.Latitude);
    }

    [Fact]
    public void FallsBackToSubdivisionThenGenericName()
    {
        Assert.Equal("경기도", LocationLookupClient.Parse("""{"latitude":37.2,"longitude":127.0,"city":"","principalSubdivision":"경기도"}""").Name);
        Assert.Equal("현재 위치", LocationLookupClient.Parse("""{"latitude":37.2,"longitude":127.0}""").Name);
    }

    [Fact]
    public void RejectsEmptyCoordinates() =>
        Assert.Throws<FormatException>(() => LocationLookupClient.Parse("""{"latitude":0,"longitude":0}"""));
}
