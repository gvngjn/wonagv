import SwiftUI

@main
struct LaundryTimeApp: App {
    @State private var model = ForecastViewModel()

    var body: some Scene {
        WindowGroup {
            HomeView()
                .environment(model)
        }
    }
}
