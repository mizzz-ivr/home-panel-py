from datetime import date, timedelta

from app.crud import habit


def calculate_current_streak(completed_dates: set[date], today: date) -> int:
    """既存呼び出し向けにカレンダー日単位の連続日数計算を維持する。"""
    if not completed_dates:
        return 0
    cursor = today if today in completed_dates else today - timedelta(days=1)
    streak = 0
    while cursor in completed_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


habit.calculate_current_streak = calculate_current_streak
