"""
配置文件
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Optional, Any, Union

from dotenv import load_dotenv

MAX_URLS_PER_STEP = 4  # 每个步骤中允许访问的最大URL数量，限制以防止过度抓取和保持效率
MAX_QUERIES_PER_STEP = 4  # 每个步骤中允许执行的最大搜索查询数量，确保搜索请求的精确性和相关性
MAX_REFLECT_PER_STEP = 4  # 每个步骤中允许生成的最大反思问题数量，用于控制子问题的生成和管理知识缺口
MAX_URLS_READ_PER_STEP = 10  # 每个步骤中允许读取的最大URL数量，限制以防止过度抓取和保持效率

# 加载环境变量
load_dotenv()

# 加载配置文件
config_path = Path(__file__).parent.parent / "config.json"
with open(config_path, "r", encoding="utf-8") as f:
    config_json = json.load(f)

# 类型定义
ToolName = str

# 环境设置
env = {**config_json.get("env", {})}
for key in env:
    if os.getenv(key):
        env[key] = os.getenv(key) or env[key]

# 导出环境变量
OPENAI_BASE_URL = env.get("OPENAI_BASE_URL")
OPENAI_API_KEY = env.get("OPENAI_API_KEY")
OPENAI_API_MODEL = env.get("OPENAI_API_MODEL")
JINA_API_KEY = env.get("JINA_API_KEY")
JINA_API_URL = env.get("JINA_API_URL")
DEBUG = env.get("DEBUG", False)
SEARCH_PROVIDER = config_json.get("defaults", {}).get("search_provider", "jina")
STEP_SLEEP = config_json.get("defaults", {}).get("step_sleep", 500)
ALLOWED_CODING_LANGUAGES = ["python", "javascript", "typescript", "bash", "shell"]


try:
    provider = os.getenv("LLM_PROVIDER") or config_json.get("defaults", {}).get(
        "llm_provider", "openai"
    )
    LLM_PROVIDER = provider
except Exception as e:
    print(f"错误: {e}")
    LLM_PROVIDER = "openai"


def get_tool_config(tool_name: str) -> Dict[str, Any]:
    """获取工具配置

    Args:
        tool_name: 工具名称

    Returns:
        工具配置
    """
    provider_key = "gemini" if LLM_PROVIDER == "vertex" else LLM_PROVIDER
    provider_config = config_json.get("models", {}).get(provider_key, {})
    default_config = provider_config.get("default", {})
    tool_overrides = provider_config.get("tools", {}).get(tool_name, {})

    return {
        "model": os.getenv("DEFAULT_MODEL_NAME") or default_config.get("model"),
        "temperature": tool_overrides.get(
            "temperature", default_config.get("temperature")
        ),
        "max_tokens": tool_overrides.get("maxTokens", default_config.get("maxTokens")),
    }


def get_max_tokens(tool_name: str) -> int:
    """获取最大令牌数

    Args:
        tool_name: 工具名称

    Returns:
        最大令牌数
    """
    return get_tool_config(tool_name).get("max_tokens", 0)


def get_model(tool_name: str):
    """获取模型实例

    Args:
        tool_name: 工具名称

    Returns:
        模型实例
    """
    config = get_tool_config(tool_name)
    provider_config = config_json.get("providers", {}).get(LLM_PROVIDER, {})

    if LLM_PROVIDER == "openai":
        if not OPENAI_API_KEY:
            raise ValueError("未找到 OPENAI_API_KEY")

        # 在 Python 实现中，这里应当创建相应的 OpenAI 客户端
        # 由于 Python 版本对应的接口可能不同，这里仅作占位
        # 实际使用时应替换为实际的客户端创建逻辑
        return {
            "model": config["model"],
            "provider": "openai",
            "options": {"api_key": OPENAI_API_KEY, "base_url": OPENAI_BASE_URL},
        }

    # 在 Python 实现中，这里应当创建相应的 Gemini 客户端
    use_search_grounding = tool_name == "searchGrounding"

    return {
        "model": config["model"],
        "provider": "gemini",
        "use_search_grounding": use_search_grounding,
    }


# 验证必要的环境变量
if LLM_PROVIDER == "openai" and not OPENAI_API_KEY:
    raise ValueError("未找到 OPENAI_API_KEY")
if not JINA_API_KEY:
    raise ValueError("未找到 JINA_API_KEY")

# 日志记录所有配置
config_summary = {
    "provider": {
        "name": LLM_PROVIDER,
        "model": config_json.get("models", {})
        .get("openai" if LLM_PROVIDER == "openai" else "gemini", {})
        .get("default", {})
        .get("model"),
        **(
            {"baseUrl": OPENAI_BASE_URL}
            if LLM_PROVIDER == "openai" and OPENAI_BASE_URL
            else {}
        ),
    },
    "search": {"provider": SEARCH_PROVIDER},
    "tools": {
        name: get_tool_config(name)
        for name in config_json.get("models", {})
        .get("gemini" if LLM_PROVIDER == "vertex" else LLM_PROVIDER, {})
        .get("tools", {})
    },
    "defaults": {"stepSleep": STEP_SLEEP},
}

print("配置摘要:", json.dumps(config_summary, indent=2, ensure_ascii=False))
