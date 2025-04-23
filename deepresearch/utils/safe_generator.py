"""
安全生成器 - 用于生成对象的安全包装
"""
import json
import traceback
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar, Union, Dict, Type, cast

import hjson
from json_repair import repair_json
from openai import OpenAI

from ..config import OPENAI_API_KEY, OPENAI_BASE_URL, get_model, get_tool_config
from .token_tracker import TokenTracker

T = TypeVar('T')

class GenerateObjectResult(Generic[T]):
    """生成对象的结果"""
    def __init__(self, object: T, usage: Dict[str, Any]):
        self.object = object
        self.usage = usage

class GenerateOptions(Generic[T]):
    """生成对象的选项"""
    def __init__(
        self,
        model: str,
        schema: Any,
        prompt: Optional[str] = None,
        system: Optional[str] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        num_retries: int = 0
    ):
        self.model = model
        self.schema = schema
        self.prompt = prompt
        self.system = system
        self.messages = messages
        self.num_retries = num_retries

class NoObjectGeneratedError(Exception):
    """未生成对象错误"""
    def __init__(self, text: str, usage: Dict[str, Any]):
        self.text = text
        self.usage = usage
        super().__init__(f"未能生成符合模式的对象: {text[:100]}...")
    
    @classmethod
    def is_instance(cls, error: Any) -> bool:
        """检查错误是否为NoObjectGeneratedError实例"""
        return isinstance(error, NoObjectGeneratedError)

