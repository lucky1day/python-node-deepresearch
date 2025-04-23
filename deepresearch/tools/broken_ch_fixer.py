import sys
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

# 确保项目根目录在Python路径中
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from openai import OpenAI
    from ..model_types import TrackerContext, PromptPair
    from ..utils.text_tools import detect_broken_unicode_via_file_io
    from ..config import OPENAI_API_KEY, OPENAI_BASE_URL, get_model
    from ..utils.action_tracker import ActionTracker
    from ..utils.token_tracker import TokenTracker
    from ..prompt_template_en import BROKEN_CH_FIXER_SYSTEM_PROMPT_TEMPLATE, BROKEN_CH_FIXER_USER_PROMPT_TEMPLATE
except ImportError:
    from openai import OpenAI
    from deepresearch.model_types import TrackerContext, PromptPair
    from deepresearch.utils.text_tools import detect_broken_unicode_via_file_io
    from deepresearch.config import OPENAI_API_KEY, OPENAI_BASE_URL, get_model
    from deepresearch.utils.action_tracker import ActionTracker
    from deepresearch.utils.token_tracker import TokenTracker
    from deepresearch.prompt_template_en import BROKEN_CH_FIXER_SYSTEM_PROMPT_TEMPLATE, BROKEN_CH_FIXER_USER_PROMPT_TEMPLATE




def get_prompt(unknown_count: int, left_context: str, right_context: str) -> PromptPair:
    """
    生成用于修复文本的提示对

    Args:
        unknown_count: 未知字符的数量
        left_context: 左侧上下文
        right_context: 右侧上下文

    Returns:
        包含系统提示和用户提示的PromptPair对象
    """
    # 格式化系统提示
    system_prompt = BROKEN_CH_FIXER_SYSTEM_PROMPT_TEMPLATE

    # 格式化用户提示
    user_prompt = BROKEN_CH_FIXER_USER_PROMPT_TEMPLATE.format(
        unknown_count=unknown_count,
        left_context=left_context,
        right_context=right_context,
    )

    return PromptPair(system=system_prompt, user=user_prompt)


async def repair_unknown_chars(
    md_content: str, trackers: Optional[TrackerContext] = None
) -> str:
    """
    修复包含�字符的markdown内容，使用AI模型猜测缺失的文本
    """
    # 检测是否有破损的Unicode字符
    broken_result = await detect_broken_unicode_via_file_io(md_content)
    broken = broken_result.get("broken", False)
    read_str = broken_result.get("read_str", md_content)

    # 如果没有破损字符，直接返回原始内容
    if not broken:
        return read_str

    print("检测到输出中有破损的Unicode字符，尝试修复...")

    repaired_content = read_str
    remaining_unknowns = True
    iterations = 0

    last_position = -1
    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    # 循环修复所有破损字符
    while remaining_unknowns and iterations < 20:
        iterations += 1

        # 查找第一个�字符的位置
        position = repaired_content.find("�")
        if position == -1:
            remaining_unknowns = False
            continue

        # 检查是否在同一位置卡住
        if position == last_position:
            # 通过删除字符跳过此位置
            repaired_content = (
                repaired_content[:position] + repaired_content[position + 1 :]
            )
            continue

        # 更新上一个位置以检测循环
        last_position = position

        # 计算连续的�字符数量
        unknown_count = 0
        for i in range(position, len(repaired_content)):
            if repaired_content[i] == "�":
                unknown_count += 1
            else:
                break

        # 提取未知字符周围的上下文
        context_size = 100
        start = max(0, position - context_size)
        end = min(len(repaired_content), position + unknown_count + context_size)
        left_context = repaired_content[start:position]
        right_context = repaired_content[position + unknown_count : end]

        # 让AI模型猜测缺失的字符
        try:
            # 获取提示
            prompt = get_prompt(unknown_count, left_context, right_context)

            result = client.chat.completions.create(
                model=get_model("fallback")["model"],
                messages=[
                    {"role": "system", "content": prompt.system},
                    {"role": "user", "content": prompt.user},
                ],
            )

            # 跟踪令牌使用情况
            if trackers and trackers.token_tracker:
                trackers.token_tracker.track_usage(
                    "md-fixer",
                    {
                        "prompt_tokens": result.usage.prompt_tokens,
                        "completion_tokens": result.usage.completion_tokens,
                        "total_tokens": result.usage.total_tokens,
                    },
                )

            replacement = result.choices[0].message.content.strip()

            # 验证替换文本
            if (
                replacement == "UNKNOWN"
                or (await detect_broken_unicode_via_file_io(replacement)).get(
                    "broken", False
                )
                or len(replacement) > unknown_count * 4
            ):
                print(f"跳过位置{position}处的无效替换 {replacement}")
                # 不修改内容，跳到下一个�字符
            else:
                # 用生成的文本替换未知序列
                repaired_content = (
                    repaired_content[:position]
                    + replacement
                    + repaired_content[position + unknown_count :]
                )

            print(
                f'修复迭代{iterations}：将{unknown_count}个�字符替换为"{replacement}"'
            )

        except Exception as error:
            print("修复未知字符时出错:", error)
            # 不修改此字符，跳到下一个�字符

    return repaired_content


if __name__ == "__main__":
    import asyncio

    async def test_repair_chars():
        # 创建测试数据
        test_content = """在 Qwen2 发布后的过去三个月里，许多���基于 Qwen2 语言模型构建了新的模型，并为我们提供了宝贵的反馈。在这段时间里，我们专注于创建更智能、更博学的语言模型。今天，我们很高兴地向大家介绍 Qwen 家族的最新成员：Qwen2.5。

我们将要宣布的可能是历史上最大的开源发布！让我们��这场盛会吧！

我们的最新发布包括了语言模型 Qwen2.5，以及专门针对编程的 Qwen2.5-Coder 和数学的 Qwen2.5-Math 模型。所有开放权重的模型都是稠密的、decoder-only的语��型，提供多种不同规模的版本，包括：

Qwen2.5: 0.5B, 1.5B, 3B, 7B, 14B, 32B, 以及72B;
Qwen2.5-Coder: 1.5B, 7B, 以及即将推出的32B;
Qwen2.5-Math: 1.5B, 7B, 以及72B。

除了3B和72B的版本外，我们所有的开源模型都采用了 Apache 2.0 许可�。您可以在相应的 Hugging Face 仓库中找到许可证文件。除此之外，我们还通过 Model Studio 提供了旗舰语言模型 Qwen-Plus 和 Qwen-Turbo 的 API，诚邀您来体验和使用！此外，我们还开源了相比上个月发布的版本有性能提升的 Qwen2-VL-72B。"""

        # 创建跟踪器
        tracker_context = TrackerContext(
            token_tracker=TokenTracker(), action_tracker=ActionTracker()
        )

        # 执行修复
        result = await repair_unknown_chars(test_content, tracker_context)

        # 打印结果
        print("\n测试结果：")
        print("=== 原始内容 ===")
        print(test_content)
        print("\n=== 修复后的内容 ===")
        print(result)

        return result

    # 运行测试
    asyncio.run(test_repair_chars())
