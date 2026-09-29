import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// [Open-Meteo](https://open-meteo.com) 기반 날씨 공급자.
/// API 키가 필요 없고 비상업적 용도로 무료다.
public struct OpenMeteoProvider: WeatherProvider {
    public var session: URLSession
    public var forecastDays: Int

    public init(session: URLSession = .shared, forecastDays: Int = 3) {
        self.session = session
        self.forecastDays = forecastDays
    }

    public func hourlyForecast(latitude: Double, longitude: Double) async throws -> [HourlyWeather] {
        let (data, response) = try await session.data(from: url(latitude: latitude, longitude: longitude))
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw WeatherError.badResponse(http.statusCode)
        }
        return try Self.parse(data)
    }

    func url(latitude: Double, longitude: Double) -> URL {
        var components = URLComponents(string: "https://api.open-meteo.com/v1/forecast")!
        components.queryItems = [
            .init(name: "latitude", value: String(format: "%.4f", latitude)),
            .init(name: "longitude", value: String(format: "%.4f", longitude)),
            .init(name: "hourly", value: [
                "temperature_2m",
                "relative_humidity_2m",
                "precipitation_probability",
                "precipitation",
                "wind_speed_10m",
                "cloud_cover",
                "is_day",
            ].joined(separator: ",")),
            .init(name: "wind_speed_unit", value: "ms"),
            .init(name: "timeformat", value: "unixtime"),
            .init(name: "timezone", value: "auto"),
            .init(name: "forecast_days", value: String(forecastDays)),
        ]
        return components.url!
    }

    static func parse(_ data: Data) throws -> [HourlyWeather] {
        let decoded = try JSONDecoder().decode(Response.self, from: data)
        let h = decoded.hourly
        let count = h.time.count
        guard [h.temperature_2m.count, h.relative_humidity_2m.count, h.precipitation_probability.count,
               h.precipitation.count, h.wind_speed_10m.count, h.cloud_cover.count, h.is_day.count]
            .allSatisfy({ $0 == count })
        else { throw WeatherError.malformedData }

        return (0..<count).compactMap { i in
            // 값이 비어 있는 시간(null)은 건너뛴다
            guard let temp = h.temperature_2m[i], let humidity = h.relative_humidity_2m[i] else { return nil }
            return HourlyWeather(
                date: Date(timeIntervalSince1970: h.time[i]),
                temperature: temp,
                humidity: humidity,
                precipitationProbability: h.precipitation_probability[i] ?? 0,
                precipitation: h.precipitation[i] ?? 0,
                windSpeed: h.wind_speed_10m[i] ?? 0,
                cloudCover: h.cloud_cover[i] ?? 0,
                isDaytime: (h.is_day[i] ?? 1) == 1
            )
        }
    }

    // swiftlint:disable identifier_name
    struct Response: Decodable {
        struct Hourly: Decodable {
            var time: [TimeInterval]
            var temperature_2m: [Double?]
            var relative_humidity_2m: [Double?]
            var precipitation_probability: [Double?]
            var precipitation: [Double?]
            var wind_speed_10m: [Double?]
            var cloud_cover: [Double?]
            var is_day: [Int?]
        }
        var hourly: Hourly
    }
    // swiftlint:enable identifier_name
}
