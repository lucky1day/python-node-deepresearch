from datetime import datetime
from typing import List
import json
import sys
from pathlib import Path

# 确保项目根目录在Python路径中
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from ..config import get_model
    from ..model_types import PromptPair, SearchAction, SERPQuery, TrackerContext
    from ..utils.safe_generator import ObjectGeneratorSafe
    from ..utils.token_tracker import TokenTracker
    from ..utils.action_tracker import ActionTracker
    from ..utils.schemas import JsonSchemaGen
    from ..prompt_template_en import (
        QUERY_REWRITER_SYSTEM_PROMPT_TEMPLATE,
        QUERY_REWRITER_USER_PROMPT_TEMPLATE,
    )
except ImportError:
    from deepresearch.config import get_model
    from deepresearch.model_types import PromptPair, SearchAction, SERPQuery, TrackerContext
    from deepresearch.utils.safe_generator import ObjectGeneratorSafe
    from deepresearch.utils.token_tracker import TokenTracker
    from deepresearch.utils.action_tracker import ActionTracker
    from deepresearch.utils.schemas import JsonSchemaGen
    from deepresearch.prompt_template_en import (
        QUERY_REWRITER_SYSTEM_PROMPT_TEMPLATE,
        QUERY_REWRITER_USER_PROMPT_TEMPLATE,
    )


# 工具名称
TOOL_NAME = "queryRewriter"


def get_prompt(query: str, think: str, context: str) -> PromptPair:
    """
    获取提示

    Args:
        query: 查询
        think: 思考
        context: 上下文

    Returns:
        提示对
    """
    current_time = datetime.now()
    current_year = current_time.year
    current_month = current_time.month

    # 格式化系统提示
    system_prompt = QUERY_REWRITER_SYSTEM_PROMPT_TEMPLATE.format(
        current_time=current_time.isoformat(),
        current_year=current_year,
        current_month=current_month,
    )

    # 格式化用户提示
    user_prompt = QUERY_REWRITER_USER_PROMPT_TEMPLATE.format(
        query=query, think=think, context=context
    )

    return PromptPair(system=system_prompt, user=user_prompt)


async def rewrite_query(
    action: SearchAction,
    context: str,
    tracker_context: TrackerContext,
    schemas: JsonSchemaGen,
) -> List[SERPQuery]:
    """
    重写查询

    Args:
        action: 搜索动作
        context: 上下文
        trackers: 跟踪器上下文
        schemas: 模式生成器

    Returns:
        重写后的搜索查询列表
    """
    try:
        generator = ObjectGeneratorSafe(tracker_context.token_tracker)

        query_promises = []
        for req in action.search_requests:
            prompt = get_prompt(req, action.think, context)
            result = await generator.generate_object(
                {
                    "model": TOOL_NAME,
                    "schema": schemas.get_query_rewriter_schema(),
                    "system": prompt.system,
                    "prompt": prompt.user,
                    "num_retries": 0,
                }
            )

            tracker_context.action_tracker.track_think(result.object.get("think", ""))
            query_promises.append(result.object.get("queries", []))

        # 合并所有查询
        all_queries = []
        for queries in query_promises:
            all_queries.extend(queries)

        print(f"【rewrite_query】: {json.dumps(all_queries, indent = 4, ensure_ascii=False)}")
        return all_queries
    except Exception as error:
        print(f"Error in {TOOL_NAME}", error)
        raise error


if __name__ == "__main__":
    import asyncio
    import json
    from deepresearch.model_types import SearchAction
    from deepresearch.utils.token_tracker import TokenTracker
    from deepresearch.utils.action_tracker import ActionTracker

    async def test_rewrite_query():
        # 创建测试数据
        test_query = "人工智能应用"
        test_think = "我想了解人工智能在现实生活中的应用，特别是在医疗和教育领域，不限制国家和语言"
        test_context = """
        人工智能正在改变医疗保健行业，从诊断工具到个性化治疗方案。
        教育领域的AI应用包括自适应学习系统和智能辅导工具。
        许多公司正在将AI集成到他们的业务流程中，以提高效率和降低成本。
        """

        # 创建测试对象
        action = SearchAction(search_requests=[test_query], think=test_think)

        # 创建跟踪器
        tracker_context = TrackerContext(
            token_tracker=TokenTracker(), action_tracker=ActionTracker()
        )

        # 创建模式对象
        schemas = JsonSchemaGen()

        # 执行查询重写
        result = await rewrite_query(action, test_context, tracker_context, schemas)

        # 打印结果
        print("\n测试结果：")
        print(f"原始查询: {test_query}")
        print(f"思考内容: {test_think}")
        print("\n重写后的查询列表:")
        for i, query in enumerate(result, 1):
            print(f"{i}. {json.dumps(query, ensure_ascii=False, indent=2)}")

        return result

    # 运行测试
    asyncio.run(test_rewrite_query())
