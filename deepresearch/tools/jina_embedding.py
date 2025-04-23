import requests
import numpy as np
from typing import Dict, List, Any
import sys
from pathlib import Path

# 确保项目根目录在Python路径中
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from ..config import JINA_API_KEY, JINA_API_URL
except ImportError:
    from deepresearch.config import JINA_API_KEY, JINA_API_URL


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """计算两个向量之间的余弦相似度"""
    a = np.array(vec_a)
    b = np.array(vec_b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


async def get_embeddings(
    input: List[str],
    model: str = "jina-embeddings-v3",
    task: str = "text-matching",
    dimensions: int = 1024,
    embedding_type: str = "float",
    late_chunking: bool = False,
    timeout_ms: int = 30000,
    truncate: bool = True,
) -> Dict[str, Any]:
    """
    获取文本的嵌入向量

    Args:
        input: 要获取嵌入的文本列表
        model: 嵌入模型名称
        task: 嵌入任务类型
        dimensions: 嵌入维度
        embedding_type: 嵌入类型
        late_chunking: 是否启用延迟分块
        timeout_ms: 请求超时时间（毫秒）
        truncate: 是否截断
    Returns:
        包含嵌入向量和令牌使用情况的字典
    """
    if not JINA_API_KEY:
        print("JINA_API_KEY未设置")
        return {"embeddings": [], "tokens": 0}

    input = ["N/A" if not item.strip() else item for item in input]

    request = {
        "model": model,
        "task": task,
        "dimensions": dimensions,
        "embedding_type": embedding_type,
        "late_chunking": late_chunking,
        "input": input,
        "truncate": truncate
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {JINA_API_KEY}"
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

        if not data.get("data") or len(data["data"]) != len(input):
            print("来自Jina API的无效响应:", data)
            return {"embeddings": [], "tokens": 0}

        embeddings = sorted(data["data"], key=lambda x: x["index"])
        embeddings = [item["embedding"] for item in embeddings]

        return {
            "embeddings": embeddings,
            "tokens": data["usage"]["total_tokens"]
        }

    except requests.exceptions.Timeout:
        print(f"嵌入请求超时: {timeout_ms}ms后超时")
        return {"embeddings": [], "tokens": 0}
    except requests.exceptions.RequestException as error:
        print("获取嵌入出错:", error)
        if hasattr(error, "response") and error.response and error.response.status_code == 402:
            return {"embeddings": [], "tokens": 0}
        raise error
