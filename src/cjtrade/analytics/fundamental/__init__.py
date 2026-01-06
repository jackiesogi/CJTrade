"""
CJTrade Companies Module

This module provides access to company fundamental data from Taiwan Stock Exchange
and other public sources. It includes company basic information, financial ratios,
EPS data, and major announcements.
"""

from .providers.twse import TWSEProvider
from .models.company_info import CompanyBasicInfo
from .models.financial_data import FinancialRatios, EPSInfo, BalanceSheetInfo, IncomeStatementInfo
from .models.announcement import Announcement
from .utils.parser import TWSEDataParser

import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime


logger = logging.getLogger(__name__)


class CompanyInfoProvider:
    """
    統一的公司資訊提供者介面

    整合多個資料來源，提供簡單易用的API來獲取公司基本面資訊
    """

    def __init__(self, default_provider: str = "twse", timeout: int = 30):
        """
        初始化公司資訊提供者

        Args:
            default_provider: 預設的資料提供者 ("twse")
            timeout: HTTP請求超時時間(秒)
        """
        self.default_provider = default_provider
        self.timeout = timeout
        self._providers: Dict[str, Any] = {}

    def _get_provider(self, provider_name: str = None):
        """獲取指定的資料提供者"""
        provider_name = provider_name or self.default_provider

        if provider_name not in self._providers:
            if provider_name == "twse":
                self._providers[provider_name] = TWSEProvider(timeout=self.timeout)
            else:
                raise ValueError(f"Unsupported provider: {provider_name}")

        return self._providers[provider_name]

    async def close(self):
        """關閉所有providers"""
        for provider in self._providers.values():
            if hasattr(provider, 'close'):
                await provider.close()
        self._providers.clear()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def get_company_basic_info(self, symbol: str, provider: str = None) -> Optional[CompanyBasicInfo]:
        """
        獲取公司基本資訊

        Args:
            symbol: 股票代號
            provider: 指定資料提供者

        Returns:
            CompanyBasicInfo: 公司基本資訊，未找到返回None
        """
        try:
            provider_obj = self._get_provider(provider)
            companies = await provider_obj.get_company_basic_info(symbol)
            return companies[0] if companies else None
        except Exception as e:
            logger.error(f"Failed to get company basic info for {symbol}: {e}")
            return None

    async def get_financial_ratios(self, symbol: str, provider: str = None) -> Optional[FinancialRatios]:
        """
        獲取公司財務比率 (PE/PB等)

        Args:
            symbol: 股票代號
            provider: 指定資料提供者

        Returns:
            FinancialRatios: 財務比率資訊，未找到返回None
        """
        try:
            provider_obj = self._get_provider(provider)
            ratios = await provider_obj.get_financial_ratios(symbol)
            return ratios[0] if ratios else None
        except Exception as e:
            logger.error(f"Failed to get financial ratios for {symbol}: {e}")
            return None

    async def get_eps_info(self, symbol: str, provider: str = None) -> List[EPSInfo]:
        """
        獲取公司EPS資訊

        Args:
            symbol: 股票代號
            provider: 指定資料提供者

        Returns:
            List[EPSInfo]: EPS資訊列表
        """
        try:
            provider_obj = self._get_provider(provider)
            return await provider_obj.get_eps_info(symbol)
        except Exception as e:
            logger.error(f"Failed to get EPS info for {symbol}: {e}")
            return []

    async def get_income_statements(self, symbol: str, provider: str = None) -> List[IncomeStatementInfo]:
        """
        獲取公司綜合損益表

        Args:
            symbol: 股票代號
            provider: 指定資料提供者

        Returns:
            List[IncomeStatementInfo]: 綜合損益表資訊列表
        """
        try:
            provider_obj = self._get_provider(provider)
            return await provider_obj.get_income_statements(symbol)
        except Exception as e:
            logger.error(f"Failed to get income statements for {symbol}: {e}")
            return []

    async def get_balance_sheet(self, symbol: str, provider: str = None) -> List[BalanceSheetInfo]:
        """
        獲取公司資產負債表

        Args:
            symbol: 股票代號
            provider: 指定資料提供者

        Returns:
            List[BalanceSheetInfo]: 資產負債表資訊列表
        """
        try:
            provider_obj = self._get_provider(provider)
            return await provider_obj.get_balance_sheet_info(symbol)
        except Exception as e:
            logger.error(f"Failed to get balance sheet for {symbol}: {e}")
            return []

    async def get_recent_announcements(self, days: int = 7, provider: str = None) -> List[Announcement]:
        """
        Get recent major announcements

        Args:
            days: Announcements within how many days
            provider: Specify the data provider

        Returns:
            List[Announcement]: Major announcements list
        """
        try:
            provider_obj = self._get_provider(provider)
            announcements = await provider_obj.get_daily_announcements()

            # Filter announcements within the specified days (based on event_date)
            from datetime import datetime, timedelta
            cutoff_date = datetime.now() - timedelta(days=days)
            recent_announcements = [
                ann for ann in announcements
                if ann.event_date >= cutoff_date
            ]

            recent_announcements.sort(key=lambda x: x.event_date, reverse=True)

            return recent_announcements
        except Exception as e:
            logger.error(f"Failed to get recent announcements: {e}")
            return []

    async def get_company_summary(self, symbol: str, provider: str = None) -> Dict[str, Any]:
        """
        獲取公司完整摘要資訊

        Args:
            symbol: 股票代號
            provider: 指定資料提供者

        Returns:
            Dict: 包含所有公司資訊的字典
        """
        try:
            provider_obj = self._get_provider(provider)

            # 並行獲取所有資訊
            tasks = [
                provider_obj.get_company_basic_info(symbol),
                provider_obj.get_financial_ratios(symbol),
                provider_obj.get_eps_info(symbol),
                provider_obj.get_balance_sheet_info(symbol),
                provider_obj.get_income_statements(symbol)
            ]

            basic_info, financial_ratios, eps_info, balance_sheet, income_statements = await asyncio.gather(*tasks)

            return {
                'symbol': symbol,
                'basic_info': basic_info[0] if basic_info else None,
                'financial_ratios': financial_ratios[0] if financial_ratios else None,
                'eps_info': eps_info,
                'balance_sheet': balance_sheet,
                'income_statements': income_statements,
                'updated_at': datetime.now()
            }
        except Exception as e:
            logger.error(f"Failed to get company summary for {symbol}: {e}")
            return {
                'symbol': symbol,
                'basic_info': None,
                'financial_ratios': None,
                'eps_info': [],
                'balance_sheet': [],
                'income_statements': [],
                'error': str(e)
            }


__all__ = [
    'CompanyInfoProvider',
    'TWSEProvider',
    'CompanyBasicInfo',
    'FinancialRatios',
    'EPSInfo',
    'BalanceSheetInfo',
    'IncomeStatementInfo',
    'Announcement',
    'TWSEDataParser'
]


# 使用範例
async def example_usage():
    """使用範例"""
    async with CompanyInfoProvider() as provider:
        # 獲取台積電的完整資訊
        summary = await provider.get_company_summary("2330")
        print("台積電摘要:", summary['basic_info'])
        print("台積電財務比率:", summary['financial_ratios'])

        # 獲取最近一週的重大訊息
        recent_news = await provider.get_recent_announcements(days=7)
        print(f"最近一週重大訊息: {len(recent_news)} 筆")

        for news in recent_news[:3]:  # 顯示前3筆
            print(f"  {news}")


if __name__ == "__main__":
    # 設定logging
    logging.basicConfig(level=logging.INFO)
    asyncio.run(example_usage())