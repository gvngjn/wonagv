# 🧺 빨래 타이밍 (LaundryTime)

현재 위치의 **습도 · 기온 · 햇빛 · 바람 · 강수 예보**를 분석해 빨래 널기 좋은 시간을 알려주는 iPhone 앱입니다.
위젯과 Apple Watch 확장을 염두에 두고 핵심 로직을 별도 Swift 패키지로 분리했습니다.

## 기능
- 현재 위치 기반 3일치 시간별 날씨 조회 ([Open-Meteo](https://open-meteo.com), API 키 불필요)
- 시간별 **건조 점수(0~100)** 계산 및 "최고 / 좋음 / 보통 / 비추천" 등급
- 연속으로 널기 좋은 **추천 시간대** 찾기 (예: "오후 1시에 널어보세요")
- 시간별 점수 + 습도 차트 (Swift Charts)
- 추천 시간 30분 전 **로컬 알림**
- 마지막 예보를 App Group 저장소에 공유 → 위젯이 바로 읽을 수 있음

## 프로젝트 구조
```
LaundryKit/                 ← 앱 · 위젯 · 워치 공용 Swift 패키지 (UI 의존성 없음)
  Models/                   HourlyWeather, DryingForecast, DryingWindow, DryingLevel
  Scoring/                  DryingScorer(점수), DryingWindowFinder(구간), DryingAdvisor(문구)
  Weather/                  WeatherProvider 프로토콜, OpenMeteoProvider
  Storage/                  ForecastStore (App Group UserDefaults)
  Tests/                    단위 테스트
App/Sources/                ← iPhone 앱 (SwiftUI, iOS 17+)
  HomeView, ForecastViewModel, LocationProvider, NotificationScheduler
project.yml                 ← XcodeGen 프로젝트 정의
```

## 건조 점수 계산 방식
| 요소 | 가중치 | 만점 기준 |
|---|---|---|
| 습도 | 45% | 40% 이하 만점, 85% 이상 0점 |
| 기온 | 20% | 25°C 이상 만점, 5°C 이하 0점 |
| 햇빛 | 20% | 낮 + 맑음 만점, 밤 0점 |
| 바람 | 15% | 2~7 m/s 만점, 무풍·강풍 감점 |

- 강수량 0.1mm 이상 또는 강수 확률 60% 이상이면 **무조건 0점**(차단)
- 강수 확률 20%부터 점진적으로 감점
- 60점 이상이 2시간 이상 이어지는 구간을 "추천 시간대"로 표시

가중치와 기준값은 `DryingScorer`에서 조정할 수 있습니다.

## 실행 방법 (macOS + Xcode 15 이상)
```bash
brew install xcodegen
xcodegen generate
open LaundryTime.xcodeproj
```
1. `LaundryTime` 타깃 → Signing & Capabilities 에서 본인 Team 선택
2. 필요하면 번들 ID(`com.example.laundrytime`)를 본인 것으로 변경
3. 실행 (시뮬레이터에서는 Features > Location 으로 위치 지정)

공용 로직 테스트만 돌리려면: `cd LaundryKit && swift test`

## 다음 단계: 위젯 & Apple Watch
### 위젯 (WidgetKit)
1. `project.yml`에 `app-extension` 타깃을 추가하고 `LaundryKit` 의존성 연결
2. 앱과 위젯 **양쪽에 App Groups capability** 추가 → `group.com.example.laundrytime`
   (ID를 바꾸면 `ForecastStore.appGroupID`도 같이 변경. 유료 개발자 계정 필요)
3. `TimelineProvider`에서 `ForecastStore().load()`로 예보를 읽고,
   `forecast.hours` 각 시간을 타임라인 엔트리로 만들면 네트워크 없이도 시간별로 갱신됨
4. 앱은 이미 새 예보를 저장할 때 `WidgetCenter.shared.reloadAllTimelines()`를 호출함

### Apple Watch
- 워치 앱 타깃에 `LaundryKit`을 연결하면 `OpenMeteoProvider` + `DryingAdvisor`로 **워치 단독 조회** 가능
- 또는 `WatchConnectivity`로 iPhone의 `DryingForecast`(Codable)를 그대로 전송
- 컴플리케이션은 위젯과 같은 WidgetKit 코드를 `accessoryCircular` / `accessoryRectangular` 패밀리로 재사용

### 기타 아이디어
- WeatherKit으로 교체: `WeatherProvider`를 구현하는 `WeatherKitProvider` 추가
- 실내 건조 모드, 이불/두꺼운 옷 등 빨래 종류별 필요 시간 설정
- 백그라운드 새로고침(`BGAppRefreshTask`)으로 알림 정확도 향상
