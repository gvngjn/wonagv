using System.Collections.ObjectModel;
using System.Net.Http;
using System.Windows.Media;
using System.Windows.Threading;
using LaundryTime.App.Services;
using LaundryTime.Core;

namespace LaundryTime.App.ViewModels;

public sealed class MainViewModel : ObservableObject
{
    private static readonly TimeSpan RefreshInterval = TimeSpan.FromMinutes(30);

    private readonly OpenMeteoClient _client;
    private readonly SettingsStore _store;
    private readonly DispatcherTimer _clock;
    private AppSettings _settings;
    private IReadOnlyList<HourlyWeather>? _weather;
    private DateTimeOffset _lastFetch = DateTimeOffset.MinValue;
    private DateTimeOffset? _notifiedWindowStart;

    public MainViewModel(OpenMeteoClient client, SettingsStore store)
    {
        _client = client;
        _store = store;
        _settings = store.Load();

        RefreshCommand = new AsyncCommand(RefreshAsync);
        SearchCommand = new AsyncCommand(SearchAsync);

        // 1분마다 문구 · 알림 갱신, 30분마다 날씨 재조회
        _clock = new DispatcherTimer { Interval = TimeSpan.FromMinutes(1) };
        _clock.Tick += async (_, _) =>
        {
            if (DateTimeOffset.Now - _lastFetch >= RefreshInterval)
                await RefreshAsync();
            else
                UpdateDisplay();
        };
    }

    /// <summary>추천 시간대가 다가오면 발생 (제목, 내용).</summary>
    public event Action<string, string>? NotificationRequested;
    /// <summary>미니 위젯 표시 여부가 바뀌면 발생.</summary>
    public event Action<bool>? MiniWidgetVisibilityChanged;

    public AsyncCommand RefreshCommand { get; }
    public AsyncCommand SearchCommand { get; }

    public DryingForecast? Forecast { get; private set; }

    // ── 표시용 속성 ─────────────────────────────────────────

    private string _headline = "날씨 확인 중…";
    public string Headline { get => _headline; private set => Set(ref _headline, value); }

    public string LocationName => _settings.Place.Name;

    private string _humidityText = "–";
    public string HumidityText { get => _humidityText; private set => Set(ref _humidityText, value); }

    private string _temperatureText = "–";
    public string TemperatureText { get => _temperatureText; private set => Set(ref _temperatureText, value); }

    private string _windText = "–";
    public string WindText { get => _windText; private set => Set(ref _windText, value); }

    private string _rainText = "–";
    public string RainText { get => _rainText; private set => Set(ref _rainText, value); }

    private string _levelTitle = "";
    public string LevelTitle { get => _levelTitle; private set => Set(ref _levelTitle, value); }

    private DryingLevel _level = DryingLevel.Fair;
    public DryingLevel Level { get => _level; private set { if (Set(ref _level, value)) OnPropertyChanged(nameof(LevelBrush)); } }
    public Brush LevelBrush => LevelStyle.BrushOf(Level);

    private string _updatedText = "";
    public string UpdatedText { get => _updatedText; private set => Set(ref _updatedText, value); }

    private string? _errorMessage;
    public string? ErrorMessage { get => _errorMessage; private set => Set(ref _errorMessage, value); }

    private bool _isLoading;
    public bool IsLoading { get => _isLoading; private set => Set(ref _isLoading, value); }

    public ObservableCollection<WindowItem> Windows { get; } = [];
    public ObservableCollection<HourBar> HourBars { get; } = [];

    private bool _hasNoWindows;
    public bool HasNoWindows { get => _hasNoWindows; private set => Set(ref _hasNoWindows, value); }

    // ── 설정 ────────────────────────────────────────────────

    public ScoringModeOption[] ScoringModes => ScoringModeOption.All;

    public ScoringModeOption SelectedScoringMode
    {
        get => ScoringModes.First(m => m.Mode == _settings.ScoringMode);
        set
        {
            if (value is null || value.Mode == _settings.ScoringMode) return;
            Save(_settings with { ScoringMode = value.Mode });
            OnPropertyChanged();
            Recalculate();
        }
    }

    public bool NotificationsEnabled
    {
        get => _settings.NotificationsEnabled;
        set { Save(_settings with { NotificationsEnabled = value }); OnPropertyChanged(); }
    }

    public bool MiniWidgetVisible
    {
        get => _settings.MiniWidgetVisible;
        set
        {
            if (value == _settings.MiniWidgetVisible) return;
            Save(_settings with { MiniWidgetVisible = value });
            OnPropertyChanged();
            MiniWidgetVisibilityChanged?.Invoke(value);
        }
    }

    public bool RunAtStartup
    {
        get => StartupRegistration.IsEnabled;
        set { StartupRegistration.SetEnabled(value); OnPropertyChanged(); }
    }

    public (double? Left, double? Top) MiniWidgetPosition
    {
        get => (_settings.MiniWidgetLeft, _settings.MiniWidgetTop);
        set => Save(_settings with { MiniWidgetLeft = value.Left, MiniWidgetTop = value.Top });
    }

