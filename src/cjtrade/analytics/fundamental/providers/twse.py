"""
Taiwan Stock Exchange (TWSE) API Provider

Provides async access to TWSE open data APIs for company information,
financial ratios, EPS data, balance sheets, and announcements.
"""
import asyncio
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
import aiohttp

from ..models.company_info import CompanyBasicInfo
from ..models.financial_data import EPSInfo, FinancialRatios, BalanceSheetInfo, IncomeStatementInfo
from ..models.announcement import Announcement


logger = logging.getLogger(__name__)


class TWSEProvider:
    """台灣證券交易所資料提供者"""

    BASE_URL = "https://openapi.twse.com.tw/v1"

    # API endpoints
    ENDPOINTS = {
        'announcements': '/opendata/t187ap04_L',      # 每日重大訊息
        'company_basic': '/opendata/t187ap03_L',      # 上市公司基本資料
        'eps_info': '/opendata/t187ap14_L',           # 上市公司EPS資訊
        'pe_pb_ratios': '/exchange/BWIBBU_ALL',       # 上市公司PE/PB Ratio

        # 財務報表 - 分行業
        'income_statement_general': '/opendata/t187ap06_X_ci',    # 綜合損益表-一般業
        'income_statement_banking': '/opendata/t187ap06_X_basi',  # 綜合損益表-金融業
        'income_statement_securities': '/opendata/t187ap06_X_bd', # 綜合損益表-證券期貨業
        'income_statement_financial_holding': '/opendata/t187ap06_X_fh', # 綜合損益表-金控業
        'income_statement_insurance': '/opendata/t187ap06_X_ins', # 綜合損益表-保險業

        'balance_sheet_general': '/opendata/t187ap07_X_ci',       # 資產負債表-一般業(目前無資料)
        'balance_sheet_other': '/opendata/t187ap07_X_mim',        # 資產負債表-異業(目前無資料)
    }

    def __init__(self, timeout: int = 30):
        """
        初始化TWSE提供者

        Args:
            timeout: HTTP請求超時時間(秒)
        """
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """獲取或創建HTTP session"""
        if self._session is None or self._session.closed:
            # 創建SSL context，跳過證書驗證以避免TWSE的SSL問題
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            connector = aiohttp.TCPConnector(ssl=ssl_context)
            self._session = aiohttp.ClientSession(timeout=self.timeout, connector=connector)
        return self._session

    async def close(self):
        """關閉HTTP session"""
        if self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _fetch_data(self, endpoint: str) -> Dict[str, Any]:
        """
        通用的API資料獲取方法

        Args:
            endpoint: API endpoint路径

        Returns:
            API回傳的JSON資料

        Raises:
            aiohttp.ClientError: HTTP請求錯誤
            ValueError: JSON解析錯誤
        """
        url = f"{self.BASE_URL}{endpoint}"
        session = await self._get_session()

        try:
            logger.debug(f"Fetching data from: {url}")
            async with session.get(url) as response:
                response.raise_for_status()
                data = await response.json()
                logger.debug(f"Successfully fetched {len(data) if isinstance(data, list) else 1} records")
                return data
        except aiohttp.ClientError as e:
            logger.error(f"HTTP error fetching {url}: {e}")
            raise
        except ValueError as e:
            logger.error(f"JSON parsing error for {url}: {e}")
            raise

    async def get_daily_announcements(self) -> List[Announcement]:
        """
        獲取每日重大訊息

        Returns:
            List[Announcement]: 重大訊息列表
        """
        try:
            data = await self._fetch_data(self.ENDPOINTS['announcements'])
            announcements = []

            for item in data:
                try:
                    # 實際欄位: 出表日期, 發言日期, 發言時間, 公司代號, 公司名稱, 主旨, 符合條款, 事實發生日, 說明

                    def parse_roc_date(date_str):
                        """解析民國年日期格式 (例: 1141223)"""
                        if date_str and len(date_str) >= 7:
                            try:
                                year = int(date_str[:3]) + 1911  # 民國年轉西元年
                                month = int(date_str[3:5])
                                day = int(date_str[5:7])
                                return datetime(year, month, day)
                            except ValueError:
                                pass
                        return None

                    # 解析三個重要日期
                    event_date = parse_roc_date(item.get('事實發生日', ''))
                    announcement_date = parse_roc_date(item.get('發言日期', ''))
                    publish_date = parse_roc_date(item.get('出表日期', ''))

                    # 如果事實發生日無法解析，使用發言日期作為備用
                    if not event_date:
                        event_date = announcement_date or datetime.now()

                    announcement = Announcement(
                        symbol=item.get('公司代號', ''),
                        company_name=item.get('公司名稱', ''),
                        event_date=event_date,
                        announcement_date=announcement_date,
                        publish_date=publish_date,
                        title=item.get('主旨 ', '').strip(),  # 移除前後空白和換行
                        content=item.get('說明', ''),
                        category=item.get('符合條款', ''),
                        url=None  # API未提供URL
                    )
                    announcements.append(announcement)

                except (ValueError, KeyError) as e:
                    logger.warning(f"Failed to parse announcement item: {e}")
                    continue

            return announcements

        except Exception as e:
            logger.error(f"Failed to get daily announcements: {e}")
            return []

    async def get_company_basic_info(self, symbol: Optional[str] = None) -> List[CompanyBasicInfo]:
        """
        獲取上市公司基本資料

        Args:
            symbol: 股票代號，若為None則返回所有公司資料

        Returns:
            List[CompanyBasicInfo]: 公司基本資料列表
        """
        try:
            data = await self._fetch_data(self.ENDPOINTS['company_basic'])
            companies = []

            for item in data:
                try:
                    # 實際欄位: 公司代號, 公司名稱, 公司簡稱, 產業別, 住址, 董事長, 總經理,
                    # 成立日期, 上市日期, 實收資本額, 網址, 等等

                    company_symbol = item.get('公司代號', '')

                    # 如果指定了symbol，只返回該公司資料
                    if symbol and company_symbol != symbol:
                        continue

                    # 解析上市日期 (格式: 19620209)
                    listing_date = None
                    listing_date_str = item.get('上市日期', '')
                    if listing_date_str and listing_date_str != '－':
                        try:
                            year = int(listing_date_str[:4])
                            month = int(listing_date_str[4:6])
                            day = int(listing_date_str[6:8])
                            listing_date = datetime(year, month, day)
                        except ValueError:
                            pass

                    # 解析實收資本額
                    capital = None
                    capital_str = item.get('實收資本額', '')
                    if capital_str and capital_str != '－':
                        try:
                            capital = float(capital_str)
                        except ValueError:
                            pass

                    company = CompanyBasicInfo(
                        symbol=company_symbol,
                        name=item.get('公司名稱', ''),
                        industry=item.get('產業別', ''),
                        market='上市',  # 這個API專門提供上市公司資料
                        listing_date=listing_date,
                        capital=capital,
                        chairman=item.get('董事長', ''),
                        ceo=item.get('總經理', ''),
                        address=item.get('住址', ''),
                        phone=item.get('總機電話', ''),
                        website=item.get('網址', ''),
                        business_scope=None  # API未提供此欄位
                    )
                    companies.append(company)

                except (ValueError, KeyError) as e:
                    logger.warning(f"Failed to parse company basic info item: {e}")
                    continue

            return companies

        except Exception as e:
            logger.error(f"Failed to get company basic info: {e}")
            return []

    async def get_eps_info(self, symbol: Optional[str] = None) -> List[EPSInfo]:
        """
        獲取上市公司EPS資訊

        Args:
            symbol: 股票代號，若為None則返回所有公司EPS資料

        Returns:
            List[EPSInfo]: EPS資訊列表
        """
        try:
            data = await self._fetch_data(self.ENDPOINTS['eps_info'])
            eps_list = []

            for item in data:
                try:
                    # 實際欄位: 年度, 季別, 公司代號, 公司名稱, 產業別, 基本每股盈餘(元),
                    # 營業收入, 營業利益, 營業外收入及支出, 稅後淨利

                    company_symbol = item.get('公司代號', '')

                    if symbol and company_symbol != symbol:
                        continue

                    # 解析年度 (民國年, 如: 114)
                    year_str = item.get('年度', '')
                    year = int(year_str) + 1911 if year_str and year_str.isdigit() else 0

                    # 解析季別
                    quarter_str = item.get('季別', '')
                    quarter = int(quarter_str) if quarter_str and quarter_str.isdigit() else None

                    # 解析EPS
                    eps_str = item.get('基本每股盈餘(元)', '')
                    eps = float(eps_str) if eps_str and eps_str != '－' else None

                    # 解析營收
                    revenue_str = item.get('營業收入', '')
                    revenue = float(revenue_str) if revenue_str and revenue_str != '－' else None

                    # 解析稅後淨利
                    net_income_str = item.get('稅後淨利', '')
                    net_income = float(net_income_str) if net_income_str and net_income_str != '－' else None

                    eps_info = EPSInfo(
                        symbol=company_symbol,
                        company_name=item.get('公司名稱', ''),
                        year=year,
                        quarter=quarter,
                        eps=eps,
                        revenue=revenue,
                        net_income=net_income,
                        updated_at=datetime.now()
                    )
                    eps_list.append(eps_info)

                except (ValueError, KeyError) as e:
                    logger.warning(f"Failed to parse EPS info item: {e}")
                    continue

            return eps_list

        except Exception as e:
            logger.error(f"Failed to get EPS info: {e}")
            return []

    async def get_financial_ratios(self, symbol: Optional[str] = None) -> List[FinancialRatios]:
        """
        獲取上市公司PE/PB Ratio等財務比率

        Args:
            symbol: 股票代號，若為None則返回所有公司財務比率

        Returns:
            List[FinancialRatios]: 財務比率列表
        """
        try:
            data = await self._fetch_data(self.ENDPOINTS['pe_pb_ratios'])
            ratios_list = []

            for item in data:
                try:
                    # 實際欄位: Date, Code, Name, PEratio, DividendYield, PBratio

                    company_symbol = item.get('Code', '')

                    if symbol and company_symbol != symbol:
                        continue

                    # 解析PE Ratio (可能為空字串)
                    pe_ratio_str = item.get('PEratio', '')
                    pe_ratio = float(pe_ratio_str) if pe_ratio_str and pe_ratio_str != '' else None

                    # 解析PB Ratio
                    pb_ratio_str = item.get('PBratio', '')
                    pb_ratio = float(pb_ratio_str) if pb_ratio_str and pb_ratio_str != '' else None

                    # 解析殖利率
                    dividend_yield_str = item.get('DividendYield', '')
                    dividend_yield = float(dividend_yield_str) if dividend_yield_str and dividend_yield_str != '' else None

                    ratios = FinancialRatios(
                        symbol=company_symbol,
                        company_name=item.get('Name', ''),
                        pe_ratio=pe_ratio,
                        pb_ratio=pb_ratio,
                        dividend_yield=dividend_yield,
                        roe=None,  # 此API未提供
                        roa=None,  # 此API未提供
                        current_ratio=None,  # 此API未提供
                        debt_ratio=None,  # 此API未提供
                        updated_at=datetime.now()
                    )
                    ratios_list.append(ratios)

                except (ValueError, KeyError) as e:
                    logger.warning(f"Failed to parse financial ratios item: {e}")
                    continue

            return ratios_list

        except Exception as e:
            logger.error(f"Failed to get financial ratios: {e}")
            return []

    async def get_balance_sheet_info(self, symbol: Optional[str] = None) -> List[BalanceSheetInfo]:
        """
        獲取上市公司資產負債表資訊

        Args:
            symbol: 股票代號，若為None則返回所有公司資產負債表資料

        Returns:
            List[BalanceSheetInfo]: 資產負債表資訊列表
        """
        try:
            data = await self._fetch_data(self.ENDPOINTS['balance_sheet_general'])
            balance_sheet_list = []

            for item in data:
                try:
                    # 實際欄位: 年度, 季別, 公司代號, 公司名稱, 流動資產, 非流動資產, 資產總計,
                    # 流動負債, 非流動負債, 負債總計, 股本, 資本公積, 保留盈餘, 權益總計, 等等

                    company_symbol = item.get('公司代號', '')

                    # 跳過空資料
                    if not company_symbol:
                        continue

                    if symbol and company_symbol != symbol:
                        continue

                    # 解析年度 (民國年)
                    year_str = item.get('年度', '')
                    year = int(year_str) + 1911 if year_str and year_str.isdigit() else 0

                    # 解析季別
                    quarter_str = item.get('季別', '')
                    quarter = int(quarter_str) if quarter_str and quarter_str.isdigit() else 0

                    # 跳過無效的年度/季別
                    if year == 1911 or quarter == 0:
                        continue

                    # 解析各項財務數據
                    def safe_float(value_str):
                        if value_str and value_str != '' and value_str != '－':
                            try:
                                return float(value_str.replace(',', ''))
                            except ValueError:
                                pass
                        return None

                    balance_sheet = BalanceSheetInfo(
                        symbol=company_symbol,
                        company_name=item.get('公司名稱', ''),
                        year=year,
                        quarter=quarter,
                        total_assets=safe_float(item.get('資產總計', '')),
                        total_liabilities=safe_float(item.get('負債總計', '')),
                        shareholders_equity=safe_float(item.get('歸屬於母公司業主之權益合計', '')),
                        current_assets=safe_float(item.get('流動資產', '')),
                        current_liabilities=safe_float(item.get('流動負債', '')),
                        long_term_debt=safe_float(item.get('非流動負債', '')),
                        cash_and_equivalents=None,  # API未提供具體現金項目
                        updated_at=datetime.now()
                    )
                    balance_sheet_list.append(balance_sheet)

                except (ValueError, KeyError) as e:
                    logger.warning(f"Failed to parse balance sheet item: {e}")
                    continue

            return balance_sheet_list

        except Exception as e:
            logger.error(f"Failed to get balance sheet info: {e}")
            return []

    async def get_income_statements(self, symbol: Optional[str] = None) -> List[IncomeStatementInfo]:
        """
        獲取綜合損益表資訊 (自動選擇適當的行業API)

        Args:
            symbol: 股票代號，若為None則返回所有公司綜合損益表資料

        Returns:
            List[IncomeStatementInfo]: 綜合損益表資訊列表
        """
        all_income_statements = []

        # 行業分類API映射
        industry_apis = {
            'banking': ('income_statement_banking', '金融業'),
            'securities': ('income_statement_securities', '證券期貨業'),
            'insurance': ('income_statement_insurance', '保險業'),
            'financial_holding': ('income_statement_financial_holding', '金控業'),
            'general': ('income_statement_general', '一般業')
        }

        for industry_key, (endpoint_key, industry_name) in industry_apis.items():
            try:
                data = await self._fetch_data(self.ENDPOINTS[endpoint_key])

                for item in data:
                    try:
                        company_symbol = item.get('公司代號', '')

                        # 跳過空資料
                        if not company_symbol:
                            continue

                        if symbol and company_symbol != symbol:
                            continue

                        # 解析年度 (民國年)
                        year_str = item.get('年度', '')
                        year = int(year_str) + 1911 if year_str and year_str.isdigit() else 0

                        # 解析季別
                        quarter_str = item.get('季別', '')
                        quarter = int(quarter_str) if quarter_str and quarter_str.isdigit() else 0

                        # 跳過無效的年度/季別
                        if year == 1911 or quarter == 0:
                            continue

                        # 通用欄位解析函數
                        def safe_float(value_str):
                            if value_str and value_str != '' and value_str != '－':
                                try:
                                    return float(str(value_str).replace(',', ''))
                                except ValueError:
                                    pass
                            return None

                        # 解析EPS
                        eps = safe_float(item.get('基本每股盈餘（元）', ''))

                        # 建立基礎income statement
                        income_statement = IncomeStatementInfo(
                            symbol=company_symbol,
                            company_name=item.get('公司名稱', ''),
                            year=year,
                            quarter=quarter,
                            industry_type=industry_name,
                            eps=eps,
                            updated_at=datetime.now()
                        )

                        # 根據行業類型填入對應欄位
                        if industry_key == 'banking':
                            # 金融業欄位
                            income_statement.interest_income_net = safe_float(item.get('利息淨收益', ''))
                            income_statement.non_interest_income = safe_float(item.get('利息以外淨損益', ''))
                            income_statement.provision_expense = safe_float(item.get('呆帳費用、承諾及保證責任準備提存', ''))
                            income_statement.operating_expense = safe_float(item.get('營業費用', ''))
                            income_statement.pre_tax_income = safe_float(item.get('繼續營業單位稅前淨利（淨損）', ''))
                            income_statement.net_income = safe_float(item.get('本期稅後淨利（淨損）', ''))
                            income_statement.comprehensive_income = safe_float(item.get('本期綜合損益總額（稅後）', ''))

                        elif industry_key == 'securities':
                            # 證券期貨業欄位
                            income_statement.revenue = safe_float(item.get('收益', ''))
                            income_statement.operating_expense = safe_float(item.get('支出及費用', ''))
                            income_statement.operating_income = safe_float(item.get('營業利益', ''))
                            income_statement.non_operating_income = safe_float(item.get('營業外損益', ''))
                            income_statement.pre_tax_income = safe_float(item.get('稅前淨利（淨損）', ''))
                            income_statement.net_income = safe_float(item.get('本期淨利（淨損）', ''))
                            income_statement.comprehensive_income = safe_float(item.get('本期綜合損益總額', ''))

                        elif industry_key == 'insurance':
                            # 保險業欄位
                            income_statement.insurance_revenue = safe_float(item.get('營業收入', ''))
                            income_statement.insurance_cost = safe_float(item.get('營業成本', ''))
                            income_statement.operating_expense = safe_float(item.get('營業費用', ''))
                            income_statement.operating_income = safe_float(item.get('營業利益（損失）', ''))
                            income_statement.non_operating_income = safe_float(item.get('營業外收入及支出', ''))
                            income_statement.pre_tax_income = safe_float(item.get('繼續營業單位稅前純益（純損）', ''))
                            income_statement.net_income = safe_float(item.get('本期淨利（淨損）', ''))
                            income_statement.comprehensive_income = safe_float(item.get('本期綜合損益總額', ''))

                        # 其他行業的通用欄位處理可以在這裡添加

                        all_income_statements.append(income_statement)

                    except (ValueError, KeyError) as e:
                        logger.warning(f"Failed to parse income statement item for {industry_name}: {e}")
                        continue

            except Exception as e:
                logger.warning(f"Failed to get {industry_name} income statements: {e}")
                continue

        return all_income_statements

    async def get_company_all_info(self, symbol: str) -> Dict[str, Any]:
        """
        獲取特定公司的所有資訊

        Args:
            symbol: 股票代號

        Returns:
            Dict包含所有公司資訊
        """
        tasks = [
            self.get_company_basic_info(symbol),
            self.get_eps_info(symbol),
            self.get_financial_ratios(symbol),
            self.get_balance_sheet_info(symbol)
        ]

        basic_info, eps_info, financial_ratios, balance_sheet = await asyncio.gather(*tasks)

        return {
            'basic_info': basic_info[0] if basic_info else None,
            'eps_info': eps_info,
            'financial_ratios': financial_ratios[0] if financial_ratios else None,
            'balance_sheet': balance_sheet
        }


# 使用範例
async def main():
    """使用範例"""
    async with TWSEProvider() as provider:
        # 獲取台積電的所有資訊
        tsmc_info = await provider.get_company_all_info("2330")
        print("台積電基本資訊:", tsmc_info['basic_info'])
        print("台積電財務比率:", tsmc_info['financial_ratios'])

        # 獲取今日重大訊息
        announcements = await provider.get_daily_announcements()
        print(f"今日重大訊息共 {len(announcements)} 筆")
        for announcement in announcements[:5]:  # 顯示前5筆
            print(f"  {announcement}")


if __name__ == "__main__":
    asyncio.run(main())