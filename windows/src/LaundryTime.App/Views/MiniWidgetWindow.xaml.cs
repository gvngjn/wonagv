using System.Windows;
using System.Windows.Input;
using LaundryTime.App.ViewModels;

namespace LaundryTime.App.Views;

/// <summary>
/// 바탕화면에 띄워 두는 작은 항상-위 창 (iPhone 위젯 대응).
/// 기본 모드와 최소화 모드(습도 + 짧은 추천만)를 오갈 수 있다.
/// </summary>
public partial class MiniWidgetWindow : Window
{
    private const double ScreenMargin = 16;

    private readonly MainViewModel _model;
    private readonly Action _openMain;
    private bool _positioned;

    public MiniWidgetWindow(MainViewModel model, Action openMain)
    {
        InitializeComponent();
        _model = model;
        _openMain = openMain;
        DataContext = model;
        WindowStartupLocation = WindowStartupLocation.Manual;

        var (left, top) = model.MiniWidgetPosition;
        if (left is { } l && top is { } t && IsOnScreen(l, t))
        {
            Left = l;
            Top = t;
            _positioned = true;
        }
    }

    protected override void OnContentRendered(EventArgs e)
    {
        base.OnContentRendered(e);
        if (_positioned) return;
        // 기본 위치: 화면 오른쪽 위 (크기가 정해진 뒤 계산)
        Left = SystemParameters.WorkArea.Right - ActualWidth - ScreenMargin;
        Top = SystemParameters.WorkArea.Top + ScreenMargin;
        _positioned = true;
    }

    protected override void OnRenderSizeChanged(SizeChangedInfo sizeInfo)
    {
        base.OnRenderSizeChanged(sizeInfo);
        // 모드를 바꾸거나 문구 길이가 바뀌어도 오른쪽 끝이 제자리에 있도록
        if (_positioned && sizeInfo.WidthChanged && sizeInfo.PreviousSize.Width > 0)
        {
            Left += sizeInfo.PreviousSize.Width - sizeInfo.NewSize.Width;
            _model.MiniWidgetPosition = (Left, Top);
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

    private void OnToggleCompact(object sender, RoutedEventArgs e) =>
        _model.MiniWidgetCompact = !_model.MiniWidgetCompact;

    private void OnOpen(object sender, RoutedEventArgs e) => _openMain();

    private void OnHide(object sender, RoutedEventArgs e) => _model.MiniWidgetVisible = false;

    private static bool IsOnScreen(double left, double top) =>
        left >= SystemParameters.VirtualScreenLeft - 50 &&
        top >= SystemParameters.VirtualScreenTop - 50 &&
        left < SystemParameters.VirtualScreenLeft + SystemParameters.VirtualScreenWidth - 50 &&
        top < SystemParameters.VirtualScreenTop + SystemParameters.VirtualScreenHeight - 50;
}
