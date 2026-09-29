using System.Collections.ObjectModel;
using System.IO;
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
    private readonly LocationService _location;
    private readonly SettingsStore _store;
    private readonly DispatcherTimer _clock;
    private AppSettings _settings;
    private IReadOnlyList<HourlyWeather>? _weather;
    private DateTimeOffset _lastFetch = DateTimeOffset.MinValue;
    private DateTimeOffset? _notifiedWindowStart;

    public MainViewModel(OpenMeteoClient client, LocationService location, SettingsStore store)
    {
        _client = client;
        _location = location;
        _store = store;
        _settings = store.Load();

        RefreshCommand = new AsyncCommand(RefreshAsync);
        SearchCommand = new AsyncCommand(SearchAsync);
        AddPeriodCommand = new RelayCommand(_ => AddPeriod());
        RemovePeriodCommand = new RelayCommand(p => RemovePeriod(p as UnavailablePeriod));

        foreach (var day in UnavailablePeriod.EveryDay)
            NewPeriodDays.Add(new DayToggle(day, UnavailablePeriod.Weekdays.Contains(day)));
        LoadPeriods();
        UpdateLocationSourceText(null);

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
    public RelayCommand AddPeriodCommand { get; }
    public RelayCommand RemovePeriodCommand { get; }

    public DryingForecast? Forecast { get; private set; }

    // ── 표시용 속성 ─────────────────────────────────────────

    private string _headline = "날씨 확인 중…";
    public string Headline { get => _headline; private set => Set(ref _headline, value); }

    public string LocationName => _settings.Place.Name;

    private string _locationSourceText = "";
    /// <summary>"자동 · Windows 위치" 처럼 위치를 어떻게 정했는지.</summary>
    public string LocationSourceText { get => _locationSourceText; private set => Set(ref _locationSourceText, value); }

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

    /// <summary>켜면 새로고침할 때마다 현재 위치로 지역을 갱신.</summary>
    public bool AutoLocation
    {
        get => _settings.AutoLocation;
        set
        {
            if (value == _settings.AutoLocation) return;
            Save(_settings with { AutoLocation = value });
            OnPropertyChanged();
            UpdateLocationSourceText(null);
            if (value) RefreshCommand.Execute(null);
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
            // 직접 고른 지역을 쓰기 위해 자동 위치는 끈다
            Save(_settings with { Place = value, AutoLocation = false });
            OnPropertyChanged(nameof(AutoLocation));
            UpdateLocationSourceText(null);
            OnPropertyChanged(nameof(LocationName));
            SearchResults.Clear();
            SearchQuery = "";
            SearchMessage = null;
            _notifiedWindowStart = null;
            RefreshCommand.Execute(null);
        }
    }

    // ── 빨래 못 너는 시간 ───────────────────────────────────

    public ObservableCollection<UnavailablePeriod> UnavailablePeriods { get; } = [];

    private bool _hasNoPeriods;
    public bool HasNoPeriods { get => _hasNoPeriods; private set => Set(ref _hasNoPeriods, value); }

    /// <summary>시간 선택 목록 (30분 단위).</summary>
    public IReadOnlyList<string> TimeOptions { get; } =
        Enumerable.Range(0, 48).Select(i => $"{i / 2:00}:{i % 2 * 30:00}").ToList();

    private string _newPeriodStart = "07:00";
    public string NewPeriodStart { get => _newPeriodStart; set => Set(ref _newPeriodStart, value); }

    private string _newPeriodEnd = "09:00";
    public string NewPeriodEnd { get => _newPeriodEnd; set => Set(ref _newPeriodEnd, value); }

    public ObservableCollection<DayToggle> NewPeriodDays { get; } = [];

    private string? _periodMessage;
    public string? PeriodMessage { get => _periodMessage; private set => Set(ref _periodMessage, value); }

    private void AddPeriod()
    {
        var days = NewPeriodDays.Where(d => d.IsChecked).Select(d => d.Day).ToList();
        if (days.Count == 0)
        {
            PeriodMessage = "요일을 하나 이상 골라 주세요.";
            return;
        }
        var period = new UnavailablePeriod(TimeOnly.Parse(NewPeriodStart), TimeOnly.Parse(NewPeriodEnd), days);
        if (period.Start == period.End)
        {
            PeriodMessage = "시작과 끝 시간이 같아요.";
            return;
        }
        if (_settings.UnavailablePeriods.Contains(period))
        {
            PeriodMessage = "이미 추가된 시간대예요.";
            return;
        }

        PeriodMessage = null;
        Save(_settings with { UnavailablePeriods = [.. _settings.UnavailablePeriods, period] });
        LoadPeriods();
        Recalculate();
    }

    private void RemovePeriod(UnavailablePeriod? period)
    {
        if (period is null) return;
        Save(_settings with { UnavailablePeriods = _settings.UnavailablePeriods.Where(p => !p.Equals(period)).ToList() });
        LoadPeriods();
        Recalculate();
    }

    private void LoadPeriods()
    {
        UnavailablePeriods.Clear();
        foreach (var p in _settings.UnavailablePeriods)
            UnavailablePeriods.Add(p);
        HasNoPeriods = UnavailablePeriods.Count == 0;
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
            if (_settings.AutoLocation)
                await UpdateLocationAsync();

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

    private async Task UpdateLocationAsync()
    {
        var located = await _location.LocateAsync();
        // 위치 확인 중에 사용자가 자동 위치를 끄거나 직접 지역을 골랐으면 무시
        if (!_settings.AutoLocation) return;
        if (located is not null)
        {
            Save(_settings with { Place = located.Place });
            OnPropertyChanged(nameof(LocationName));
        }
        UpdateLocationSourceText(located, attempted: true);
    }

    private void UpdateLocationSourceText(LocatedPlace? located, bool attempted = false)
    {
        LocationSourceText = !_settings.AutoLocation ? "직접 설정"
            : located is null ? (attempted ? "자동 · 위치 확인 실패, 마지막 위치 사용" : "자동 · 위치 확인 중…")
            : located.Source == LocationSource.Device ? "자동 · Windows 위치"
            : "자동 · 인터넷 연결 기준 대략 위치";
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
        var advisor = new DryingAdvisor
        {
            Scorer = new DryingScorer { Mode = _settings.ScoringMode },
            Finder = new DryingWindowFinder { Unavailable = _settings.UnavailablePeriods },
        };
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
            HourBars.Add(HourBar.From(h, now, _settings.UnavailablePeriods.Any(p => p.Contains(h.Weather.Time))));

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
