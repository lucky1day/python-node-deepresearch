import math
import requests
import numpy as np
from typing import Dict, List, Any, Optional
import sys
import asyncio
from pathlib import Path
import os

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

# 最大令牌数每个嵌入请求
MAX_TOKENS_PER_REQUEST = 8192
# 每个字符的令牌粗略估计
TOKENS_PER_CHARACTER = 0.4


async def cherry_pick(
    question: str,
    long_context: str,
    options: Dict = None,
    tracker_context: Optional[TrackerContext] = None,
    url: str = "",
    json_schema=None,
) -> str:
    """
    从长文本中提取与问题最相关的片段

    Args:
        question: 用户的问题
        long_context: 长文本内容
        options: 配置选项
        tracker: 令牌跟踪器对象
        url: 文本来源URL
        schema: 语言模式生成器对象

    Returns:
        提取的最相关片段
    """
    if options is None:
        options = {}

    # 设置默认选项
    snippet_length = options.get("snippet_length", 3000)  # 每个片段的字符长度
    num_snippets = options.get(
        "num_snippets", max(2, min(5, math.floor(len(long_context) / snippet_length)))
    )
    chunk_size = options.get("chunk_size", 300)  # 每个块的字符长度

    # 如果内容过短，直接返回整个内容
    if len(long_context) < snippet_length * 2:
        print(f"【cherry_pick】{url} 内容太短，不需要处理")
        return long_context

    # 将长文本分割成块
    chunks = []
    for i in range(0, len(long_context), chunk_size):
        chunks.append(long_context[i : min(i + chunk_size, len(long_context))])

    print(f"【late_chunk】{url} 启用后期分块！块数量: {len(chunks)}")

    # 如果有tracker，记录思考过程
    if (
        tracker_context
        and hasattr(tracker_context, "actionTracker")
        and hasattr(tracker_context.actionTracker, "trackThink")
    ):
        language_code = (
            json_schema.languageCode if json_schema and hasattr(json_schema, "languageCode") else None
        )
        tracker_context.actionTracker.trackThink("late_chunk", language_code, {"url": url})

    try:
        if question.strip() == "":
            raise ValueError("空问题，返回完整上下文")

        # 估计每个块的令牌数
        estimated_tokens_per_chunk = math.ceil(chunk_size * TOKENS_PER_CHARACTER)

        # 计算每批次的块数，以保持在令牌限制以下
        chunks_per_batch = math.floor(
            MAX_TOKENS_PER_REQUEST / estimated_tokens_per_chunk
        )

        # 创建块批次
        chunk_batches = []
        for i in range(0, len(chunks), chunks_per_batch):
            chunk_batches.append(chunks[i : i + chunks_per_batch])

        print(
            f"总长度 {len(long_context)} 分割 {len(chunks)} 个块，每个块的大小为 {chunk_size} 字符，分成 {len(chunk_batches)} 批，每批约 {chunks_per_batch} 个块"
        )

        # 处理每个批次并收集嵌入
        all_chunk_embeddings = []
        total_tokens_used = 0

        for batch_index, batch in enumerate(chunk_batches):
            print(
                f"处理批次 {batch_index + 1}/{len(chunk_batches)} 包含 {len(batch)} 个块"
            )

            # 获取当前批次的嵌入
            batch_embedding_result = await get_embeddings(
                input=batch,
                model="jina-embeddings-v3",
                task="retrieval.passage",
                late_chunking=True,
                embedding_type="float",
                dimensions=1024,
                truncate=True,
            )

            # 提取此批次的嵌入
            batch_embeddings = batch_embedding_result["embeddings"]

            # 验证响应格式
            if not batch_embeddings or len(batch_embeddings) != len(batch):
                raise ValueError("来自API的意外响应格式")

            all_chunk_embeddings.extend(batch_embeddings)

            # 跟踪令牌使用情况
            batch_tokens = batch_embedding_result["tokens"]
            total_tokens_used += batch_tokens

        # 获取问题的嵌入
        question_embedding_result = await get_embeddings(
            input=[question],
            model="jina-embeddings-v3",
            task="retrieval.query",
            dimensions=1024,
            embedding_type="float",
            truncate=True,
        )

        question_embedding = question_embedding_result["embeddings"][0]

        # 验证问题嵌入响应
        if (
            not question_embedding_result["embeddings"]
            or len(question_embedding_result["embeddings"]) == 0
        ):
            raise ValueError("API响应中未找到问题嵌入")

        # 跟踪问题嵌入的令牌使用情况
        question_tokens = question_embedding_result["tokens"]
        total_tokens_used += question_tokens

        # 跟踪总令牌使用情况
        if (
            tracker_context
            and hasattr(tracker_context, "tokenTracker")
            and hasattr(tracker_context.tokenTracker, "track_usage")
        ):
            tracker_context.tokenTracker.track_usage(
                "latechunk",
                {
                    "prompt_tokens": total_tokens_used,
                    "completion_tokens": 0,
                    "total_tokens": total_tokens_used,
                },
            )

        # 验证我们获得了所有块的嵌入
        if len(all_chunk_embeddings) != len(chunks):
            print(f"获得了 {len(all_chunk_embeddings)} 个嵌入，用于 {len(chunks)} 个块")

        # 计算问题与每个块之间的余弦相似度
        similarities = [
            cosine_similarity(question_embedding, chunk_embed)
            for chunk_embed in all_chunk_embeddings
        ]

        # 计算单个片段所需的块数
        chunks_per_snippet = math.ceil(snippet_length / chunk_size)

        # 找到平均相似度最高的前 `num_snippets` 个片段
        snippets = []

        # 创建相似度副本以避免修改原始数据
        similarities_copy = similarities.copy()

        for i in range(num_snippets):
            # 为片段找到最佳起始位置
            best_start_index = 0
            best_score = float("-inf")

            # 检查片段的每个可能起始位置
            for j in range(len(similarities) - chunks_per_snippet + 1):
                # 计算当前窗口的平均相似度
                window_scores = similarities_copy[j : j + chunks_per_snippet]
                window_score = sum(window_scores) / len(window_scores)

                if window_score > best_score:
                    best_score = window_score
                    best_start_index = j

            # 提取片段文本
            start_index = best_start_index * chunk_size
            end_index = min(start_index + snippet_length, len(long_context))
            snippets.append(long_context[start_index:end_index])

            # 将已使用的块标记为非常低的分数，以避免重复使用
            for k in range(
                best_start_index,
                min(best_start_index + chunks_per_snippet, len(similarities_copy)),
            ):
                similarities_copy[k] = float("-inf")

        # 用 <snippet-index> 标签包装
        return "\n\n".join(
            [
                f"<snippet-{i+1}>\n\n{snippet}\n\n</snippet-{i+1}>"
                for i, snippet in enumerate(snippets)
            ]
        )

    except Exception as error:
        print("后期分块出错:", error)
        # 只返回上下文的开头部分，直到所需长度
        return long_context[: snippet_length * num_snippets]


