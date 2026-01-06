"""
Company announcement data models
"""
from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class Announcement:
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
        from datetime import timedelta
        return (datetime.now() - self.event_date) <= timedelta(days=days)

    @property
    def days_since_event(self) -> int:
        return (datetime.now() - self.event_date).days

    @property
    def announcement_delay(self) -> Optional[int]:
        if self.announcement_date:
            return (self.announcement_date - self.event_date).days
        return None