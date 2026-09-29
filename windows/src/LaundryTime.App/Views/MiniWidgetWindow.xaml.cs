using System.Windows;
using System.Windows.Input;
using LaundryTime.App.ViewModels;

namespace LaundryTime.App.Views;

/// <summary>바탕화면에 띄워 두는 작은 항상-위 창 (iPhone 위젯 대응).</summary>
public partial class MiniWidgetWindow : Window
{
    private readonly MainViewModel _model;
    private readonly Action _openMain;

    public MiniWidgetWindow(MainViewModel model, Action openMain)
    {
        InitializeComponent();
        _model = model;
        _openMain = openMain;
        DataContext = model;

        var (left, top) = model.MiniWidgetPosition;
        if (left is { } l && top is { } t && IsOnScreen(l, t))
        {
            WindowStartupLocation = WindowStartupLocation.Manual;
            Left = l;
            Top = t;
        }
        else
        {
            // 기본 위치: 화면 오른쪽 위
            WindowStartupLocation = WindowStartupLocation.Manual;
            Left = SystemParameters.WorkArea.Right - Width - 24;
            Top = SystemParameters.WorkArea.Top + 24;
        }
    }

    protected override void OnMouseLeftButtonDown(MouseButtonEventArgs e)
    {
        base.OnMouseLeftButtonDown(e);
        if (e.ClickCount == 2)
        {
            _openMain();
            return;
        }
        DragMove();
        _model.MiniWidgetPosition = (Left, Top);
    }

    private void OnOpen(object sender, RoutedEventArgs e) => _openMain();

    private void OnHide(object sender, RoutedEventArgs e) => _model.MiniWidgetVisible = false;

    private static bool IsOnScreen(double left, double top) =>
        left >= SystemParameters.VirtualScreenLeft - 50 &&
        top >= SystemParameters.VirtualScreenTop - 50 &&
        left < SystemParameters.VirtualScreenLeft + SystemParameters.VirtualScreenWidth - 50 &&
        top < SystemParameters.VirtualScreenTop + SystemParameters.VirtualScreenHeight - 50;
}
