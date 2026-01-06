"""
Company basic information data models
"""
from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime


@dataclass
class CompanyBasicInfo:
    """公司基本資料"""
    symbol: str                    # 股票代號
    name: str                     # 公司名稱
    industry: str                 # 產業別
    market: str                   # 上市/上櫃
    listing_date: Optional[datetime] = None  # 上市日期
    capital: Optional[float] = None          # 實收資本額
    chairman: Optional[str] = None           # 董事長
    ceo: Optional[str] = None                # 總經理
    address: Optional[str] = None            # 公司地址
    phone: Optional[str] = None              # 電話
    website: Optional[str] = None            # 網站
    business_scope: Optional[str] = None     # 營業項目

    def __str__(self) -> str:
        return f"{self.symbol} {self.name} ({self.industry})"