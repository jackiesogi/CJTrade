"""
Financial data models for companies
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from typing import Dict
from typing import Optional


@dataclass
class EPSInfo:
    """每股盈餘資訊"""
    symbol: str                    # 股票代號
    company_name: str             # 公司名稱
    year: int                     # 年度
    quarter: Optional[int] = None  # 季度 (如果是季報)
    eps: Optional[float] = None    # 每股盈餘
    revenue: Optional[float] = None # 營收
    net_income: Optional[float] = None # 淨利
    updated_at: Optional[datetime] = None

    def __str__(self) -> str:
        period = f"{self.year}Q{self.quarter}" if self.quarter else str(self.year)
        return f"{self.symbol} {period} EPS: {self.eps}"


@dataclass
class FinancialRatios:
    """財務比率資訊 (PE/PB Ratio)"""
    symbol: str                    # 股票代號
    company_name: str             # 公司名稱
    pe_ratio: Optional[float] = None    # 本益比
    pb_ratio: Optional[float] = None    # 股價淨值比
    dividend_yield: Optional[float] = None # 殖利率
    roe: Optional[float] = None          # ROE 股東權益報酬率
    roa: Optional[float] = None          # ROA 資產報酬率
    current_ratio: Optional[float] = None # 流動比率
    debt_ratio: Optional[float] = None    # 負債比率
    updated_at: Optional[datetime] = None

    def __str__(self) -> str:
        return f"{self.symbol} PE:{self.pe_ratio} PB:{self.pb_ratio}"


@dataclass
class IncomeStatementInfo:
    """綜合損益表資訊"""
    symbol: str                    # 股票代號
    company_name: str             # 公司名稱
    year: int                     # 年度
    quarter: int                  # 季度
    industry_type: str            # 行業類型 (一般業、金融業、證券期貨業、金控業、保險業)

    # 一般業通用欄位
    revenue: Optional[float] = None              # 營業收入
    operating_income: Optional[float] = None     # 營業利益
    non_operating_income: Optional[float] = None # 營業外收入
    pre_tax_income: Optional[float] = None       # 稅前淨利
    net_income: Optional[float] = None           # 稅後淨利
    comprehensive_income: Optional[float] = None # 綜合損益總額
    eps: Optional[float] = None                  # 基本每股盈餘

    # 金融業特殊欄位
    interest_income_net: Optional[float] = None  # 利息淨收益
    non_interest_income: Optional[float] = None  # 利息以外淨損益
    provision_expense: Optional[float] = None    # 呆帳費用、承諾及保證責任準備提存
    operating_expense: Optional[float] = None    # 營業費用

    # 保險業特殊欄位
    insurance_revenue: Optional[float] = None    # 營業收入(保險業)
    insurance_cost: Optional[float] = None       # 營業成本(保險業)

    updated_at: Optional[datetime] = None

    def __str__(self) -> str:
        return f"{self.symbol} {self.year}Q{self.quarter} 淨利:{self.net_income}"


@dataclass
class BalanceSheetInfo:
    """資產負債表資訊"""
    symbol: str                    # 股票代號
    company_name: str             # 公司名稱
    year: int                     # 年度
    quarter: int                  # 季度
    total_assets: Optional[float] = None      # 總資產
    total_liabilities: Optional[float] = None # 總負債
    shareholders_equity: Optional[float] = None # 股東權益
    current_assets: Optional[float] = None    # 流動資產
    current_liabilities: Optional[float] = None # 流動負債
    long_term_debt: Optional[float] = None    # 長期負債
    cash_and_equivalents: Optional[float] = None # 現金及約當現金
    updated_at: Optional[datetime] = None

    def __str__(self) -> str:
        return f"{self.symbol} {self.year}Q{self.quarter} 總資產:{self.total_assets}"
