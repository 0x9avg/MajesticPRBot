"""
Утилиты для API сервиса.
"""


def split_time_by_day(started_at, ended_at):
    """
    Split a time range by day boundaries for daily stats tracking.
    
    Args:
        started_at: Start datetime
        ended_at: End datetime
        
    Yields:
        Tuples of (date, seconds) for each day in the range
    """
    from datetime import datetime, timedelta
    
    if not started_at or not ended_at:
        return
    
    # Ensure we're working with dates
    current = started_at
    
    while current.date() < ended_at.date():
        # Calculate seconds until end of current day
        end_of_day = datetime.combine(current.date() + timedelta(days=1), datetime.min.time())
        if end_of_day.tzinfo is None and current.tzinfo is not None:
            end_of_day = end_of_day.replace(tzinfo=current.tzinfo)
        
        seconds = int((end_of_day - current).total_seconds())
        yield (current.date(), seconds)
        
        current = end_of_day
    
    # Handle remaining time on the last day
    seconds = int((ended_at - current).total_seconds())
    if seconds > 0:
        yield (current.date(), seconds)
