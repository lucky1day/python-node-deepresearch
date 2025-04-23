"""
代码沙箱工具 - 安全执行代码并返回结果
"""
import asyncio
import os
import re
import subprocess
import tempfile
from typing import Dict, Any, List, Optional, Tuple
import uuid
import json

from ..model_types import CodeGenResponse
from ..config import OPENAI_API_KEY, OPENAI_API_MODEL, ALLOWED_CODING_LANGUAGES, DEBUG


class CodeSandbox:
    """
    代码沙箱 - 用于安全执行代码
    """
    
    def __init__(self):
        # 支持的语言和对应的执行命令
        self.language_configs = {
            "python": {
                "file_ext": ".py",
                "run_cmd": ["python", "{file}"]
            },
            "javascript": {
                "file_ext": ".js",
                "run_cmd": ["node", "{file}"]
            },
            "typescript": {
                "file_ext": ".ts",
                "run_cmd": ["npx", "ts-node", "{file}"]
            },
            "bash": {
                "file_ext": ".sh",
                "run_cmd": ["bash", "{file}"]
            },
            "go": {
                "file_ext": ".go",
                "run_cmd": ["go", "run", "{file}"]
            },
            "ruby": {
                "file_ext": ".rb",
                "run_cmd": ["ruby", "{file}"]
            },
            "php": {
                "file_ext": ".php",
                "run_cmd": ["php", "{file}"]
            }
        }
    
    async def generate_code(self, problem_description: str, language: str = "python") -> CodeGenResponse:
        """
        使用AI生成代码
        
        Args:
            problem_description: 问题描述
            language: 编程语言
            
        Returns:
            生成的代码响应
        """
        if language not in ALLOWED_CODING_LANGUAGES:
            return CodeGenResponse(
                think=f"不支持的编程语言: {language}。请使用以下语言之一: {', '.join(ALLOWED_CODING_LANGUAGES)}",
                code=""
            )
            
        if not OPENAI_API_KEY:
            return CodeGenResponse(
                think="OPENAI_API_KEY未设置，无法生成代码",
                code=""
            )
            
        try:
            from openai import OpenAI
            
            client = OpenAI(api_key=OPENAI_API_KEY)
            
            # 构建系统提示
            system_prompt = f"""你是一位专业的{language}编程专家。你需要为用户生成解决特定问题的代码。

生成代码要求:
1. 使用{language}编程语言编写简洁、高效的代码
2. 代码必须针对问题进行优化，避免不必要的复杂性
3. 确保代码具有良好的错误处理和边界条件检查
4. 添加必要的注释，解释关键步骤和复杂逻辑
5. 确保代码风格一致，遵循{language}的最佳实践

提供思路解释和完整的代码实现。"""

            # 构建用户提示
            user_prompt = f"请为以下问题生成{language}代码:\n\n{problem_description}"
            
            # 调用API
            response = client.chat.completions.create(
                model=OPENAI_API_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            
            content = response.choices[0].message.content
            
            # 尝试从内容中提取代码块
            code_blocks = re.findall(r'```(?:\w*\n)?([\s\S]*?)```', content)
            
            if code_blocks:
                # 提取第一个代码块作为实现
                code = code_blocks[0].strip()
            else:
                # 如果没有代码块标记，尝试提取整个内容
                code = content.strip()
                
            return CodeGenResponse(
                think=f"已生成{language}代码解决方案",
                code=code
            )
                
        except Exception as e:
            if DEBUG:
                print(f"代码生成失败: {str(e)}")
            return CodeGenResponse(
                think=f"代码生成失败: {str(e)}",
                code=""
            )
    
    async def execute_code(self, code: str, language: str = "python", timeout: int = 30) -> Dict[str, Any]:
        """
        执行代码
        
        Args:
            code: 要执行的代码
            language: 编程语言
            timeout: 执行超时时间（秒）
            
        Returns:
            执行结果字典
        """
        if language not in self.language_configs:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"不支持的编程语言: {language}",
                "error": f"不支持的编程语言: {language}"
            }
            
        # 创建临时文件
        try:
            config = self.language_configs[language]
            file_ext = config["file_ext"]
            run_cmd = config["run_cmd"]
            
            # 创建唯一的临时文件
            unique_id = str(uuid.uuid4())
            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, f"sandbox_{unique_id}{file_ext}")
            
            # 写入代码到临时文件
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(code)
                
            # 准备执行命令
            cmd = [cmd_part.format(file=file_path) for cmd_part in run_cmd]
            
            # 设置超时
            try:
                # 执行代码
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    limit=1024 * 1024  # 1MB限制
                )
                
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
                    stdout_str = stdout.decode('utf-8', errors='replace')
                    stderr_str = stderr.decode('utf-8', errors='replace')
                    
                    return {
                        "success": process.returncode == 0,
                        "stdout": stdout_str,
                        "stderr": stderr_str,
                        "exit_code": process.returncode
                    }
                    
                except asyncio.TimeoutError:
                    # 超时，终止进程
                    try:
                        process.kill()
                    except:
                        pass
                        
                    return {
                        "success": False,
                        "stdout": "",
                        "stderr": f"执行超时（{timeout}秒）",
                        "error": "执行超时"
                    }
                    
            except Exception as e:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": str(e),
                    "error": f"执行错误: {str(e)}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "error": f"设置错误: {str(e)}"
            }
            
        finally:
            # 清理临时文件
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except:
                pass
                

if __name__ == "__main__":
    # 测试代码
    import asyncio
    
    async def test():
        sandbox = CodeSandbox()
        
        # 测试生成代码
        problem = "编写一个函数，计算斐波那契数列的第n个数"
        print(f"问题: {problem}")
        
        code_response = await sandbox.generate_code(problem, "python")
        print("\n生成的代码:")
        print(code_response.code)
        
        # 测试执行代码
        test_code = """
def fibonacci(n):
    if n <= 0:
        return 0
    elif n == 1:
        return 1
    else:
        return fibonacci(n-1) + fibonacci(n-2)

# 测试
for i in range(10):
    print(f"fibonacci({i}) = {fibonacci(i)}")
"""
        
        print("\n执行代码:")
        result = await sandbox.execute_code(test_code, "python")
        
        if result["success"]:
            print("执行成功!")
            print("输出:")
            print(result["stdout"])
        else:
            print("执行失败!")
            print("错误:")
            print(result["stderr"])
            
    asyncio.run(test()) 