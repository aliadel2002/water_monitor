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


def eco_score(days=7):
    """
    Return a simple 0 to 100 score describing how usage compares to the
    daily limit over the recent period. 100 means usage has been at or
    near zero relative to the limit, 0 means usage has been at or above
    the limit on average.

    This is intentionally simple: score = 100 - (average usage as a
    percentage of the daily limit), clamped to the 0 to 100 range. It is
    meant as an at-a-glance gamification number for the dashboard, not a
    precise metric.

    Args:
        days (int): how many recent days to base the score on (default 7)

    Returns:
        int: eco score from 0 to 100
    """
    avg = rolling_average(days)
    limit = settings.get_daily_limit()

    if limit <= 0:
        return 0

    usage_pct = (avg / limit) * 100
    score = 100 - usage_pct
    score = max(0, min(100, score))
    return round(score)


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
