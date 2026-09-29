import Charts
import LaundryKit
import SwiftUI

struct HomeView: View {
    @Environment(ForecastViewModel.self) private var model

    var body: some View {
        @Bindable var model = model
        NavigationStack {
            List {
                if let forecast = model.forecast {
                    Section {
                        SummaryCard(forecast: forecast)
                    }
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)

                    Section("추천 시간대") {
                        if forecast.windows.isEmpty {
                            Label("앞으로 3일간 널기 좋은 시간이 없어요", systemImage: "house")
                                .foregroundStyle(.secondary)
                        } else {
                            ForEach(forecast.windows.prefix(3)) { WindowRow(window: $0) }
                        }
                    }

                    Section("시간별 건조 점수") {
                        HourlyChart(hours: forecast.hours)
                            .frame(height: 180)
                            .padding(.vertical, 8)
                    }
                } else if case .failed(let message) = model.state {
                    ContentUnavailableView("불러오지 못했어요", systemImage: "exclamationmark.triangle", description: Text(message))
                } else {
                    HStack { Spacer(); ProgressView("날씨 확인 중…"); Spacer() }
                }

                Section {
                    Picker("계산 방식", selection: $model.scoringMode) {
                        ForEach(ScoringMode.allCases) { Text($0.title).tag($0) }
                    }
                    Toggle("추천 시간 30분 전에 알림", isOn: $model.notificationsEnabled)
                } footer: {
                    Text("기본은 습도만으로 판단해요. 비 오는 시간은 항상 제외돼요.\n날씨 데이터: Open-Meteo.com")
                }
            }
            .navigationTitle("빨래 타이밍")
            .refreshable { await model.refresh() }
            .task { await model.refresh() }
            .overlay(alignment: .top) {
                if case .failed(let message) = model.state, model.forecast != nil {
                    Text(message)
                        .font(.footnote)
                        .padding(8)
                        .background(.red.opacity(0.9), in: Capsule())
                        .foregroundStyle(.white)
                }
            }
        }
    }
}

// MARK: - 요약 카드

private struct SummaryCard: View {
    let forecast: DryingForecast

    var body: some View {
        TimelineView(.everyMinute) { context in
            let current = forecast.current(at: context.date)
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Label(forecast.locationName ?? "현재 위치", systemImage: "location.fill")
                        .font(.subheadline)
                    Spacer()
                    if let current {
                        Image(systemName: current.level.symbolName)
                            .font(.title)
                            .symbolRenderingMode(.multicolor)
                    }
                }

                Text(DryingAdvisor.headline(for: forecast, now: context.date))
                    .font(.title2.bold())

                if let current {
                    HStack(spacing: 20) {
                        Metric(title: "습도", value: "\(Int(current.weather.humidity))%", symbol: "humidity.fill")
                        Metric(title: "기온", value: "\(Int(current.weather.temperature.rounded()))°", symbol: "thermometer.medium")
                        Metric(title: "바람", value: String(format: "%.1fm/s", current.weather.windSpeed), symbol: "wind")
                        Metric(title: "강수", value: "\(Int(current.weather.precipitationProbability))%", symbol: "umbrella.fill")
                    }
                }
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
            .background((current?.level ?? .fair).tint.gradient.opacity(0.25), in: RoundedRectangle(cornerRadius: 20))
        }
    }
}

private struct Metric: View {
    let title: String
    let value: String
    let symbol: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Label(title, systemImage: symbol)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(value).font(.headline.monospacedDigit())
        }
    }
}

// MARK: - 추천 시간대 행

private struct WindowRow: View {
    let window: DryingWindow

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text("\(DryingAdvisor.timeText(window.start)) ~ \(DryingAdvisor.timeText(window.end))")
                    .font(.headline)
                Text("\(window.hours)시간 · 평균 습도 \(Int(window.averageHumidity))%")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Text(window.level.title)
                .font(.caption.bold())
                .padding(.horizontal, 10)
                .padding(.vertical, 4)
                .background(window.level.tint.opacity(0.2), in: Capsule())
                .foregroundStyle(window.level.tint)
        }
    }
}

// MARK: - 시간별 차트

private struct HourlyChart: View {
    let hours: [HourlyDryingScore]

    private var upcoming: [HourlyDryingScore] {
        let start = Date.now.addingTimeInterval(-3600)
        return Array(hours.filter { $0.weather.date > start }.prefix(36))
    }

    var body: some View {
        Chart(upcoming) { hour in
            BarMark(
                x: .value("시간", hour.weather.date, unit: .hour),
                y: .value("점수", hour.score)
            )
            .foregroundStyle(hour.level.tint)

            LineMark(
                x: .value("시간", hour.weather.date, unit: .hour),
                y: .value("습도", hour.weather.humidity)
            )
            .foregroundStyle(.blue.opacity(0.6))
            .lineStyle(StrokeStyle(lineWidth: 1.5, dash: [4, 3]))
        }
        .chartYScale(domain: 0...100)
        .chartXAxis {
            AxisMarks(values: .stride(by: .hour, count: 6)) { _ in
                AxisGridLine()
                AxisValueLabel(format: .dateTime.hour())
            }
        }
        .chartLegend(.hidden)
    }
}

extension DryingLevel {
    var tint: Color {
        switch self {
        case .excellent: .orange
        case .good: .green
        case .fair: .gray
        case .poor: .blue
        }
    }
}

#Preview {
    HomeView().environment(ForecastViewModel())
}
