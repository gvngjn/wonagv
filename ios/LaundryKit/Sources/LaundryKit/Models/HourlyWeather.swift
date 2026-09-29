import Foundation

/// 한 시간 단위의 날씨 관측/예보 값.
public struct HourlyWeather: Codable, Hashable, Sendable {
    public var date: Date
    /// 기온 (°C)
    public var temperature: Double
    /// 상대습도 (%)
    public var humidity: Double
    /// 강수 확률 (%)
    public var precipitationProbability: Double
    /// 시간당 강수량 (mm)
    public var precipitation: Double
    /// 풍속 (m/s)
    public var windSpeed: Double
    /// 운량 (%)
    public var cloudCover: Double
    /// 낮 시간 여부
    public var isDaytime: Bool

    public init(
        date: Date,
        temperature: Double,
        humidity: Double,
        precipitationProbability: Double,
        precipitation: Double,
        windSpeed: Double,
        cloudCover: Double,
        isDaytime: Bool
    ) {
        self.date = date
        self.temperature = temperature
        self.humidity = humidity
        self.precipitationProbability = precipitationProbability
        self.precipitation = precipitation
        self.windSpeed = windSpeed
        self.cloudCover = cloudCover
        self.isDaytime = isDaytime
    }
}
