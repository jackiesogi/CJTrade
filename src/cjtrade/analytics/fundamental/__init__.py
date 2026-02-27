"""
CJTrade Companies Module

This module provides access to company fundamental data from Taiwan Stock Exchange
and other public sources. It includes company basic information, financial ratios,
EPS data, and major announcements.
"""
import asyncio
import logging
from datetime import datetime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from cjtrade.analytics.fundamental.models.announcement import Announcement
from cjtrade.analytics.fundamental.models.company_info import CompanyBasicInfo
from cjtrade.analytics.fundamental.models.financial_data import BalanceSheetInfo
from cjtrade.analytics.fundamental.models.financial_data import EPSInfo
from cjtrade.analytics.fundamental.models.financial_data import FinancialRatios
from cjtrade.analytics.fundamental.models.financial_data import IncomeStatementInfo
from cjtrade.analytics.fundamental.providers.twse import TWSEProvider
from cjtrade.analytics.fundamental.utils.parser import TWSEDataParser

# get_company_basic_info(): 公司基本資料（上市時間、負責人、公司全名......）
# get_financial_ratios(): 財務比率（PE/PB等）
# get_eps_info(): 每股盈餘資訊
# get_income_statements(): 綜合損益表資訊
# get_balance_sheet(): 資產負債表資訊
# get_recent_announcements(): 最近重大訊息（公告、新聞等）
# get_company_summary(): 一次獲取公司資訊總結（基本資料、財務比率、EPS、綜損表、資負表等）


logger = logging.getLogger(__name__)


class CompanyInfoProvider:
    """
    Unified company information provider interface

    Integrates multiple data sources and provides a simple API
    to retrieve company fundamental information
    """

    def __init__(self, default_provider: str = "twse", timeout: int = 30):
        self.default_provider = default_provider
        self.timeout = timeout
        self._providers: Dict[str, Any] = {}


    def _get_provider(self, provider_name: str = None):
        provider_name = provider_name or self.default_provider

        if provider_name not in self._providers:
            if provider_name == "twse":
                self._providers[provider_name] = TWSEProvider(timeout=self.timeout)
            else:
                raise ValueError(f"Unsupported provider: {provider_name}")

        return self._providers[provider_name]


    async def close(self):
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
        Get company basic information
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
        Get company financial ratios (PE/PB, etc.)
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
        Get company EPS information
        """
        try:
            provider_obj = self._get_provider(provider)
            return await provider_obj.get_eps_info(symbol)
        except Exception as e:
            logger.error(f"Failed to get EPS info for {symbol}: {e}")
            return []


    async def get_income_statements(self, symbol: str, provider: str = None) -> List[IncomeStatementInfo]:
        """
        Get company consolidated statements of comprehensive income

        Args:
            symbol: Stock symbol
            provider: Specify the data provider

        Returns:
            List[IncomeStatementInfo]: List of comprehensive income statement information
        """
        try:
            provider_obj = self._get_provider(provider)
            return await provider_obj.get_income_statements(symbol)
        except Exception as e:
            logger.error(f"Failed to get income statements for {symbol}: {e}")
            return []


    async def get_balance_sheet(self, symbol: str, provider: str = None) -> List[BalanceSheetInfo]:
        """
        Get company balance sheet
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
        Get complete company summary information
        """
        try:
            provider_obj = self._get_provider(provider)

            # Fetch all information concurrently
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


async def example_usage():
    async with CompanyInfoProvider() as provider:
        # Get complete information for TSMC (2330)
        summary = await provider.get_company_summary("2330")
        print("TSMC Summary:", summary['basic_info'])
        print("TSMC Financial Ratios:", summary['financial_ratios'])

        # Get major announcements from the past 7 days
        recent_news = await provider.get_recent_announcements(days=7)
        print(f"Major announcements from the past 7 days: {len(recent_news)} records")

        for news in recent_news[:3]:
            print(f"  {news}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(example_usage())
