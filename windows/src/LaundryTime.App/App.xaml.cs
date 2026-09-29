using System.ComponentModel;
using System.Net.Http;
using System.Windows;
using LaundryTime.App.Services;
using LaundryTime.App.ViewModels;
using LaundryTime.App.Views;
using LaundryTime.Core;

namespace LaundryTime.App;

public partial class App : Application
{
    private Mutex? _singleInstance;
    private MainViewModel? _model;
    private MainWindow? _mainWindow;
    private MiniWidgetWindow? _widget;
    private TrayIcon? _tray;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        _singleInstance = new Mutex(true, "LaundryTime.SingleInstance", out var isFirst);
        if (!isFirst)
        {
            MessageBox.Show("빨래 타이밍이 이미 실행 중이에요.\n작업 표시줄 오른쪽 트레이 아이콘을 확인해 주세요.",
                "빨래 타이밍", MessageBoxButton.OK, MessageBoxImage.Information);
            Shutdown();
            return;
        }

        var http = new HttpClient { Timeout = TimeSpan.FromSeconds(15) };
        http.DefaultRequestHeaders.UserAgent.ParseAdd("LaundryTime/1.0");
        _model = new MainViewModel(new OpenMeteoClient(http), new SettingsStore(SettingsStore.DefaultPath));

        _mainWindow = new MainWindow { DataContext = _model };
        _tray = new TrayIcon(ShowMainWindow, () => _model.MiniWidgetVisible = !_model.MiniWidgetVisible,
            () => _model.RefreshCommand.Execute(null), ExitApp);

        _model.NotificationRequested += (title, body) => _tray.ShowNotification(title, body);
        _model.MiniWidgetVisibilityChanged += SetWidgetVisible;
        _model.PropertyChanged += OnModelChanged;

        if (!e.Args.Contains("--minimized"))
            ShowMainWindow();
        SetWidgetVisible(_model.MiniWidgetVisible);
        _model.Start();
    }

    private void OnModelChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (_model is null || _tray is null) return;
        if (e.PropertyName is nameof(MainViewModel.Headline) or nameof(MainViewModel.Level))
            _tray.Update(_model.Level, $"{_model.HumidityText} · {_model.Headline}");
    }

    private void ShowMainWindow()
    {
        if (_mainWindow is null) return;
        _mainWindow.Show();
        if (_mainWindow.WindowState == WindowState.Minimized)
            _mainWindow.WindowState = WindowState.Normal;
        _mainWindow.Activate();
    }

    private void SetWidgetVisible(bool visible)
    {
        if (_model is null) return;
        if (visible)
        {
            _widget ??= new MiniWidgetWindow(_model, ShowMainWindow);
            _widget.Show();
        }
        else
        {
            _widget?.Hide();
        }
    }

    private void ExitApp()
    {
        _mainWindow?.ForceClose();
        _widget?.Close();
        _tray?.Dispose();
        Shutdown();
    }

    protected override void OnExit(ExitEventArgs e)
    {
        _tray?.Dispose();
        _singleInstance?.Dispose();
        base.OnExit(e);
    }
}
