from typing import Dict, List, Tuple, Any
import sys
from pathlib import Path

# 确保项目根目录在Python路径中
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from ..model_types import ErrorAnalysisResponse, PromptPair, TrackerContext
    from ..utils.safe_generator import ObjectGeneratorSafe
    from ..utils.schemas import JsonSchemaGen
    from ..prompt_template import ERROR_ANALYZER_SYSTEM_PROMPT_TEMPLATE, ERROR_ANALYZER_USER_PROMPT_TEMPLATE
except ImportError:
    from deepresearch.model_types import ErrorAnalysisResponse, PromptPair, TrackerContext
    from deepresearch.utils.safe_generator import ObjectGeneratorSafe
    from deepresearch.utils.schemas import JsonSchemaGen
    from deepresearch.prompt_template import ERROR_ANALYZER_SYSTEM_PROMPT_TEMPLATE, ERROR_ANALYZER_USER_PROMPT_TEMPLATE


TOOL_NAME = 'errorAnalyzer'


def get_prompt(diary_context: List[str]) -> PromptPair:
    """
    获取提示
    
    Args:
        diary_context: 日志上下文列表
        
    Returns:
        提示对
    """
    # 格式化系统提示
    system_prompt = ERROR_ANALYZER_SYSTEM_PROMPT_TEMPLATE
    
    # 格式化用户提示
    user_prompt = ERROR_ANALYZER_USER_PROMPT_TEMPLATE.format(
        diary_context=diary_context
    )
    
    return PromptPair(
        system=system_prompt,
        user=user_prompt
    )


async def analyze_steps(
    diary_context: List[str],
    trackers: TrackerContext,
    schema_gen: JsonSchemaGen
) -> ErrorAnalysisResponse:
    """分析步骤并提供错误分析"""
    try:
        generator = ObjectGeneratorSafe(trackers.token_tracker)
        prompt = get_prompt(diary_context)

        result = await generator.generate_object({     
            "model": TOOL_NAME,
            "schema": schema_gen.get_error_analysis_schema(),
            "system": prompt.system,
            "prompt": prompt.user
        })

        print(f"【error_analyzer】: {prompt.system}")
        print(f"【error_analyzer】: {prompt.user}")
        print(f"【error_analyzer】: {result.object}")
        trackers.action_tracker.track_think(result.object["blame"])
        trackers.action_tracker.track_think(result.object["improvement"])

        return ErrorAnalysisResponse(
            recap=result.object["recap"],
            blame=result.object["blame"],
            improvement=result.object["improvement"]
        )

    except Exception as error:
        print(f"Error in {TOOL_NAME}", error)
        raise error


if __name__ == "__main__":
    import asyncio
    from deepresearch.utils.token_tracker import TokenTracker
    from deepresearch.utils.action_tracker import ActionTracker
    
    
    async def test_analyze_steps():
        # 创建测试数据
        test_diary_context = """
<steps>
At step 1, you took the **search** action and look for external information for the question: "how old is jina ai ceo?".
In particular, you tried to search for the following keywords: "jina ai ceo age".
You found quite some information and add them to your URL list and **visit** them later when needed. 

At step 2, you took the **search** action and look for external information for the question: "how old is jina ai ceo?".
In particular, you tried to search for the following keywords: "Han Xiao birthdate".
But you couldn't find useful information.

At step 3, you took **answer** action but evaluator thinks it is not a good answer:
</steps>

Original question: 
how old is jina ai ceo?

Your answer: 
The age of the Jina AI CEO cannot be determined from the available information.

The evaluator thinks your answer is bad because: 
The answer is not definitive and fails to provide the requested information.
"""
        
        # 创建跟踪器
        tracker_context = TrackerContext(
            token_tracker=TokenTracker(),
            action_tracker=ActionTracker()
        )
        
        # 创建模式对象
        schemas = JsonSchemaGen()
        
        # 执行分析
        result = await analyze_steps(test_diary_context, tracker_context, schemas)
        
        # 打印结果
        print("\n测试结果：")
        print("分析摘要:", result.recap)
        print("问题原因:", result.blame)
        print("改进建议:", result.improvement)
        
        return result
    
    # 运行测试
    asyncio.run(test_analyze_steps()) 