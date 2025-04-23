#!/usr/bin/env python3
"""
DeepResearch Agent 运行脚本
用法: python run_agent.py "你的问题"
"""

import sys
import asyncio
from deepresearch.agent import get_response

async def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python run_agent.py \"你的问题\"")
        sys.exit(1)
    
    question = " ".join(sys.argv[1:])
    print(f"正在处理问题: {question}")
    
    try:
        result = await get_response(question)
        print("\n最终答案:", result["result"].answer)
        print("访问的URL数量:", len(result["visited_urls"]))
        result["context"].token_tracker.print_summary()
    except Exception as e:
        print(f"发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())