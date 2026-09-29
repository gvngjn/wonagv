using System.Globalization;
using System.Windows;
using System.Windows.Data;

namespace LaundryTime.App.Views;

/// <summary>null · 빈 문자열 · 0이면 Collapsed.</summary>
public sealed class NotEmptyToVisibility : IValueConverter
{
    public static readonly NotEmptyToVisibility Instance = new();

    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value switch
        {
            null => Visibility.Collapsed,
            string s when string.IsNullOrWhiteSpace(s) => Visibility.Collapsed,
            int n when n == 0 => Visibility.Collapsed,
            _ => Visibility.Visible,
        };

    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}

/// <summary>로딩 중이면 " · 불러오는 중…" 문구를 붙인다.</summary>
public sealed class LoadingSuffix : IValueConverter
{
    public static readonly LoadingSuffix Instance = new();

    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value is true ? " · 불러오는 중…" : "";

    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}
