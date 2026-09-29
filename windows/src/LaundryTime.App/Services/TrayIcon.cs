using System.Drawing;
using System.Runtime.InteropServices;
using LaundryTime.App.ViewModels;
using LaundryTime.Core;
using Forms = System.Windows.Forms;

namespace LaundryTime.App.Services;

/// <summary>시스템 트레이 아이콘 · 메뉴 · 풍선 알림.</summary>
public sealed class TrayIcon : IDisposable
{
    private readonly Forms.NotifyIcon _icon;
    private Icon? _currentIcon;

    public TrayIcon(Action open, Action toggleWidget, Action refresh, Action exit)
    {
        var menu = new Forms.ContextMenuStrip();
        menu.Items.Add("열기", null, (_, _) => open());
        menu.Items.Add("미니 위젯 표시/숨기기", null, (_, _) => toggleWidget());
        menu.Items.Add("새로고침", null, (_, _) => refresh());
        menu.Items.Add(new Forms.ToolStripSeparator());
        menu.Items.Add("종료", null, (_, _) => exit());

        _icon = new Forms.NotifyIcon
        {
            Text = "빨래 타이밍",
            ContextMenuStrip = menu,
            Visible = true,
        };
        _icon.DoubleClick += (_, _) => open();
        Update(DryingLevel.Fair, "빨래 타이밍");
    }

    /// <summary>현재 등급 색으로 아이콘을 다시 그리고 툴팁을 바꾼다.</summary>
    public void Update(DryingLevel level, string tooltip)
    {
        var old = _currentIcon;
        _currentIcon = CreateIcon(LevelStyle.ColorOf(level));
        _icon.Icon = _currentIcon;
        old?.Dispose();

        const int maxLength = 63;
        _icon.Text = tooltip.Length > maxLength ? tooltip[..maxLength] : tooltip;
    }

    public void ShowNotification(string title, string body) =>
        _icon.ShowBalloonTip(10_000, title, body, Forms.ToolTipIcon.Info);

    public void Dispose()
    {
        _icon.Visible = false;
        _icon.Dispose();
        _currentIcon?.Dispose();
    }

    /// <summary>등급 색 원 + 흰색 물방울 모양 아이콘.</summary>
    private static Icon CreateIcon(System.Windows.Media.Color c)
    {
        using var bmp = new Bitmap(32, 32);
        using (var g = Graphics.FromImage(bmp))
        {
            g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
            using var fill = new SolidBrush(Color.FromArgb(c.R, c.G, c.B));
            g.FillEllipse(fill, 1, 1, 30, 30);

            using var drop = new System.Drawing.Drawing2D.GraphicsPath();
            drop.AddBezier(16, 6, 16, 6, 8, 16, 8, 20);
            drop.AddArc(8, 13, 16, 14, 180, -180);
            drop.AddBezier(24, 20, 24, 16, 16, 6, 16, 6);
            using var white = new SolidBrush(Color.White);
            g.FillPath(white, drop);
        }

        var handle = bmp.GetHicon();
        try
        {
            using var temp = Icon.FromHandle(handle);
            return (Icon)temp.Clone();
        }
        finally
        {
            DestroyIcon(handle);
        }
    }

    [DllImport("user32.dll")]
    private static extern bool DestroyIcon(IntPtr handle);
}