if __name__ == "__main__":
    async def test_cherry_pick():
        # 测试问题
        question = "千问的多语言能力怎么样？"
        
        long_context = """
        简介
        在 Qwen2 发布后的过去三个月里，许多开发者基于 Qwen2 语言模型构建了新的模型，并为我们提供了宝贵的反馈。在这段时间里，我们专注于创建更智能、更博学的语言模型。今天，我们很高兴地向大家介绍 Qwen 家族的最新成员：Qwen2.5。

        我们将要宣布的可能是历史上最大的开源发布！让我们开始这场盛会吧！

        我们的最新发布包括了语言模型 Qwen2.5，以及专门针对编程的 Qwen2.5-Coder 和数学的 Qwen2.5-Math 模型。所有开放权重的模型都是稠密的、decoder-only的语言模型，提供多种不同规模的版本，包括：

        Qwen2.5: 0.5B, 1.5B, 3B, 7B, 14B, 32B, 以及72B;
        Qwen2.5-Coder: 1.5B, 7B, 以及即将推出的32B;
        Qwen2.5-Math: 1.5B, 7B, 以及72B。

        除了3B和72B的版本外，我们所有的开源模型都采用了 Apache 2.0 许可证。您可以在相应的 Hugging Face 仓库中找到许可证文件。除此之外，我们还通过 Model Studio 提供了旗舰语言模型 Qwen-Plus 和 Qwen-Turbo 的 API，诚邀您来体验和使用！此外，我们还开源了相比上个月发布的版本有性能提升的 Qwen2-VL-72B。

        如需了解更多关于 Qwen2.5、Qwen2.5-Coder 和 Qwen2.5-Math 的详细信息，请随时访问以下链接：

        Qwen2.5 LLM Qwen2.5-Coder Qwen2.5-Math


        准备好迎接我们全面的模型系列所带来的无限可能吧！我们非常高兴能够与您分享这些前沿模型，并期待看到您使用它们所取得的非凡成就！

        要点总结
        就 Qwen2.5 语言模型而言，所有模型都在我们最新的大规模数据集上进行了预训练，该数据集包含多达 18T tokens。相较于 Qwen2，Qwen2.5 获得了显著更多的知识（MMLU：85+），并在编程能力（HumanEval 85+）和数学能力（MATH 80+）方面有了大幅提升。此外，新模型在指令执行、生成长文本（超过 8K 标记）、理解结构化数据（例如表格）以及生成结构化输出特别是 JSON 方面取得了显著改进。 Qwen2.5 模型总体上对各种system prompt更具适应性，增强了角色扮演实现和聊天机器人的条件设置功能。与 Qwen2 类似，Qwen2.5 语言模型支持高达 128K tokens，并能生成最多 8K tokens的内容。它们同样保持了对包括中文、英文、法文、西班牙文、葡萄牙文、德文、意大利文、俄文、日文、韩文、越南文、泰文、阿拉伯文等 29 种以上语言的支持。 我们在下表中提供了有关模型的基本信息。

        专业领域的专家语言模型，即用于编程的 Qwen2.5-Coder 和用于数学的 Qwen2.5-Math，相比其前身 CodeQwen1.5 和 Qwen2-Math 有了实质性的改进。 具体来说，Qwen2.5-Coder 在包含 5.5 T tokens 编程相关数据上进行了训练，使即使较小的编程专用模型也能在编程评估基准测试中表现出媲美大型语言模型的竞争力。 同时，Qwen2.5-Math 支持 中文 和 英文，并整合了多种推理方法，包括CoT（Chain of Thought）、PoT（Program of Thought）和 TIR（Tool-Integrated Reasoning）。
        """
        
        # 配置选项
        options = {
            "snippet_length": 100,  # 每个片段的字符长度
            "num_snippets": 2,      # 返回的片段数量
            "chunk_size": 50       # 每个块的字符长度
        }
        
        tracker_context = TrackerContext(
            token_tracker=TokenTracker(),
            action_tracker=ActionTracker()
        )

        # 调用cherry_pick函数
        try:
            result = await cherry_pick(
                question=question,
                long_context=long_context,
                options=options,
                tracker_context=tracker_context,
            )

            print("问题:", question)
            print("\n提取的相关片段:")
            print(result)
            
        except Exception as e:
            print(f"测试失败: {str(e)}")

    # 运行测试函数
    asyncio.run(test_cherry_pick())