    // ── 지역 검색 ───────────────────────────────────────────

    private string _searchQuery = "";
    public string SearchQuery { get => _searchQuery; set => Set(ref _searchQuery, value); }

    public ObservableCollection<Place> SearchResults { get; } = [];

    private string? _searchMessage;
    public string? SearchMessage { get => _searchMessage; private set => Set(ref _searchMessage, value); }

    public Place? SelectedPlace
    {
        get => null;
        set
        {
            if (value is null) return;
            Save(_settings with { Place = value });
            OnPropertyChanged(nameof(LocationName));
            SearchResults.Clear();
            SearchQuery = "";
            SearchMessage = null;
            _notifiedWindowStart = null;
            RefreshCommand.Execute(null);
        }
    }

    // ── 동작 ────────────────────────────────────────────────

    public void Start()
    {
        _clock.Start();
        RefreshCommand.Execute(null);
    }

    public async Task RefreshAsync()
    {
        IsLoading = true;
        ErrorMessage = null;
        try
        {
            var place = _settings.Place;
            _weather = await _client.GetHourlyForecastAsync(place.Latitude, place.Longitude);
            _lastFetch = DateTimeOffset.Now;
            Recalculate();
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException)
        {
            ErrorMessage = "날씨를 불러오지 못했어요. 인터넷 연결을 확인해 주세요.";
            _lastFetch = DateTimeOffset.Now - RefreshInterval + TimeSpan.FromMinutes(5); // 5분 뒤 재시도
        }
        catch (FormatException e)
        {
            ErrorMessage = e.Message;
        }
        finally
        {
            IsLoading = false;
        }
    }

    private async Task SearchAsync()
    {
        SearchResults.Clear();
        SearchMessage = null;
        if (string.IsNullOrWhiteSpace(SearchQuery)) return;
        try
        {
            var places = await _client.SearchPlacesAsync(SearchQuery);
            foreach (var p in places) SearchResults.Add(p);
            if (places.Count == 0) SearchMessage = "검색 결과가 없어요. 시·군·구 이름으로 검색해 보세요.";
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException)
        {
            SearchMessage = "검색하지 못했어요. 인터넷 연결을 확인해 주세요.";
        }
    }

    /// <summary>가지고 있는 날씨로 점수를 다시 계산 (계산 방식 변경 시 재조회 불필요).</summary>
    private void Recalculate()
    {
        if (_weather is null) return;
        var advisor = new DryingAdvisor { Scorer = new DryingScorer { Mode = _settings.ScoringMode } };
        Forecast = advisor.CreateForecast(_weather, _settings.Place.Name, DateTimeOffset.Now);
        UpdateDisplay();
    }

    private void UpdateDisplay()
    {
        var forecast = Forecast;
        if (forecast is null) return;
        var now = DateTimeOffset.Now;

        Headline = DryingAdvisor.Headline(forecast, now);
        if (forecast.Current(now) is { } current)
        {
            var w = current.Weather;
            HumidityText = $"{w.Humidity:0}%";
            TemperatureText = $"{w.Temperature:0}°";
            WindText = $"{w.WindSpeed:0.0}m/s";
            RainText = $"{w.PrecipitationProbability:0}%";
            Level = current.Level;
            LevelTitle = current.IsRainBlocked ? "비 예보" : $"지금 {current.Level.Title()}";
        }
        UpdatedText = $"{forecast.GeneratedAt.ToLocalTime():HH:mm} 업데이트";

        Windows.Clear();
        foreach (var w in forecast.Windows.Where(w => w.End > now).Take(4))
            Windows.Add(WindowItem.From(w, now));
        HasNoWindows = Windows.Count == 0;

        HourBars.Clear();
        foreach (var h in forecast.Hours.Where(h => h.Weather.Time > now.AddHours(-1)).Take(48))
            HourBars.Add(HourBar.From(h, now));

        CheckNotification(forecast, now);
    }

    private void CheckNotification(DryingForecast forecast, DateTimeOffset now)
    {
        if (!_settings.NotificationsEnabled) return;
        var window = forecast.NextWindow(now);
        if (window is null || window.Start <= now || window.Start == _notifiedWindowStart) return;
        if (now < window.Start.AddMinutes(-_settings.NotifyLeadMinutes)) return;

        _notifiedWindowStart = window.Start;
        NotificationRequested?.Invoke(
            "곧 빨래 널기 좋은 시간이에요",
            $"{DryingAdvisor.TimeText(window.Start, now)}부터 {window.Hours}시간, 평균 습도 {window.AverageHumidity:0}% ({window.Level.Title()})");
    }

    private void Save(AppSettings settings)
    {
        _settings = settings;
        try { _store.Save(settings); }
        catch (IOException) { /* 저장 실패해도 앱은 계속 동작 */ }
        catch (UnauthorizedAccessException) { }
    }
}
