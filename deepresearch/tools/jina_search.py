"""
Jina搜索工具 - 使用Jina API进行网络搜索
"""

import requests
import json
import sys
from pathlib import Path
from typing import Optional

# 确保项目根目录在Python路径中
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from ..model_types import SearchResponse, SearchResult, TrackerContext
    from ..config import JINA_API_KEY, DEBUG
    from ..utils.token_tracker import TokenTracker
    from ..utils.action_tracker import ActionTracker
except ImportError:
    from deepresearch.model_types import SearchResponse, SearchResult, TrackerContext
    from deepresearch.config import JINA_API_KEY, DEBUG
    from deepresearch.utils.token_tracker import TokenTracker
    from deepresearch.utils.action_tracker import ActionTracker


async def search(query: str, tracker_context: Optional[TrackerContext] = None) -> SearchResponse:
    """
    使用Jina的API进行网络搜索

    Args:
        query: 搜索查询
        tracker: 可选的令牌跟踪器

    Returns:
        SearchResponse 对象

    Raises:
        Exception: 如果API密钥未设置或请求失败
    """
    if not query.strip():
        raise Exception("查询不能为空")

    if not JINA_API_KEY:
        raise Exception("JINA_API_KEY未设置")

    try:
        url = f"https://s.jina.ai/?q={query}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {JINA_API_KEY}",
            "X-Respond-With": "no-content",
        }

        # 设置超时
        timeout_seconds = 60.0

        # 发送请求
        response = requests.get(url, headers=headers, timeout=timeout_seconds)
        response.raise_for_status()  # 会自动处理HTTP错误

        # 解析响应JSON
        response_data = response.json()

        # 检查响应数据格式
        if not response_data.get("data") or not isinstance(
            response_data.get("data"), list
        ):
            raise Exception("无效的响应格式")

        # 计算令牌总数
        total_tokens = sum(
            item.get("usage", {}).get("tokens", 0)
            for item in response_data.get("data", [])
        )
        if DEBUG:
            print(f'总URL数: {len(response_data.get("data", []))}')

        # 追踪令牌使用情况
        tracker_context.token_tracker.track_usage(
            "search",
            {
                "prompt_tokens": len(query),
                "completion_tokens": total_tokens,
                "total_tokens": 0,
            },
        )

        # 将原始响应数据转换为 SearchResult 对象列表
        search_results = []
        for item in response_data.get("data", []):
            search_result = SearchResult(
                title=item.get("title", ""),
                description=item.get("description", ""),
                url=item.get("url", ""),
                content=item.get("content", ""),
                usage=item.get("usage", {"tokens": 0}),
            )
            search_results.append(search_result)

        # 创建并返回 SearchResponse 对象
        return SearchResponse(
            code=response.status_code,
            status=response_data.get("status", 0),
            data=search_results,
            name=response_data.get("name"),
            message=response_data.get("message"),
            readable_message=response_data.get("readable_message"),
        )

    except requests.exceptions.HTTPError as e:
        # 处理HTTP错误
        if e.response.status_code == 402:
            try:
                error_data = e.response.json()
                error_msg = error_data.get("readableMessage") or "余额不足"
            except:
                error_msg = "余额不足"
            raise Exception(error_msg)

        try:
            error_data = e.response.json()
            error_msg = error_data.get("readableMessage")
        except:
            error_msg = None

        raise Exception(error_msg or f"HTTP错误 {e.response.status_code}")

    except requests.exceptions.Timeout:
        raise Exception(f"请求超时: {timeout_seconds}秒后超时")

    except requests.exceptions.RequestException as e:
        raise Exception(f"请求失败: {str(e)}")

    except json.JSONDecodeError:
        raise Exception("解析响应失败: 无效的JSON格式")

    except Exception as e:
        if DEBUG:
            print(f"搜索查询失败: {str(e)}")
        raise Exception(f"搜索查询失败: {str(e)}")


if __name__ == "__main__":
    # 测试代码
    import asyncio

    async def test():
        # 为测试创建简单的令牌跟踪器
        tracker_context = TrackerContext(
            token_tracker=TokenTracker(),
            action_tracker=ActionTracker()
        )

        query = " 如何复现 deep research"
        try:
            result = await search(query, tracker_context=tracker_context)

            if result.data:
                print(f"找到 {len(result.data)} 个结果:")

                for i, item in enumerate(result.data[:3]):  # 只打印前3个结果
                    print(f"\n--- 结果 {i+1} ---")
                    print(f"标题: {item.title}")
                    print(f"URL: {item.url}")
                    print(
                        f"描述: {item.description[:100]}..."
                        if len(item.description) > 100
                        else f"描述: {item.description}"
                    )
        except Exception as e:
            print(f"测试出错: {e}")

        # 打印令牌使用情况
        print("\n令牌使用统计:")
        print(f"总使用令牌: {tracker_context.token_tracker.print_summary()}")

    asyncio.run(test())
