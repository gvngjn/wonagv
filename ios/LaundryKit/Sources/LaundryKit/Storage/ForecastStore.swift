import Foundation

/// 마지막으로 계산한 예보를 App Group 공유 저장소에 보관한다.
///
/// 앱이 저장하면 같은 App Group을 쓰는 위젯 익스텐션이 그대로 읽을 수 있다.
/// (애플워치는 별도 기기이므로 WatchConnectivity로 전달하거나 직접 조회한다.)
public struct ForecastStore: Sendable {
    /// Xcode의 Signing & Capabilities > App Groups 에 등록한 ID와 같아야 한다.
    public static let appGroupID = "group.com.example.laundrytime"
    static let key = "latestDryingForecast"

    private let suiteName: String?

    public init(suiteName: String? = ForecastStore.appGroupID) {
        self.suiteName = suiteName
    }

    private var defaults: UserDefaults {
        suiteName.flatMap(UserDefaults.init(suiteName:)) ?? .standard
    }

    public func save(_ forecast: DryingForecast) throws {
        defaults.set(try JSONEncoder().encode(forecast), forKey: Self.key)
    }

    public func load() -> DryingForecast? {
        guard let data = defaults.data(forKey: Self.key) else { return nil }
        return try? JSONDecoder().decode(DryingForecast.self, from: data)
    }
}
