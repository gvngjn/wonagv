import CoreLocation

/// 현재 위치를 한 번 받아오는 간단한 async 래퍼.
@MainActor
final class LocationProvider: NSObject, CLLocationManagerDelegate {
    struct Place {
        var coordinate: CLLocationCoordinate2D
        var name: String?
    }

    /// 위치 권한이 없을 때 사용할 기본 위치 (서울 시청)
    static let fallback = Place(coordinate: .init(latitude: 37.5665, longitude: 126.9780), name: "서울")

    private let manager = CLLocationManager()
    private var continuation: CheckedContinuation<CLLocation?, Never>?

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyKilometer
    }

    func currentPlace() async -> Place {
        guard let location = await requestLocation() else { return Self.fallback }
        let name = try? await CLGeocoder().reverseGeocodeLocation(location).first
            .flatMap { $0.subLocality ?? $0.locality ?? $0.administrativeArea }
        return Place(coordinate: location.coordinate, name: name)
    }

    private func requestLocation() async -> CLLocation? {
        switch manager.authorizationStatus {
        case .denied, .restricted:
            return nil
        default:
            break
        }
        // 이전 요청이 남아 있으면 정리
        continuation?.resume(returning: nil)
        return await withCheckedContinuation { continuation in
            self.continuation = continuation
            if manager.authorizationStatus == .notDetermined {
                manager.requestWhenInUseAuthorization()
            } else {
                manager.requestLocation()
            }
        }
    }

    private func finish(_ location: CLLocation?) {
        continuation?.resume(returning: location)
        continuation = nil
    }

    // MARK: - CLLocationManagerDelegate

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        Task { @MainActor in
            guard self.continuation != nil else { return }
            switch manager.authorizationStatus {
            case .authorizedWhenInUse, .authorizedAlways:
                manager.requestLocation()
            case .denied, .restricted:
                self.finish(nil)
            default:
                break
            }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        Task { @MainActor in self.finish(locations.last) }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor in self.finish(nil) }
    }
}
