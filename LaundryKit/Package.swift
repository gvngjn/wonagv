// swift-tools-version:5.9
import PackageDescription

// 앱 · 위젯 · 애플워치가 함께 쓰는 공용 로직.
// UI 의존성이 없으므로 어떤 타깃에서도 그대로 링크할 수 있다.
let package = Package(
    name: "LaundryKit",
    platforms: [
        .iOS(.v17),
        .watchOS(.v10),
        .macOS(.v14),
    ],
    products: [
        .library(name: "LaundryKit", targets: ["LaundryKit"]),
    ],
    targets: [
        .target(name: "LaundryKit"),
        .testTarget(name: "LaundryKitTests", dependencies: ["LaundryKit"]),
    ]
)
