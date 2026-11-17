"""
Company announcement data models
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Announcement:
    """A TWSE major announcement (重大訊息).

    ``event_date`` (事實發生日期) is the main date; ``announcement_date`` is when
    the company announced it and ``publish_date`` when the API published it.
    """
    symbol: str                    # 股票代號
    company_name: str              # 公司名稱
    event_date: datetime           # 事實發生日期 (最重要的日期)
    announcement_date: Optional[datetime] = None  # 發言日期 (公司公告日)
    publish_date: Optional[datetime] = None       # 出表日期 (API發布日)
    title: str = ""                # 公告標題 (主旨)
    content: Optional[str] = None  # 公告內容 (說明)
    category: Optional[str] = None # 公告類別 (符合條款)
    url: Optional[str] = None      # 原始公告連結

    def __str__(self) -> str:
        return f"{self.symbol} {self.event_date.strftime('%Y-%m-%d')} {self.title}"

    @property
    def is_recent(self, days: int = 7) -> bool:
        """Whether ``event_date`` is within the last 7 days.

        Warnings
        --------
        Depends on the current wall-clock time. As a property it cannot take
        `days`, so the default of 7 is always used.
        """
        from datetime import timedelta
        return (datetime.now() - self.event_date) <= timedelta(days=days)

    @property
    def days_since_event(self) -> int:
        """Whole days from ``event_date`` to now.

        Warnings
        --------
        Depends on the current wall-clock time.
        """
        return (datetime.now() - self.event_date).days

    @property
    def announcement_delay(self) -> Optional[int]:
        """Days from ``event_date`` to ``announcement_date``, or None if not announced."""
        if self.announcement_date:
            return (self.announcement_date - self.event_date).days
        return None
