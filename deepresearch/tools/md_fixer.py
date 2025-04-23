import sys
from pathlib import Path
from typing import List

# 确保项目根目录在Python路径中
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from openai import OpenAI
    from ..model_types import KnowledgeItem, PromptPair, TrackerContext, Reference
    from ..utils.text_tools import get_knowledge_str
    from ..config import OPENAI_API_KEY, OPENAI_BASE_URL, get_model
    from ..utils.schemas import JsonSchemaGen
    from ..prompt_template_en import MD_FIXER_SYSTEM_PROMPT_TEMPLATE, MD_FIXER_USER_PROMPT_TEMPLATE
except ImportError:
    from openai import OpenAI
    from deepresearch.model_types import KnowledgeItem, PromptPair, TrackerContext, Reference
    from deepresearch.utils.text_tools import get_knowledge_str
    from deepresearch.config import OPENAI_API_KEY, OPENAI_BASE_URL, get_model
    from deepresearch.utils.schemas import JsonSchemaGen
    from deepresearch.prompt_template_en import MD_FIXER_SYSTEM_PROMPT_TEMPLATE, MD_FIXER_USER_PROMPT_TEMPLATE

# 工具名称
TOOL_NAME = 'md-fixer'


def get_prompt(md_content: str, all_knowledge: List[KnowledgeItem]) -> PromptPair:
    """生成用于修复Markdown内容的提示"""
    knowledge_str = get_knowledge_str(all_knowledge)
    
    # 格式化系统提示
    system_prompt = MD_FIXER_SYSTEM_PROMPT_TEMPLATE.format(
        knowledge_str=knowledge_str
    )
    
    # 格式化用户提示
    user_prompt = MD_FIXER_USER_PROMPT_TEMPLATE.format(
        md_content=md_content
    )
    
    return PromptPair(
        system=system_prompt,
        user=user_prompt
    )


async def fix_markdown(
    md_content: str,
    knowledge_items: List[KnowledgeItem],
    tracker_context: TrackerContext,
    schema: JsonSchemaGen
) -> str:
    """修复Markdown内容，修复格式问题并增强内容"""
    try:
        prompt = get_prompt(md_content, knowledge_items)
        tracker_context.action_tracker.track_think('final_answer', schema.language_code)
        
        client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        result = client.chat.completions.create(
            model=get_model('evaluator')["model"],
            messages=[
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user}
            ]
        )
        mc_content_new = result.choices[0].message.content
        
        tracker_context.token_tracker.track_usage('md-fixer', {
            'prompt_tokens': result.usage.prompt_tokens,
            'completion_tokens': result.usage.completion_tokens,
            'total_tokens': result.usage.total_tokens
        })

        print(TOOL_NAME, mc_content_new)
        print('修复前/后长度对比:', len(md_content), len(mc_content_new))
        
        # 如果修复后的内容显著短于原始内容，返回原始内容
        if len(mc_content_new) < len(md_content) * 0.85:
            print(f"修复后的内容长度{len(mc_content_new)}显著短于原始内容{len(md_content)}，改为返回原始内容。")
            return md_content
            
        return mc_content_new
        
    except Exception as error:
        print(f"在{TOOL_NAME}中出错", error)
        return md_content 


if __name__ == "__main__":
    import asyncio
    from deepresearch.model_types import KnowledgeItem
    from deepresearch.utils.token_tracker import TokenTracker
    from deepresearch.utils.action_tracker import ActionTracker
    
    
    async def test_fix_markdown():
        # 创建测试数据
        test_md_content = """
# 这是一个测试标题

这是一段带有**粗体**和*斜体*的文本。

## 损坏的表格

| 列1 | 列2 | 列3 |
| --- | --- |
| 数据1 | 数据2 | 数据3 |
| 数据4 | 数据5 |

## 损坏的列表

- 列表项1
  - 子列表项1
 - 错误缩进的项目
   - 更深的子列表项
     ```
     代码块没有正确缩进
     ```

## 损坏的代码块

```python
def hello_world():
    print("Hello World!")
"""
        
        # 创建测试知识项目
        test_knowledge_items = [
            KnowledgeItem(
                type="qa",
                question="如何修复Markdown表格?",
                answer="Markdown表格需要每列有对应的头部和分隔行。每行的列数应该一致。",
                references=[
                    Reference(
                        exact_quote="Markdown表格需要每列有对应的头部和分隔行",
                        url="https://example.com/markdown-guide"
                    )
                ]
            ),
            KnowledgeItem(
                type="qa",
                question="如何正确格式化Markdown列表?",
                answer="嵌套列表应该使用适当的缩进，通常是4个空格或2个空格。",
                references=[
                    Reference(
                        exact_quote="嵌套列表应该使用适当的缩进",
                        url="https://example.com/markdown-lists"
                    )
                ]
            )
        ]
        
        # 创建跟踪器
        tracker_context = TrackerContext(
            token_tracker=TokenTracker(),
            action_tracker=ActionTracker()
        )
        
        # 创建模式对象
        schemas = JsonSchemaGen()
        
        # 执行Markdown修复
        result = await fix_markdown(test_md_content, test_knowledge_items, tracker_context, schemas)
        
        # 打印结果
        print("\n测试结果：")
        print("=== 原始Markdown内容 ===")
        print(test_md_content)
        print("\n=== 修复后的Markdown内容 ===")
        print(result)
        
        return result
    
    # 运行测试
    asyncio.run(test_fix_markdown()) 