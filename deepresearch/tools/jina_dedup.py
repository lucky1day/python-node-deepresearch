import requests
import numpy as np
from typing import Dict, List, Any, Optional
import sys
import asyncio
from pathlib import Path

# 确保项目根目录在Python路径中
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from ..model_types import TrackerContext
    from ..utils.token_tracker import TokenTracker
    from ..utils.action_tracker import ActionTracker
    from ..tools.jina_embedding import get_embeddings, cosine_similarity
except ImportError:
    from deepresearch.model_types import TrackerContext
    from deepresearch.utils.token_tracker import TokenTracker
    from deepresearch.utils.action_tracker import ActionTracker
    from deepresearch.tools.jina_embedding import get_embeddings, cosine_similarity


SIMILARITY_THRESHOLD = 0.86  # 可调整的余弦相似度阈值


async def dedup_queries(
    new_queries: List[str],
    existing_queries: List[str] = [],
    tracker_context: Optional[TrackerContext] = None,
) -> Dict[str, Any]:
    """
    对查询进行去重操作

    Args:
        new_queries: 新的查询列表
        existing_queries: 已有的查询列表（用于对比）
        similarity_threshold: 相似度阈值，超过此值视为重复
        timeout_ms: 请求超时时间（毫秒）
        tracker: 可选的令牌跟踪器

    Returns:
        去重后的唯一查询列表
    """
    # 快速路径：如果只有一个新查询且没有现有查询
    if len(new_queries) == 1 and not existing_queries:
        print(f"【dedup_queries】 \n New queries: {new_queries} \n Existing queries: {existing_queries} \n -> Unique queries: {new_queries}")
        return {"unique_queries": unique_queries}

    try:
        # 批量获取所有查询的嵌入向量
        all_queries = new_queries + existing_queries
        result = await get_embeddings(all_queries)
        all_embeddings = result.get("embeddings", [])
        tokens = result.get("tokens", 0)

        # 如果嵌入为空，返回所有新查询
        if not all_embeddings:
            return new_queries

        # 将嵌入分回新的和现有的
        new_embeddings = all_embeddings[: len(new_queries)]
        existing_embeddings = all_embeddings[len(new_queries) :]

        unique_queries = []
        used_indices = set()

        # 将每个新查询与现有查询和已接受的查询进行比较
        for i in range(len(new_queries)):
            is_unique = True

            # 与现有查询比较
            for j in range(len(existing_queries)):
                if (
                    cosine_similarity(new_embeddings[i], existing_embeddings[j]) >= SIMILARITY_THRESHOLD
                ):
                    is_unique = False
                    break

            # 与已接受的查询比较
            if is_unique:
                for used_index in used_indices:
                    if (
                        cosine_similarity(new_embeddings[i], new_embeddings[used_index]) >= SIMILARITY_THRESHOLD
                    ):
                        is_unique = False
                        break

            # 如果通过所有检查，则添加到唯一查询中
            if is_unique:
                unique_queries.append(new_queries[i])
                used_indices.add(i)

        # 跟踪API的令牌使用情况
        if tracker_context:
            tracker_context.token_tracker.track_usage(
                "dedup",
                {
                    "prompt_tokens": 0,
                    "completion_tokens": tokens,
                    "total_tokens": tokens,
                },
            )

        print(f"【dedup_queries】 \n New queries: {new_queries} \n Existing queries: {existing_queries} \n -> Unique queries: {unique_queries}")
        return {"unique_queries": unique_queries,}

    except Exception as error:
        print("去重分析中出错:", error)
        return new_queries


if __name__ == "__main__":
    # 测试查询样本
    test_queries = [
        "如何提高英语口语水平？",
        "怎样才能让英语口语变得更好？",
        "学习Python的最佳资源是什么？",
        "编程初学者如何学习Python？",
        "机器学习的基础知识有哪些？",
    ]

    # 运行异步测试函数
    async def run_tests():
        print("开始测试Jina查询去重...")

        # 为测试创建简单的令牌跟踪器
        tracker_context = TrackerContext(
            token_tracker=TokenTracker(), action_tracker=ActionTracker()
        )

        # 测试场景1：相似查询去重
        print("\n测试场景1: 相似查询去重")
        result1 = await dedup_queries(test_queries, [], tracker_context=tracker_context)
        print(f"原始查询数: {len(test_queries)}")
        print(f"去重后查询数: {len(result1)}")
        print(f"去重后查询: {result1}")

        # 测试场景2：与现有查询对比去重
        print("\n测试场景2: 与现有查询对比去重")
        existing = ["Python学习资源推荐", "机器学习入门指南"]
        result2 = await dedup_queries(test_queries, existing, tracker_context=tracker_context)
        print(f"新查询: {test_queries}")
        print(f"现有查询: {existing}")
        print(f"去重后查询: {result2}")

        # 打印令牌使用情况
        print("\n令牌使用统计:")
        print(f"总使用令牌: {tracker_context.token_tracker.print_summary()}")

    # 运行测试
    asyncio.run(run_tests())
