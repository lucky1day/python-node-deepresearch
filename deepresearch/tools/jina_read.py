"""
网页内容读取工具
"""
import requests
import json
from typing import Dict, Optional, Any, List
import sys
import asyncio
from pathlib import Path

# 确保项目根目录在Python路径中
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from ..model_types import ReadResponse, TrackerContext, ReadResponseData
    from ..utils.token_tracker import TokenTracker
    from ..utils.action_tracker import ActionTracker
    from ..config import JINA_API_KEY
except ImportError:
    from deepresearch.model_types import ReadResponse, TrackerContext, ReadResponseData
    from deepresearch.utils.token_tracker import TokenTracker
    from deepresearch.utils.action_tracker import ActionTracker
    from deepresearch.config import JINA_API_KEY

JINA_READ_API_URL = "https://r.jina.ai/"


async def read_url(
    url: str,
    with_all_links: bool = False,
    tracker_context: Optional[TrackerContext] = None,
    timeout_ms: int = 60000,  # 默认超时时间60秒
) -> ReadResponse:
    """
    使用jina.ai API读取URL内容
    
    Args:
        url: 要读取的URL
        with_all_links: 是否获取所有链接信息
        timeout_ms: 请求超时时间（毫秒）
        tracker: 跟踪器上下文
        
    Returns:
        包含ReadResponse的字典
    """
    if not JINA_API_KEY:
        print("JINA_API_KEY未设置")
        raise ValueError("JINA_API_KEY not set")
    
    # 检查URL是否有效
    if not url.strip():
        raise ValueError("URL不能为空")
    
    if not url.startswith("http://") and not url.startswith("https://"):
        raise ValueError("无效URL，仅支持http和https类型的URL")
    
    # 准备请求数据
    data = {"url": url}
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {JINA_API_KEY}",
        "Content-Type": "application/json",
        "X-Retain-Images": "none",
        "X-Md-Link-Style": "discarded",
    }
    
    if with_all_links:
        headers["X-With-Links-Summary"] = "all"
    
    timeout_seconds = timeout_ms / 1000
    
    try:
        response = requests.post(
            JINA_READ_API_URL, 
            json=data, 
            headers=headers, 
            timeout=timeout_seconds
        )
        
        response.raise_for_status()
        response_data = response.json()
        
        # 解析成功的响应response_data
        read_response_data = ReadResponseData(
            title=response_data.get("data", {}).get("title", ""),
            description=response_data.get("data", {}).get("description", ""),
            url=response_data.get("data", {}).get("url", ""),
            content=response_data.get("data", {}).get("content", ""),
            usage=response_data.get("data", {}).get("usage", {}),
            links=response_data.get("data", {}).get("links", [])
        )
        
        response_obj = ReadResponse(
            code=response.status_code,
            status=response_data.get("status", 0),
            data=read_response_data,
            name=response_data.get("name", None),
            message=response_data.get("message", None),
            readable_message=response_data.get("readable_message", None)
        )
        
        if not response_obj.data:
            raise ValueError("无效的响应数据")
        
        # 打印读取信息
        print("【read_url】:", {
            "标题": response_obj.data.title,
            "URL": response_obj.data.url,
            "令牌数": response_obj.data.usage.get("tokens", 0)
        })
        
        # 追踪令牌使用情况
        tokens = response_obj.data.usage.get("tokens", 0)
        if tracker_context:
            tracker_context.token_tracker.track_usage(
                "read",
                {
                    "prompt_tokens": len(url),
                    "completion_tokens": 0,
                    "total_tokens": tokens,
                },
            )
        
        return response_obj
    
    except requests.exceptions.Timeout:
        print(f"读取请求超时: {timeout_ms}ms后超时")
        raise ValueError(f"请求超时: {timeout_ms}ms")
    except requests.exceptions.RequestException as error:
        print("URL读取出错:", error)
        raise ValueError(f"请求失败: {str(error)}")


if __name__ == "__main__":
    # 测试URL样本
    test_urls = [
        "https://qwenlm.github.io/zh/blog/qwen2.5/",
        "https://jina.ai/",
        "https://openai.com/research/index/",
        "https://blog.jina.ai/"
    ]
    
    # 运行异步测试函数
    async def run_tests():
        print("开始测试Jina URL读取工具...")
        
        # 为测试创建简单的令牌跟踪器
        tracker_context = TrackerContext(
            token_tracker=TokenTracker(),
            action_tracker=ActionTracker(),
        )
        
        for i, url in enumerate(test_urls):
            print(f"\n测试 {i+1}: {url}")
            
            try:
                result = await read_url(url, tracker_context=tracker_context)
                if result["response"].data:
                    print(f"标题: {result['response'].data.title}")
                    print(f"描述: {result['response'].data.description}")
                    print(f"内容长度: {len(result['response'].data.content)}")
                else:
                    print(f"读取失败: {result['response'].message}")
            except Exception as e:
                print(f"测试出错: {str(e)}")
        
        # 打印令牌使用情况
        print("\n令牌使用统计:")
        print(f"总使用令牌: {tracker_context.token_tracker.print_summary()}")
    
    # 运行测试
    asyncio.run(run_tests()) 