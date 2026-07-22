# =============================================================================
# analytics.py
# Simple usage analytics built on top of daily_history: a rolling average,
# an eco score, and a streak counter.
#
# All three are computed from finalized past days only (the entries that
# daily_history has already archived). Today's still-accumulating total is
# intentionally left out, since it is not comparable to a completed day's
# total until the day is over.
# =============================================================================

import daily_history
import settings


def rolling_average(days=7):
    """
    Return the average daily usage in litres over the most recent
    completed days.

    Args:
        days (int): how many of the most recent days to average (default 7)

    Returns:
        float: average litres per day, or 0.0 if there is no history yet
    """
    entries = daily_history.get_history(days)
    if not entries:
        return 0.0
    total = sum(e["total_litres"] for e in entries)
    return round(total / len(entries), 1)


def _usage_component(days):
    """
    Component 1 of 4 — Usage efficiency (weight: 70 pts max).

    Measures how far the 7-day average sits below the daily limit.
    Score is linear: 0 L/day → 70 pts, exactly at the limit → 0 pts,
    over the limit → 0 pts (clamped). This is the heaviest factor
    because staying under the limit is the primary conservation goal.

    Returns:
        float: 0.0 – 70.0
    """
    avg = rolling_average(days)
    limit = settings.get_daily_limit()
    if limit <= 0:
        return 0.0
    usage_frac = avg / limit          # 0 = no usage, 1 = at limit, >1 = over
    raw = (1.0 - usage_frac) * 70.0  # invert so lower usage → higher score
    return max(0.0, min(70.0, raw))


def _streak_component():
    """
    Component 2 of 4 — Consistency streak (weight: 15 pts max).

    Rewards users who have kept below the daily limit for many consecutive
    days in a row. The component grows linearly from 0 pts (0-day streak)
    to the full 15 pts once the streak reaches 7 days, then stays flat
    beyond that so it rewards sustained good habits without indefinitely
    compounding.

    Returns:
        float: 0.0 – 15.0
    """
    streak = current_streak()
    streak_frac = min(streak / 7.0, 1.0)   # cap at 7 consecutive days
    return streak_frac * 15.0


def _trend_component(days=7):
    """
    Component 3 of 4 — Usage trend (weight: 15 pts max).

    Looks at whether average usage is moving in the right direction.
    It splits the history window into an older half and a newer half,
    then compares their averages:

      - Newer average lower than older → improving trend → up to 15 pts
      - No history or identical halves → neutral → 7.5 pts (midpoint)
      - Newer average higher than older → worsening trend → 0 pts

    The score is clamped so a single unusually large improvement cannot
    push the component past its 15-pt ceiling.

    Returns:
        float: 0.0 – 15.0
    """
    entries = daily_history.get_history(days)
    if len(entries) < 2:
        # Not enough history to judge a trend; award the neutral midpoint
        return 7.5

    mid = len(entries) // 2
    older_half = entries[:mid]
    newer_half = entries[mid:]

    older_avg = sum(e["total_litres"] for e in older_half) / len(older_half)
    newer_avg = sum(e["total_litres"] for e in newer_half) / len(newer_half)

    limit = settings.get_daily_limit()
    if limit <= 0:
        return 7.5

    # Express the delta as a fraction of the daily limit so the score is
    # independent of whether the limit is 50 L or 500 L.
    # Positive delta → usage went down (good); negative → usage went up (bad).
    delta_frac = (older_avg - newer_avg) / limit

    # Map delta to [0, 15]: delta = 0 → 7.5 (neutral midpoint),
    # delta = +1 limit's worth of improvement → full 15 pts,
    # delta = -1 → 0 pts.
    raw = 7.5 + delta_frac * 15.0
    return max(0.0, min(15.0, raw))


def _leak_penalty():
    """
    Component 4 of 4 — Leak alarm penalty (deduction: up to −20 pts).

    Scans the in-memory event log for any leak_alarm or confirmed_leak
    transition messages logged in the current session. Each unique alarm
    event costs points, up to a cap of 20 pts total, because a leak alarm
    — even a brief one — represents a significant conservation/safety
    failure that the other three components cannot see.

    Limitation: the event log is in-memory only and resets on each server
    restart, so this factor reflects today's session rather than long-term
    history. Once leak alarm events are persisted to daily_history, this
    can be made retrospective.

    Returns:
        float: 0.0 – 20.0  (amount to subtract, NOT add)
    """
    # Import here to avoid a circular import at module load time
    import event_log as _event_log

    alarm_keywords = ("Leak alarm triggered", "Leak confirmed")
    alarm_count = sum(
        1 for ev in _event_log.get_all_events()
        if any(kw in ev["message"] for kw in alarm_keywords)
    )
    # Each alarm costs 10 pts, capped at 20 total (2 events)
    penalty = min(alarm_count * 10.0, 20.0)
    return penalty


def eco_score(days=7):
    """
    Return a blended 0–100 eco score that combines four factors:

      Component 1 — Usage efficiency   (70 pts max)
        How far the 7-day average usage sits below the daily limit.
        This is the dominant factor: staying well under the limit is the
        most direct measure of conservation.

      Component 2 — Consistency streak  (15 pts max)
        How many consecutive recent days usage stayed under the limit.
        Rewards sustained good habits, not just one lucky day.

      Component 3 — Usage trend         (15 pts max)
        Whether usage has been falling (improving) or rising (worsening)
        across the history window. Awards the neutral midpoint (7.5) when
        there is not enough history to judge direction.

      Component 4 — Leak alarm penalty  (−20 pts max deduction)
        Subtracts points for any leak alarm or confirmed-leak events logged
        during the current session. Ensures that causing a leak always hurts
        the score even if daily volume is low.

    Total before clamping = C1 + C2 + C3 − C4.
    Final score is clamped to [0, 100] and returned as an integer.

    Args:
        days (int): history window in days (default 7)

    Returns:
        int: eco score from 0 to 100
    """
    usage   = _usage_component(days)    # 0–70 pts
    streak  = _streak_component()       # 0–15 pts
    trend   = _trend_component(days)    # 0–15 pts
    penalty = _leak_penalty()           # 0–20 pts (deducted)

    raw = usage + streak + trend - penalty
    return max(0, min(100, round(raw)))


def current_streak():
    """
    Return the number of consecutive most-recent completed days where
    usage stayed at or under the daily limit. The streak breaks at the
    first day (walking backward from the most recent) that went over the
    limit.

    Returns:
        int: number of consecutive under-limit days, 0 if the most recent
             completed day was over the limit or there is no history yet
    """
    limit = settings.get_daily_limit()
    entries = daily_history.get_history()

    streak = 0
    for entry in reversed(entries):
        if entry["total_litres"] <= limit:
            streak += 1
        else:
            break
    return streak


def get_summary():
    """
    Return all three analytics figures together, for a single API call.

    Returns:
        dict: rolling_average_litres, eco_score, streak_days
    """
    return {
        "rolling_average_litres": rolling_average(7),
        "eco_score": eco_score(7),
        "streak_days": current_streak(),
    }
