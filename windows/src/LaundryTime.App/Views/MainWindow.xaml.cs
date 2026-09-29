using System.ComponentModel;
using System.Windows;
using System.Windows.Input;

namespace LaundryTime.App.Views;

public partial class MainWindow : Window
{
    private bool _forceClose;

    public MainWindow() => InitializeComponent();

    /// <summary>앱 종료 시에만 실제로 닫는다.</summary>
    public void ForceClose()
    {
        _forceClose = true;
        Close();
    }

    /// <summary>차트 위에서도 마우스 휠로 페이지가 스크롤되도록 전달.</summary>
    private void OnChartMouseWheel(object sender, MouseWheelEventArgs e)
    {
        e.Handled = true;
        PageScroller.ScrollToVerticalOffset(PageScroller.VerticalOffset - e.Delta);
    }

    protected override void OnClosing(CancelEventArgs e)
    {
        // X 버튼은 트레이로 숨기기
        if (!_forceClose)
        {
            e.Cancel = true;
            Hide();
        }
        base.OnClosing(e);
    }
}
