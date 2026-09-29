import XCTest
@testable import LaundryKit

final class DryingScorerTests: XCTestCase {
    let scorer = DryingScorer(mode: .combined)

    func testDefaultModeIsHumidityOnly() {
        let scorer = DryingScorer()
        XCTAssertEqual(scorer.mode, .humidityOnly)
        XCTAssertEqual(scorer.score(.sample(humidity: 40)).score, 100)
        XCTAssertEqual(scorer.score(.sample(humidity: 62.5)).score, 50)
        XCTAssertEqual(scorer.score(.sample(humidity: 90)).score, 0)
    }

    func testHumidityOnlyIgnoresOtherFactors() {
        let scorer = DryingScorer()
        let calmNight = scorer.score(.sample(humidity: 50, temperature: 5, wind: 0, cloud: 100, isDaytime: false))
        let sunnyDay = scorer.score(.sample(humidity: 50, temperature: 30, wind: 4, cloud: 0, isDaytime: true))
        XCTAssertEqual(calmNight.score, sunnyDay.score)
    }

    func testHumidityOnlyStillBlocksRain() {
        XCTAssertTrue(DryingScorer().score(.sample(humidity: 40, precipitation: 1)).isRainBlocked)
    }

    func testIdealWeatherScoresHigh() {
        let result = scorer.score(.sample(humidity: 35, temperature: 26, wind: 3, cloud: 0))
        XCTAssertEqual(result.score, 100)
        XCTAssertEqual(result.level, .excellent)
    }

    func testHumidAirScoresLow() {
        let dry = scorer.score(.sample(humidity: 40))
        let humid = scorer.score(.sample(humidity: 90))
        XCTAssertGreaterThan(dry.score, humid.score)
        XCTAssertLessThan(humid.score, 60)
    }

    func testRainBlocks() {
        XCTAssertTrue(scorer.score(.sample(precipitation: 0.5)).isRainBlocked)
        XCTAssertTrue(scorer.score(.sample(rainChance: 70)).isRainBlocked)
        XCTAssertEqual(scorer.score(.sample(rainChance: 70)).score, 0)
    }

    func testNightIsWorseThanDay() {
        XCTAssertGreaterThan(
            scorer.score(.sample(isDaytime: true)).score,
            scorer.score(.sample(isDaytime: false)).score
        )
    }

    func testStrongWindPenalized() {
        XCTAssertGreaterThan(scorer.windFactor(4), scorer.windFactor(14))
        XCTAssertGreaterThan(scorer.windFactor(4), scorer.windFactor(0))
    }
}

final class DryingWindowFinderTests: XCTestCase {
    func testFindsBestContiguousWindow() {
        let base = Date(timeIntervalSince1970: 1_800_000_000)
        let scores = [30, 70, 75, 80, 20, 90, 95, 92, 91, 10]
        let hours = scores.enumerated().map { i, s in
            HourlyDryingScore(weather: .sample(date: base.addingTimeInterval(Double(i) * 3600)), score: s, isRainBlocked: false)
        }

        let windows = DryingWindowFinder(minimumScore: 60, minimumHours: 2).windows(in: hours, now: base)

        XCTAssertEqual(windows.count, 2)
        XCTAssertEqual(windows[0].start, base.addingTimeInterval(5 * 3600))
        XCTAssertEqual(windows[0].hours, 4)
        XCTAssertEqual(windows[0].averageScore, 92)
        XCTAssertEqual(windows[1].start, base.addingTimeInterval(1 * 3600))
    }

    func testIgnoresPastHoursAndShortRuns() {
        let base = Date(timeIntervalSince1970: 1_800_000_000)
        let scores = [90, 90, 90, 10, 90, 10]
        let hours = scores.enumerated().map { i, s in
            HourlyDryingScore(weather: .sample(date: base.addingTimeInterval(Double(i) * 3600)), score: s, isRainBlocked: false)
        }
        // 2시간 30분 시점: 0,1시는 지났고 2시만 남아 최소 2시간 미달
        let windows = DryingWindowFinder().windows(in: hours, now: base.addingTimeInterval(2.5 * 3600))
        XCTAssertTrue(windows.isEmpty)
    }
}

final class OpenMeteoParsingTests: XCTestCase {
    func testParsesResponse() throws {
        let json = """
        {"hourly":{"time":[1800000000,1800003600],
        "temperature_2m":[21.5,null],"relative_humidity_2m":[55,60],
        "precipitation_probability":[10,null],"precipitation":[0,0],
        "wind_speed_10m":[2.1,3.0],"cloud_cover":[20,30],"is_day":[1,0]}}
        """
        let hours = try OpenMeteoProvider.parse(Data(json.utf8))
        XCTAssertEqual(hours.count, 1) // 기온이 null인 시간은 제외
        XCTAssertEqual(hours[0].humidity, 55)
        XCTAssertEqual(hours[0].windSpeed, 2.1)
        XCTAssertTrue(hours[0].isDaytime)
    }
}

final class HeadlineTests: XCTestCase {
    func testHeadlineWhenNoWindow() {
        let forecast = DryingForecast(locationName: nil, generatedAt: .now, hours: [], windows: [])
        XCTAssertEqual(DryingAdvisor.headline(for: forecast), "당분간 실내 건조를 추천해요")
    }
}

extension HourlyWeather {
    static func sample(
        date: Date = .now,
        humidity: Double = 50,
        temperature: Double = 20,
        wind: Double = 3,
        cloud: Double = 20,
        rainChance: Double = 0,
        precipitation: Double = 0,
        isDaytime: Bool = true
    ) -> HourlyWeather {
        HourlyWeather(
            date: date, temperature: temperature, humidity: humidity,
            precipitationProbability: rainChance, precipitation: precipitation,
            windSpeed: wind, cloudCover: cloud, isDaytime: isDaytime
        )
    }
}
