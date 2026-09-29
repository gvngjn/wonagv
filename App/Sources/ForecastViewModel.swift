import Foundation
import LaundryKit
import Observation
import WidgetKit

@MainActor
@Observable
final class ForecastViewModel {
    enum State {
        case idle
        case loading
        case loaded
        case failed(String)
    }

    private(set) var state: State = .idle
    private(set) var forecast: DryingForecast?

    var notificationsEnabled: Bool {
        didSet {
            UserDefaults.standard.set(notificationsEnabled, forKey: "notificationsEnabled")
            Task { await updateNotifications() }
        }
    }

    private let provider: WeatherProvider
    private let advisor = DryingAdvisor()
    private let store = ForecastStore()
    private let location = LocationProvider()

    init(provider: WeatherProvider = OpenMeteoProvider()) {
        self.provider = provider
        self.notificationsEnabled = UserDefaults.standard.bool(forKey: "notificationsEnabled")
        // 네트워크 응답 전까지 마지막 예보를 먼저 보여준다
        self.forecast = store.load()
    }

    func refresh() async {
        state = .loading
        do {
            let place = await location.currentPlace()
            let weather = try await provider.hourlyForecast(
                latitude: place.coordinate.latitude,
                longitude: place.coordinate.longitude
            )
            let forecast = advisor.forecast(for: weather, locationName: place.name)
            self.forecast = forecast
            state = .loaded

            // 위젯이 읽을 수 있도록 공유 저장소에 저장하고 타임라인 갱신
            try? store.save(forecast)
            WidgetCenter.shared.reloadAllTimelines()
            await updateNotifications()
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    private func updateNotifications() async {
        guard notificationsEnabled else {
            NotificationScheduler.cancel()
            return
        }
        guard await NotificationScheduler.requestAuthorization() else {
            notificationsEnabled = false
            return
        }
        if let forecast {
            await NotificationScheduler.schedule(for: forecast)
        }
    }
}
