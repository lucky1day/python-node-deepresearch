"""
令牌跟踪器
"""

from typing import Dict, Any, Optional, List, Union
import tiktoken
import sys
from pyee import EventEmitter


class TokenTracker(EventEmitter):
    """
    跟踪和限制令牌使用，兼容TypeScript版本的功能
    """

    def __init__(self, budget: Optional[int] = 1_000_000):
        """
        初始化令牌跟踪器

        Args:
            budget: 可选的令牌预算上限
        """
        super().__init__()
        self.budget = budget
        self.usages: List[Dict[str, Any]] = []
        self.encoding = tiktoken.get_encoding("cl100k_base")  # OpenAI的标准编码

        # 检查全局上下文对象是否可用，类似TS版本中的asyncLocalContext
        if hasattr(sys, "asyncLocalContext"):

            def on_usage_callback(*args):
                async_local_context = getattr(sys, "asyncLocalContext")
                if (
                    hasattr(async_local_context, "available")
                    and async_local_context.available()
                ):
                    async_local_context.ctx.chargeAmount = self.get_total_usage()[
                        "total_tokens"
                    ]

            self.on("usage", on_usage_callback)

    def track_usage(self, tool: str, usage: Dict[str, int]) -> None:
        """
        跟踪令牌使用情况

        Args:
            tool: 使用的工具名称
            usage: 包含prompt_tokens、completion_tokens和total_tokens的使用情况字典
        """
        u = {"tool": tool, "usage": usage}
        self.usages.append(u)
        self.emit("usage", usage)

    def get_total_usage(self) -> Dict[str, int]:
        """
        获取总的令牌使用情况

        Returns:
            包含prompt_tokens、completion_tokens和total_tokens的字典
        """
        result = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        for item in self.usages:
            usage = item["usage"]
            result["prompt_tokens"] += usage.get("prompt_tokens")
            result["completion_tokens"] += usage.get("completion_tokens")
            result["total_tokens"] += usage.get("total_tokens")
        return result

    def get_usage_breakdown(self) -> Dict[str, int]:
        """
        获取按工具细分的令牌使用情况

        Returns:
            以工具名为键，总令牌数为值的字典
        """
        result: Dict[str, int] = {}
        for item in self.usages:
            tool = item["tool"]
            usage = item["usage"]
            if tool not in result:
                result[tool] = 0
            result[tool] += usage.get("total_tokens", 0)
        return result

    def print_summary(self) -> None:
        """
        打印令牌使用情况摘要
        """
        print(
            "令牌使用摘要:",
            {
                "budget": self.budget,
                "total": self.get_total_usage(),
                "breakdown": self.get_usage_breakdown()
            },
        )

    def reset(self) -> None:
        """
        重置令牌使用记录
        """
        self.usages = []
