import requests
from typing import Optional
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

JINA_API_URL = "https://api.jina.ai/v1/classify"


async def classify_text(
    text: str,
    classifier_id: str = "4a27dea0-381e-407c-bc67-250de45763dd",  # 默认垃圾邮件分类器ID
    timeout_ms: int = 30000,  # 默认超时时间30秒
    tracker_context: Optional[TrackerContext] = None,
) -> bool:
    """
    使用Jina AI对文本进行分类

    Args:
        text: 要分类的文本
        classifier_id: 分类器ID
        timeout_ms: 请求超时时间（毫秒）
        tracker: 可选的令牌跟踪器

    Returns:
        文本是否为垃圾信息的布尔值
    """
    if not JINA_API_KEY:
        print("JINA_API_KEY未设置")
        return False

    request = {"classifier_id": classifier_id, "input": [text]}

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {JINA_API_KEY}",
    }

    timeout_seconds = timeout_ms / 1000

    try:
        response = requests.post(
            JINA_API_URL, json=request, headers=headers, timeout=timeout_seconds
        )

        response.raise_for_status()
        data = response.json()

        if tracker_context and "usage" in data:
            tracker_context.token_tracker.track_usage(
                "classify",
                {
                    "prompt_tokens": data["usage"]["total_tokens"],
                    "completion_tokens": 0,
                    "total_tokens": data["usage"]["total_tokens"],
                },
            )

        if data.get("data") and data["data"]:
            return data["data"][0]["prediction"] == "true"

    except requests.exceptions.Timeout:
        print(f"分类请求超时: {timeout_ms}ms后超时")
    except requests.exceptions.RequestException as error:
        print("文本分类出错:", error)

    return False


if __name__ == "__main__":
    # 测试文本样本
    test_texts = [
        "您好，这是关于下周项目进度会议的通知，请各位准时参加，谢谢。",
        "恭喜您！您已被选中获得价值10000元的免费大奖，请在24小时内回复领取。",
        "注意：您的账户将被冻结，请立即汇款2000元至以下账号解冻：62220000111122223333",
        "Introduction\nIn the past five months since Qwen2-VL's release, numerous developers have built new models on the Qwen2-VL vision-language models, providing us with valuable feedback. During this period, we focused on building more useful vision-language models. Today, we are excited to introduce the latest addition to the Qwen family: Qwen2.5-VL.\n\nKey Enhancements:\nPowerful Document Parsing Capabilities: Upgrade text recognition to omnidocument parsing, excelling in processing multi-scene, multilingual, and various built-in (handwriting, tables, charts, chemical formulas, and music sheets) documents.\n\nPrecise Object Grounding Across Formats: Unlock improved accuracy in detecting, pointing, and counting objects, accommodating absolute coordinate and JSON formats for advanced spatial reasoning.\n\nUltra-long Video Understanding and Fine-grained Video Grounding: Extend native dynamic resolution to the temporal dimension, enhancing the ability to understand videos lasting hours while extracting event segments in seconds.\n\nEnhanced Agent Functionality for Computer and Mobile Devices: Leverage advanced grounding, reasoning, and decision-making abilities, boosting the model with superior agent functionality on smartphones and computers.\n",
    ]

    # 运行异步测试函数
    async def run_tests():
        print("开始测试Jina垃圾邮件分类器...")

        # 为测试创建简单的令牌跟踪器
        tracker_context = TrackerContext(
            token_tracker=TokenTracker(),
            action_tracker=ActionTracker(),
        )

        for i, text in enumerate(test_texts):
            print(
                f"\n测试 {i+1}: {text[:50]}..."
                if len(text) > 50
                else f"\n测试 {i+1}: {text}"
            )

            try:
                result = await classify_text(text, tracker_context=tracker_context)
                status = "垃圾邮件" if result else "正常邮件"
                print(f"分类结果: {status}")
            except Exception as e:
                print(f"测试出错: {e}")

        # 打印令牌使用情况
        print("\n令牌使用统计:")
        print(f"总使用令牌: {tracker_context.token_tracker.print_summary()}")

    # 运行测试
    asyncio.run(run_tests())
