import Foundation

/// 날씨 데이터 공급자. WeatherKit 등으로 교체할 수 있도록 프로토콜로 분리.
public protocol WeatherProvider: Sendable {
    func hourlyForecast(latitude: Double, longitude: Double) async throws -> [HourlyWeather]
}

public enum WeatherError: LocalizedError {
    case badResponse(Int)
    case malformedData

    public var errorDescription: String? {
        switch self {
        case .badResponse(let code): "날씨 서버 응답 오류 (\(code))"
        case .malformedData: "날씨 데이터를 해석할 수 없어요"
        }
    }
}
