import Foundation
import LaundryKit
import UserNotifications

/// 다음 추천 시간대 시작 전에 로컬 알림을 예약한다.
enum NotificationScheduler {
    private static let identifier = "next-drying-window"
    /// 시작 몇 분 전에 알릴지
    static let leadTime: TimeInterval = 30 * 60

    static func requestAuthorization() async -> Bool {
        (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])) ?? false
    }

    static func schedule(for forecast: DryingForecast, now: Date = .now) async {
        let center = UNUserNotificationCenter.current()
        center.removePendingNotificationRequests(withIdentifiers: [identifier])

        guard let window = forecast.nextWindow(after: now) else { return }
        let fireDate = window.start.addingTimeInterval(-leadTime)
        guard fireDate > now else { return }

        let content = UNMutableNotificationContent()
        content.title = "곧 빨래 널기 좋은 시간이에요 🧺"
        content.body = "\(DryingAdvisor.timeText(window.start, now: fireDate))부터 \(window.hours)시간, "
            + "평균 습도 \(Int(window.averageHumidity))% (\(window.level.title))"
        content.sound = .default

        let components = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: fireDate)
        let trigger = UNCalendarNotificationTrigger(dateMatching: components, repeats: false)
        try? await center.add(UNNotificationRequest(identifier: identifier, content: content, trigger: trigger))
    }

    static func cancel() {
        UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: [identifier])
    }
}
