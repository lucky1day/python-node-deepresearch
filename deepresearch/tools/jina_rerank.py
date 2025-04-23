import requests
from typing import List, Dict, Any, Optional
import sys
import asyncio
from pathlib import Path

# 确保项目根目录在Python路径中
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from ..model_types import TrackerContext
    from ..utils.token_tracker import TokenTracker
    from ..utils.action_tracker import ActionTracker
    from ..config import JINA_API_KEY
except ImportError:
    from deepresearch.model_types import TrackerContext
    from deepresearch.utils.token_tracker import TokenTracker
    from deepresearch.utils.action_tracker import ActionTracker
    from deepresearch.config import JINA_API_KEY

JINA_API_URL = 'https://api.jina.ai/v1/rerank'


async def rerank_documents(
    query: str,
    documents: List[str],
    model: str = "jina-reranker-v2-base-multilingual",
    timeout_ms: int = 30000,  # 默认超时时间30秒
    tracker_context: Optional[TrackerContext] = None
) -> Dict[str, List[Dict[str, Any]]]:
    """
    对一组文档进行重排序，基于它们与查询的相关性
    
    Args:
        query: 用于对文档进行排序的查询
        documents: 要排序的文档数组
        model: 使用的重排序模型
        timeout_ms: 请求超时时间（毫秒）
        tracker: 可选的令牌跟踪器，用于使用情况监控
        
    Returns:
        包含重新排序的文档及其分数的结果数组
    """
    if not JINA_API_KEY:
        print('JINA_API_KEY未设置')
        return {"results": []}

    request = {
        "model": model,
        "query": query,
        "top_n": len(documents),
        "documents": documents
    }

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {JINA_API_KEY}'
    }

    timeout_seconds = timeout_ms / 1000

    try:
        response = requests.post(
            JINA_API_URL,
            json=request,
            headers=headers,
            timeout=timeout_seconds
        )
        
        response.raise_for_status()
        data = response.json()

        # 跟踪API的令牌使用情况
        if tracker_context and "usage" in data:
            tracker_context.token_tracker.track_usage('rerank', {
                'prompt_tokens': data['usage']['total_tokens'],
                'completion_tokens': 0,
                'total_tokens': data['usage']['total_tokens']
            })

        return {
            "results": data['results']
        }
    except requests.exceptions.Timeout:
        print(f"重排序请求超时: {timeout_ms}ms后超时")
    except requests.exceptions.RequestException as error:
        print('重排序文档时出错:', error)
        
    # 如果有错误，返回空结果
    return {
        "results": []
    }


if __name__ == "__main__":
    # 测试文档和查询
    test_query = "什么是人工智能"
    test_documents = [
        "这个问题与主题完全无关，不包含任何关于人工智能的信息。"
        "深度学习是机器学习的一种方法，它利用神经网络模拟人脑结构进行学习。",
        "人工智能（Artificial Intelligence，缩写为AI）是计算机科学的一个分支，它致力于研发能够模拟、延伸和扩展人类智能的理论、方法、技术及应用系统。",
        "机器学习是人工智能的一个子领域，专注于开发能够从数据中学习的算法和统计模型。",
        "自然语言处理（NLP）是人工智能的一个重要研究方向，目标是使计算机能够理解、解释和生成人类语言。",
    ]

    # 运行异步测试函数
    async def run_tests():
        print("开始测试Jina重排序API...")

        # 为测试创建简单的令牌跟踪器
        tracker_context = TrackerContext(
            token_tracker=TokenTracker(),
            action_tracker=ActionTracker()
        )

        results = await rerank_documents(
            query=test_query,
            documents=test_documents,
            tracker_context=tracker_context
        )
        
        print(f"\n查询: {test_query}")
        print("\n重排序结果:")
        
        if results["results"]:
            for i, result in enumerate(results["results"]):
                print(f"\n{i+1}. 分数: {result['relevance_score']:.4f}")
                print(f"   文档: {result['document'][:100]}..." if len(result['document']) > 100 else f"   文档: {result['document']}")
        else:
            print("未获取到结果")

        # 打印令牌使用情况
        print("\n令牌使用统计:")
        print(f"总使用令牌: {tracker_context.token_tracker.print_summary()}")
            

    # 运行测试
    asyncio.run(run_tests()) 