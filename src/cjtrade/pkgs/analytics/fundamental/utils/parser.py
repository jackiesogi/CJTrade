"""
Data parsing utilities for TWSE API responses
"""
import logging
from datetime import datetime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union


logger = logging.getLogger(__name__)


class TWSEDataParser:
    """台灣證券交易所資料解析器"""

    @staticmethod
    def parse_date(date_str: str, formats: List[str] = None) -> Optional[datetime]:
        """
        解析日期字串

        Args:
            date_str: 日期字串
            formats: 日期格式列表，預設為常見的台灣日期格式

        Returns:
            datetime物件，解析失敗返回None
        """
        if not date_str:
            return None

        if formats is None:
            formats = [
                '%Y/%m/%d',     # 2023/12/26
                '%Y-%m-%d',     # 2023-12-26
                '%Y%m%d',       # 20231226
                '%m/%d/%Y',     # 12/26/2023
                '%d/%m/%Y',     # 26/12/2023
            ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue

        logger.warning(f"Unable to parse date: {date_str}")
        return None

    @staticmethod
    def parse_float(value: Union[str, int, float], default: Optional[float] = None) -> Optional[float]:
        """
        安全解析數值

        Args:
            value: 要解析的值
            default: 解析失敗時的預設值

        Returns:
            float值，解析失敗返回default
        """
        if value is None or value == '':
            return default

        try:
            if isinstance(value, (int, float)):
                return float(value)

            # 處理字串中的逗號、空格等
            if isinstance(value, str):
                # 移除逗號、空格、括號等
                cleaned = value.replace(',', '').replace(' ', '').replace('(', '').replace(')', '')

                # 處理負數
                if cleaned.startswith('-') or cleaned.endswith('-'):
                    cleaned = cleaned.replace('-', '')
                    return -float(cleaned)

                # 處理百分比
                if '%' in cleaned:
                    cleaned = cleaned.replace('%', '')
                    return float(cleaned) / 100

                return float(cleaned)

        except (ValueError, TypeError) as e:
            logger.debug(f"Failed to parse float value '{value}': {e}")

        return default

    @staticmethod
    def parse_int(value: Union[str, int], default: Optional[int] = None) -> Optional[int]:
        """
        安全解析整數

        Args:
            value: 要解析的值
            default: 解析失敗時的預設值

        Returns:
            int值，解析失敗返回default
        """
        if value is None or value == '':
            return default

        try:
            if isinstance(value, int):
                return value

            if isinstance(value, str):
                # 移除逗號、空格等
                cleaned = value.replace(',', '').replace(' ', '')
                return int(float(cleaned))  # 先轉float再轉int，處理如"123.0"的情況

        except (ValueError, TypeError) as e:
            logger.debug(f"Failed to parse int value '{value}': {e}")

        return default

    @staticmethod
    def safe_get(data: Dict[str, Any], key: str, default: Any = None) -> Any:
        """
        安全獲取字典值，支援多種key格式

        Args:
            data: 資料字典
            key: 要獲取的key
            default: 預設值

        Returns:
            字典中的值或預設值
        """
        if not isinstance(data, dict):
            return default

        # 直接匹配
        if key in data:
            return data[key]

        # 嘗試不同的key格式
        key_variants = [
            key,
            key.lower(),
            key.upper(),
            key.replace('_', ''),
            key.replace('_', '-'),
            key.replace('-', '_'),
            ''.join(word.capitalize() for word in key.split('_')),  # snake_case to PascalCase
        ]

        for variant in key_variants:
            if variant in data:
                return data[variant]

        return default

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """
        正規化股票代號

        Args:
            symbol: 原始股票代號

        Returns:
            正規化後的股票代號
        """
        if not symbol:
            return ""

        # 移除空格和特殊字符
        normalized = symbol.strip().replace(' ', '')

        # 確保是純數字格式（台股代號通常是4位數字）
        if normalized.isdigit():
            return normalized.zfill(4)  # 補齊到4位

        return normalized

    @staticmethod
    def validate_symbol(symbol: str) -> bool:
        """
        驗證股票代號格式

        Args:
            symbol: 股票代號

        Returns:
            是否為有效的股票代號
        """
        if not symbol:
            return False

        # 台股代號通常是4位數字，ETF可能有英文字母
        symbol = symbol.strip()

        # 純數字4位
        if symbol.isdigit() and len(symbol) == 4:
            return True

        # ETF格式 (如 0050, 00878)
        if symbol.isdigit() and len(symbol) in [4, 5]:
            return True

        # 包含字母的代號 (較少見)
        if len(symbol) <= 6 and symbol.replace('.', '').replace('-', '').isalnum():
            return True

        return False

    @staticmethod
    def clean_company_name(name: str) -> str:
        """
        清理公司名稱

        Args:
            name: 原始公司名稱

        Returns:
            清理後的公司名稱
        """
        if not name:
            return ""

        # 移除前後空格
        cleaned = name.strip()

        # 移除常見的後綴
        suffixes_to_remove = ['股份有限公司', '有限公司', '公司', '股份', '集團']
        for suffix in suffixes_to_remove:
            if cleaned.endswith(suffix):
                cleaned = cleaned[:-len(suffix)].strip()

        return cleaned

    @staticmethod
    def categorize_announcement(title: str, content: str = "") -> str:
        """
        根據公告標題和內容分類

        Args:
            title: 公告標題
            content: 公告內容

        Returns:
            公告分類
        """
        if not title:
            return "其他"

        title_lower = title.lower()
        content_lower = content.lower() if content else ""

        # 財務相關
        if any(keyword in title_lower for keyword in ['財報', '財務', '營收', '獲利', '盈餘', '損益', 'eps']):
            return "財務業績"

        # 股利相關
        if any(keyword in title_lower for keyword in ['股利', '股息', '配息', '除息', '除權']):
            return "股利配發"

        # 重大事件
        if any(keyword in title_lower for keyword in ['合併', '收購', '投資', '處分', '轉讓']):
            return "重大投資"

        # 人事異動
        if any(keyword in title_lower for keyword in ['董事', '經理', '人事', '異動', '任命', '辭職']):
            return "人事異動"

        # 法規相關
        if any(keyword in title_lower for keyword in ['法規', '法院', '訴訟', '罰款', '違規']):
            return "法規事項"

        # 營運相關
        if any(keyword in title_lower for keyword in ['營運', '業務', '產品', '服務', '合約']):
            return "營運發展"

        return "其他"


# 使用範例
def example_usage():
    """使用範例"""
    parser = TWSEDataParser()

    # 解析日期
    date = parser.parse_date("2023/12/26")
    print(f"解析日期: {date}")

    # 解析數值
    pe_ratio = parser.parse_float("15.67")
    revenue = parser.parse_float("1,234,567")
    print(f"PE比率: {pe_ratio}, 營收: {revenue}")

    # 正規化股票代號
    symbol = parser.normalize_symbol("2330")
    print(f"股票代號: {symbol}")

    # 分類公告
    category = parser.categorize_announcement("公布111年第三季財務報告")
    print(f"公告分類: {category}")


if __name__ == "__main__":
    example_usage()
