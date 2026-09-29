namespace LaundryTime.Core;

/// <summary>
/// 빨래를 널 수 없는 시간대 (예: 평일 07:00~09:00 출근).
/// 이 시간에는 널기를 추천하지 않지만, 그 전에 널어 둔 빨래는 계속 마른다고 본다.
/// </summary>
/// <param name="Start">시작 시각 (포함)</param>
/// <param name="End">끝 시각 (제외). Start보다 이르면 자정을 넘기는 구간 (예: 22:00~06:00)</param>
/// <param name="Days">적용 요일. 시작 시각이 속한 요일 기준.</param>
public sealed record UnavailablePeriod(TimeOnly Start, TimeOnly End, IReadOnlyList<DayOfWeek> Days)
{
    public static readonly IReadOnlyList<DayOfWeek> Weekdays =
        [DayOfWeek.Monday, DayOfWeek.Tuesday, DayOfWeek.Wednesday, DayOfWeek.Thursday, DayOfWeek.Friday];

    public static readonly IReadOnlyList<DayOfWeek> Weekend = [DayOfWeek.Saturday, DayOfWeek.Sunday];

    public static readonly IReadOnlyList<DayOfWeek> EveryDay =
        [DayOfWeek.Monday, DayOfWeek.Tuesday, DayOfWeek.Wednesday, DayOfWeek.Thursday,
         DayOfWeek.Friday, DayOfWeek.Saturday, DayOfWeek.Sunday];

    /// <summary>주어진 (현지) 시각이 이 구간에 속하는지.</summary>
    public bool Contains(DateTimeOffset time)
    {
        var t = TimeOnly.FromTimeSpan(time.TimeOfDay);
        if (Start == End)
            return false;
        if (Start < End)
            return Days.Contains(time.DayOfWeek) && t >= Start && t < End;

        // 자정을 넘기는 구간: 22:00~24:00 은 당일, 00:00~06:00 은 전날 요일 기준
        if (t >= Start)
            return Days.Contains(time.DayOfWeek);
        if (t < End)
            return Days.Contains(time.AddDays(-1).DayOfWeek);
        return false;
    }

    /// <summary>"평일 07:00~09:00" 형태.</summary>
    public string Description => $"{DaysText(Days)} {Start:HH\\:mm}~{End:HH\\:mm}";

    public static string DaysText(IReadOnlyCollection<DayOfWeek> days)
    {
        var set = days.ToHashSet();
        if (set.SetEquals(EveryDay)) return "매일";
        if (set.SetEquals(Weekdays)) return "평일";
        if (set.SetEquals(Weekend)) return "주말";
        return string.Join("·", EveryDay.Where(set.Contains).Select(DayName));
    }

    public static string DayName(DayOfWeek day) => day switch
    {
        DayOfWeek.Monday => "월",
        DayOfWeek.Tuesday => "화",
        DayOfWeek.Wednesday => "수",
        DayOfWeek.Thursday => "목",
        DayOfWeek.Friday => "금",
        DayOfWeek.Saturday => "토",
        _ => "일",
    };

    // 요일 목록을 값으로 비교 (설정 저장 · 비교용)
    public bool Equals(UnavailablePeriod? other) =>
        other is not null && Start == other.Start && End == other.End && Days.SequenceEqual(other.Days);

    public override int GetHashCode() => HashCode.Combine(Start, End, Days.Count);
}
