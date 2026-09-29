using Microsoft.Win32;

namespace LaundryTime.App.Services;

/// <summary>Windows 시작 시 자동 실행 (HKCU\...\Run 레지스트리).</summary>
public static class StartupRegistration
{
    private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string ValueName = "LaundryTime";

    public static bool IsEnabled
    {
        get
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKey);
            return key?.GetValue(ValueName) is not null;
        }
    }

    public static void SetEnabled(bool enabled)
    {
        using var key = Registry.CurrentUser.CreateSubKey(RunKey);
        if (enabled && Environment.ProcessPath is { } exe)
            key.SetValue(ValueName, $"\"{exe}\" --minimized");
        else
            key.DeleteValue(ValueName, throwOnMissingValue: false);
    }
}