class ObjectGeneratorSafe:
    """安全的对象生成器，可以处理错误并提供友好的接口"""
    
    def __init__(self, token_tracker: Optional[TokenTracker] = None):
        """
        初始化安全生成器
        
        Args:
            token_tracker: 令牌跟踪器，用于跟踪令牌使用情况
        """
        self.token_tracker = token_tracker or TokenTracker()
    
    def _create_distilled_schema(self, schema: Any) -> Any:
        """
        创建简化版模式，移除所有描述
        这使得模式更简单，适用于后备解析场景
        
        Args:
            schema: 原始模式
            
        Returns:
            简化后的模式
        """
        # 暂时不实现复杂的模式简化逻辑
        # 这里应该根据Python中使用的模式验证库来实现
        return schema
    
    def _strip_schema_descriptions(self, schema: Any) -> Any:
        """
        从AI SDK Schema对象中移除描述
        
        Args:
            schema: 原始模式
            
        Returns:
            移除描述后的模式
        """
        # 深度克隆模式以避免修改原始模式
        cloned_schema = json.loads(json.dumps(schema))
        
        # 递归移除描述属性
        def remove_descriptions(obj: Any) -> None:
            if not isinstance(obj, dict) or obj is None:
                return
            
            if 'properties' in obj:
                for key in obj['properties'].keys():
                    # 移除描述属性
                    if 'description' in obj['properties'][key]:
                        del obj['properties'][key]['description']
                    
                    # 递归处理嵌套属性
                    remove_descriptions(obj['properties'][key])
            
            # 处理数组
            if 'items' in obj:
                if 'description' in obj['items']:
                    del obj['items']['description']
                remove_descriptions(obj['items'])
            
            # 处理可能包含描述的其他嵌套对象
            if 'anyOf' in obj:
                for item in obj['anyOf']:
                    remove_descriptions(item)
            if 'allOf' in obj:
                for item in obj['allOf']:
                    remove_descriptions(item)
            if 'oneOf' in obj:
                for item in obj['oneOf']:
                    remove_descriptions(item)
        
        remove_descriptions(cloned_schema)
        return cloned_schema
    
    async def generate_object(self, options: Union[GenerateOptions[T], Dict[str, Any]]) -> GenerateObjectResult[T]:
        """
        生成对象
        
        Args:
            options: 生成选项，可以是 GenerateOptions 实例或字典
            
        Returns:
            生成的对象和使用情况
            
        Raises:
            Exception: 如果生成失败
        """
        # 如果 options 是字典，将其转换为 GenerateOptions 实例
        if isinstance(options, dict):
            options = GenerateOptions(
                model=options.get('model'),
                schema=options.get('schema'),
                prompt=options.get('prompt'),
                system=options.get('system'),
                messages=options.get('messages'),
                num_retries=options.get('num_retries', 0)
            )
        
        model = options.model
        schema = options.schema
        prompt = options.prompt
        system = options.system
        messages = options.messages
        num_retries = options.num_retries
        
        if not model or not schema:
            raise ValueError('模型和模式是必需的参数')
        
        try:
            # 主要尝试使用主模型
            client = OpenAI(base_url=OPENAI_BASE_URL, api_key=OPENAI_API_KEY)
            
            model_config = get_model(model)
            tool_config = get_tool_config(model)
            
            api_messages = []
            if system:
                api_messages.append({"role": "system", "content": system})
            if prompt:
                api_messages.append({"role": "user", "content": prompt})
            elif messages:
                api_messages.extend(messages)
            
            response = client.chat.completions.create(
                model=model_config["model"],
                messages=api_messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "generate_structured_output",
                        "schema": schema,
                        "strict": True
                    }
                }
            )

            content = response.choices[0].message.content
            result = repair_json(content, return_objects=True)
            
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            }
            
            self.token_tracker.track_usage(model, usage)
            return GenerateObjectResult(object=result, usage=usage)
            
        except Exception as error:
            # 第一个后备方案：尝试手动解析错误响应
            try:
                error_result = await self._handle_generate_object_error(error)
                self.token_tracker.track_usage(model, error_result.usage)
                return error_result
                
            except Exception as parse_error:
                if num_retries > 0:
                    print(f"{model} 对象生成失败 -> 手动解析失败 -> 剩余重试次数 {num_retries - 1}")
                    new_options = GenerateOptions(
                        model=model,
                        schema=schema,
                        prompt=prompt,
                        system=system,
                        messages=messages,
                        num_retries=num_retries - 1
                    )
                    return await self.generate_object(new_options)
                else:
                    # 第二个后备方案：尝试使用后备模型（如果提供了）
                    print(f"{model} 对象生成失败 -> 手动解析失败 -> 尝试使用简化模式的后备方案")
                    try:
                        failed_output = ''
                        
                        if NoObjectGeneratedError.is_instance(parse_error):
                            failed_output = parse_error.text
                            # 查找字符串中最后一个`"url":`出现的位置，这是问题的根源
                            url_index = failed_output.rfind('"url":')
                            if url_index > 0:
                                failed_output = failed_output[:min(url_index, 8000)]
                        
                        # 创建没有描述的简化模式版本
                        distilled_schema = self._create_distilled_schema(schema)
                        
                        client = OpenAI()
                        fallback_model = get_model('fallback')
                        fallback_config = get_tool_config('fallback')
                        
                        fallback_response = client.chat.completions.create(
                            model=fallback_model,
                            messages=[{
                                "role": "user", 
                                "content": f"按照给定的JSON模式，从以下内容中提取字段：\n\n {failed_output}"
                            }],
                            response_format={"type": "json_object"},
                            max_tokens=fallback_config.get('max_tokens'),
                            temperature=fallback_config.get('temperature'),
                            tools=[{
                                "type": "function",
                                "function": {
                                    "name": "extract_structured_output",
                                    "description": "从文本中提取符合指定JSON模式的结构化数据",
                                    "parameters": distilled_schema
                                }
                            }],
                            tool_choice={"type": "function", "function": {"name": "extract_structured_output"}}
                        )
                        
                        # 从工具响应中获取内容
                        if hasattr(fallback_response.choices[0].message, 'tool_calls') and fallback_response.choices[0].message.tool_calls:
                            tool_call = fallback_response.choices[0].message.tool_calls[0]
                            fallback_content = tool_call.function.arguments
                            fallback_result = json.loads(fallback_content)
                        else:
                            # 如果没有工具响应，回退到普通响应内容
                            fallback_content = fallback_response.choices[0].message.content
                            fallback_result = json.loads(fallback_content)
                        
                        fallback_usage = {
                            "prompt_tokens": fallback_response.usage.prompt_tokens,
                            "completion_tokens": fallback_response.usage.completion_tokens,
                            "total_tokens": fallback_response.usage.total_tokens
                        }
                        
                        self.token_tracker.track_usage('fallback', fallback_usage)  # 对后备模型进行跟踪
                        print('简化模式解析成功！')
                        return GenerateObjectResult(object=fallback_result, usage=fallback_usage)
                        
                    except Exception as fallback_error:
                        # 如果后备模型也失败，尝试解析其错误响应
                        try:
                            last_chance_result = await self._handle_generate_object_error(fallback_error)
                            self.token_tracker.track_usage('fallback', last_chance_result.usage)
                            return last_chance_result
                        except Exception as final_error:
                            print('所有恢复机制都失败了')
                            raise error  # 抛出原始错误以便更好地调试
    
    async def _handle_generate_object_error(self, error: Exception) -> GenerateObjectResult[T]:
        """
        处理生成对象时的错误
        
        Args:
            error: 错误
            
        Returns:
            处理后的结果
            
        Raises:
            Exception: 如果无法处理错误
        """
        if NoObjectGeneratedError.is_instance(error):
            print('对象未按模式生成，回退到手动解析')
            try:
                # 首先尝试标准JSON解析
                partial_response = json.loads(error.text)
                print('JSON解析成功！')
                return GenerateObjectResult(object=partial_response, usage=error.usage)
            except Exception as parse_error:
                # 使用hjson进行更宽松的解析
                try:
                    hjson_response = hjson.loads(error.text)
                    print('Hjson解析成功！')
                    return GenerateObjectResult(object=hjson_response, usage=error.usage)
                except Exception as hjson_error:
                    print('JSON和Hjson解析都失败了:', hjson_error)
                    raise error
        raise error 