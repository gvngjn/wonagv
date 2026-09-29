# 🧺 빨래 타이밍 (LaundryTime)

지역의 **습도 예보**를 확인해 빨래 널기 좋은 시간을 알려주는 **Windows 데스크톱 앱**입니다.

| 폴더 | 내용 |
|---|---|
| [`windows/`](windows/) | **Windows 앱 (C# / WPF, .NET 8)** — 현재 주력 |
| [`ios/`](ios/) | iPhone 앱 초기 버전 (SwiftUI, Mac + Xcode 필요) |

## 기능
- 3일치 시간별 날씨 조회 ([Open-Meteo](https://open-meteo.com), API 키 불필요)
- **습도만으로 판단하는 건조 점수 (기본값)** — 습도 40% 이하 100점, 85% 이상 0점
  - 설정에서 "종합(습도·기온·햇빛·바람)" 방식으로 변경 가능
  - 비가 오거나 강수 확률 60% 이상인 시간은 항상 제외
- 60점 이상(습도 약 58% 이하)이 2시간 이상 이어지는 **추천 시간대** 표시
  - "오늘 오후 2시", "내일(수) 오전 10시", "10월 1일(목) 오전 9시"처럼 요일·날짜로 안내
- 48시간 **시간별 점수 차트** (마우스를 올리면 습도 표시)
- **현재 위치 자동 갱신** — Windows 위치 서비스(Wi-Fi·GPS)를 쓰고, 꺼져 있으면 인터넷 연결 기준 대략 위치 사용
  (지역 이름 조회: [BigDataCloud](https://www.bigdatacloud.com) 무료 API)
- 직접 지역 검색도 가능 (예: "수원", "부산 해운대") — 고르면 자동 위치는 꺼짐
- **빨래 못 너는 시간 설정** — 예: 평일 07:00~09:00 출근 시간
  - 그 시간에는 널기를 추천하지 않음 (추천 시간대 시작을 뒤로 미룸)
  - 그 전에 널어 둔 빨래는 계속 마르는 것으로 계산 (예: 06시에 널고 출근 OK)
  - 자정을 넘기는 시간대(22:00~06:00)와 요일 선택 지원
- 추천 시간 30분 전 **Windows 알림** (창을 닫아도 트레이에서 계속 동작)
- 항상 위에 뜨는 **바탕화면 미니 위젯** (드래그로 이동, 더블클릭으로 열기)
- 트레이 아이콘 색이 현재 상태를 표시 (주황 최고 · 초록 좋음 · 회색 보통 · 파랑 비추천)
- Windows 시작 시 자동 실행 옵션

## 설치 (빌드된 exe 받기)
1. GitHub 저장소 → **Actions** 탭 → "Windows 앱 빌드" 최신 실행 선택
2. 아래 **Artifacts** 에서 `LaundryTime-win-x64` 다운로드 → 압축 해제
3. `LaundryTime.exe` 실행 (.NET 설치 불필요)

> 서명되지 않은 exe라 처음 실행 시 SmartScreen 경고가 뜰 수 있어요 → "추가 정보" → "실행".

> Windows 위치를 쓰려면 **설정 → 개인 정보 및 보안 → 위치**에서 "위치 서비스"와
> "데스크톱 앱이 위치에 액세스하도록 허용"을 켜 주세요. 꺼져 있으면 대략 위치를 씁니다.

## 직접 빌드
[.NET 8 SDK](https://dotnet.microsoft.com/download/dotnet/8.0) 설치 후:
```powershell
cd windows
dotnet run --project src/LaundryTime.App          # 바로 실행
dotnet test                                       # 테스트
dotnet publish src/LaundryTime.App -c Release -r win-x64 --self-contained -p:PublishSingleFile=true -o publish
```
Visual Studio 2022에서는 `windows/LaundryTime.sln`을 열면 됩니다.

## 구조
```
windows/
  src/LaundryTime.Core/     ← UI 없는 핵심 로직 (Linux/macOS에서도 빌드·테스트 가능)
    DryingScorer            점수 계산 (습도만 / 종합)
    DryingWindowFinder      연속 추천 시간대 찾기
    DryingAdvisor           "오후 2시에 널어보세요" 문구
    UnavailablePeriod       빨래 못 너는 시간대
    OpenMeteoClient         날씨 · 지역 검색 API
    LocationLookupClient    좌표 → 지역 이름, IP 기반 대략 위치
    AppSettings             설정 저장 (%APPDATA%\LaundryTime\settings.json)
  src/LaundryTime.App/      ← WPF 앱
    Views/                  메인 창, 미니 위젯
    ViewModels/             MainViewModel
    Services/               트레이 아이콘 · 알림, 자동 실행, 현재 위치
  tests/LaundryTime.Core.Tests/   xUnit 테스트
```
