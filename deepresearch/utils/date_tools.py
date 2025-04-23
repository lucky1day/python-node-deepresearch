"""
日期工具函数
"""
from datetime import datetime, timedelta
from typing import Optional, Union
from dateutil import parser

from ..model_types import SERPQuery


def format_date_range(query: SERPQuery) -> str:
    """
    根据查询参数格式化日期范围
    
    Args:
        query: 搜索引擎查询参数
        
    Returns:
        格式化后的日期范围字符串
    """
    search_date_time = None
    current_date = datetime.now()
    format_type = 'full'  # 默认格式
    
    if query["tbs"]:
        if query["tbs"] == 'qdr:h':
            search_date_time = datetime.now() - timedelta(hours=1)
            format_type = 'hour'
        elif query["tbs"] == 'qdr:d':
            search_date_time = datetime.now() - timedelta(days=1)
            format_type = 'day'
        elif query["tbs"] == 'qdr:w':
            search_date_time = datetime.now() - timedelta(days=7)
            format_type = 'day'
        elif query["tbs"] == 'qdr:m':
            search_date_time = datetime.now() - timedelta(days=30)
            format_type = 'day'
        elif query["tbs"] == 'qdr:y':
            search_date_time = datetime.now() - timedelta(days=365)
            format_type = 'year'
    
    if search_date_time is not None:
        start_date = format_date_based_on_type(search_date_time, format_type)
        end_date = format_date_based_on_type(current_date, format_type)
        return f"Between {start_date} and {end_date}"
    
    return ''


def format_date_based_on_type(date: Union[datetime, str], format_type: str) -> str:
    """
    根据指定格式类型格式化日期
    
    Args:
        date: 日期对象
        format_type: 格式类型 ('year', 'day', 'hour', 'full')
        
    Returns:
        格式化后的日期字符串
    """
    if isinstance(date, str):
        date = parser.isoparse(date)

    year = str(date.year)
    month = str(date.month).zfill(2)
    day = str(date.day).zfill(2)
    hours = str(date.hour).zfill(2)
    minutes = str(date.minute).zfill(2)
    seconds = str(date.second).zfill(2)
    
    if format_type == 'year' or format_type == 'day':
        return f"{year}-{month}-{day}"
    elif format_type == 'hour':
        return f"{year}-{month}-{day} {hours}:{minutes}"
    else:  # 'full' 或其他情况
        return f"{year}-{month}-{day} {hours}:{minutes}:{seconds}" 