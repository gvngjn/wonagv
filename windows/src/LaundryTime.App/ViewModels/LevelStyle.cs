using System.Windows.Media;
using LaundryTime.Core;

namespace LaundryTime.App.ViewModels;

/// <summary>등급별 색상 (화면 · 미니 위젯 · 트레이 아이콘 공통).</summary>
public static class LevelStyle
{
    public static Color ColorOf(DryingLevel level) => level switch
    {
        DryingLevel.Excellent => Color.FromRgb(0xF5, 0x9E, 0x0B),
        DryingLevel.Good => Color.FromRgb(0x22, 0xA0, 0x6B),
        DryingLevel.Fair => Color.FromRgb(0x8A, 0x94, 0xA6),
        _ => Color.FromRgb(0x3B, 0x82, 0xF6),
    };

    public static SolidColorBrush BrushOf(DryingLevel level)
    {
        var brush = new SolidColorBrush(ColorOf(level));
        brush.Freeze();
        return brush;
    }
}
