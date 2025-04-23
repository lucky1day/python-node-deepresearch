"""
答案评估工具 - 评估搜索结果和最终答案的质量
"""
import json
import re
import datetime
import sys
from pathlib import Path
from json_repair import repair_json
from typing import Dict, List, Any, Optional, Union, Tuple

# 确保项目根目录在Python路径中
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from ..model_types import (
        EvaluationResponse, EvaluationType, KnowledgeItem,
        Reference, AnswerAction, PromptPair, TrackerContext,
        TokenTracker, ActionTracker
    )
    from ..utils.text_tools import get_knowledge_str
    from ..utils.safe_generator import ObjectGeneratorSafe
    from ..utils.schemas import JsonSchemaGen
    from ..prompt_template import REJECT_ALL_ANSWERS_SYSTEM_PROMPT, REJECT_ALL_ANSWERS_USER_PROMPT, DEFINITIVE_SYSTEM_PROMPT, DEFINITIVE_USER_PROMPT, FRESHNESS_SYSTEM_PROMPT, FRESHNESS_USER_PROMPT, COMPLETENESS_SYSTEM_PROMPT, COMPLETENESS_USER_PROMPT, PLURALITY_SYSTEM_PROMPT, PLURALITY_USER_PROMPT, QUESTION_EVALUATION_SYSTEM_PROMPT, QUESTION_EVALUATION_USER_PROMPT
except ImportError:
    from deepresearch.model_types import (
        EvaluationResponse, EvaluationType, KnowledgeItem,
        Reference, AnswerAction, PromptPair, TrackerContext,
        TokenTracker, ActionTracker
    )
    from deepresearch.utils.text_tools import get_knowledge_str
    from deepresearch.utils.safe_generator import ObjectGeneratorSafe
    from deepresearch.utils.schemas import JsonSchemaGen
    from deepresearch.prompt_template import REJECT_ALL_ANSWERS_SYSTEM_PROMPT, REJECT_ALL_ANSWERS_USER_PROMPT, DEFINITIVE_SYSTEM_PROMPT, DEFINITIVE_USER_PROMPT, FRESHNESS_SYSTEM_PROMPT, FRESHNESS_USER_PROMPT, COMPLETENESS_SYSTEM_PROMPT, COMPLETENESS_USER_PROMPT, PLURALITY_SYSTEM_PROMPT, PLURALITY_USER_PROMPT, QUESTION_EVALUATION_SYSTEM_PROMPT, QUESTION_EVALUATION_USER_PROMPT
TOOL_NAME = 'evaluator'


def get_reject_all_answers_prompt(question: str, answer: AnswerAction, all_knowledge: List[KnowledgeItem]) -> PromptPair:
    """生成拒绝所有答案的提示"""
    knowledge_str = get_knowledge_str(all_knowledge)
    answer_text = answer.answer if isinstance(answer, AnswerAction) else answer
    
    # 获取知识字符串列表，然后用换行符连接，与TypeScript版本保持一致
    knowledge_str_list = knowledge_str
    knowledge_str_joined = '\n\n'.join(knowledge_str_list)
    
    return PromptPair(
        system=REJECT_ALL_ANSWERS_SYSTEM_PROMPT.format(knowledge_str=knowledge_str_joined),
        user=REJECT_ALL_ANSWERS_USER_PROMPT.format(question=question, answer_text=answer_text)
    )

def get_definitive_prompt(question: str, answer: str) -> PromptPair:
    """生成确定性评估提示"""
    return PromptPair(
        system=DEFINITIVE_SYSTEM_PROMPT,
        user=DEFINITIVE_USER_PROMPT.format(question=question, answer=answer)
    )

def get_freshness_prompt(question: str, answer: AnswerAction, current_time: str) -> PromptPair:
    """生成时效性评估提示"""
    def custom_json_serializer(obj):
        if isinstance(obj, AnswerAction):
            return obj.__dict__  # 返回类的 __dict__ 属性
        if isinstance(obj, Reference):
            return obj.__dict__  # 如果是 Reference 类型，也返回其 __dict__
        raise TypeError(f"Type {type(obj)} not serializable")
        
    
    return PromptPair(
        system=FRESHNESS_SYSTEM_PROMPT.format(current_time=current_time),
        user= FRESHNESS_USER_PROMPT.format(question=question, answer_json=json.dumps(answer.__dict__ if isinstance(answer, AnswerAction) else answer, default=custom_json_serializer, ensure_ascii=False))
    )

def get_completeness_prompt(question: str, answer: str) -> PromptPair:
    """生成完整性评估提示"""
    return PromptPair(
        system=COMPLETENESS_SYSTEM_PROMPT,
        user=COMPLETENESS_USER_PROMPT.format(question=question, answer=answer)
    )

def get_plurality_prompt(question: str, answer: str) -> PromptPair:
    """生成多样性评估提示"""
    return PromptPair(
        system=PLURALITY_SYSTEM_PROMPT,
        user=PLURALITY_USER_PROMPT.format(question=question, answer=answer)
    )

def get_question_evaluation_prompt(question: str) -> PromptPair:
    """生成问题评估提示"""
    return PromptPair(
        system=QUESTION_EVALUATION_SYSTEM_PROMPT,
        user=QUESTION_EVALUATION_USER_PROMPT.format(question=question)
    )

async def evaluate_question(
    question: str,
    trackers: TrackerContext,
    schema_gen: Any
) -> List[EvaluationType]:
    """
    分析问题并确定需要哪些评估类型:
    
    1. DEFINITIVE(明确性): 答案是否准确明确，没有模棱两可的表述
       例如"谁是20年NBA总冠军"需要一个确定的答案
       
    2. FRESHNESS(新鲜度): 答案是否包含最新信息
       例如"现在的比特币价格是多少"需要最新数据
       
    3. PLURALITY(多元性): 答案是否提供多角度或多种解决方案
       例如"如何减肥"需要提供多种减肥方法
       
    4. COMPLETENESS(完整性): 答案是否全面详尽，涵盖问题各方面
       例如"Python异常处理"需要包含try-except,finally等全部内容
    """
    try:
        prompt = get_question_evaluation_prompt(question)
        
        generator = ObjectGeneratorSafe(trackers.token_tracker)

        result = await generator.generate_object({
            "model": TOOL_NAME,
            "schema": schema_gen.get_question_evaluate_schema(),
            "system": prompt.system,
            "prompt": prompt.user
        })


        # 始终包含definitive在类型中
        types = []
        if result.object.get("needs_definitive"):
            types.append(EvaluationType.DEFINITIVE)
        if result.object.get("needs_freshness"):
            types.append(EvaluationType.FRESHNESS) 
        if result.object.get("needs_plurality"):
            types.append(EvaluationType.PLURALITY)
        if result.object.get("needs_completeness"):
            types.append(EvaluationType.COMPLETENESS)

        print(f"\n\n【evaluate_question】\n问题: '{question}'\n评估类型: {types}\n详细评估: {result.object}\n")
        trackers.action_tracker.track_think(result.object.get("think"))
        
        return types
        
    except Exception as e:
        print('Error in question evaluation:', e)
        return []

async def perform_evaluation(
    evaluation_type: EvaluationType,
    prompt: PromptPair,
    trackers: TrackerContext,
    schema_gen: Any
) -> Dict[str, Any]:
    """执行特定类型的评估"""
    generator = ObjectGeneratorSafe(trackers.token_tracker)
    result = await generator.generate_object({
        "model": TOOL_NAME,
        "schema": schema_gen.get_evaluator_schema(evaluation_type),
        "system": prompt.system,
        "prompt": prompt.user
    })

    # Track the thought process
    trackers.action_tracker.track_think(result.object.get("think", ""))

    print(f"{evaluation_type} {TOOL_NAME}", result.object)

    return result

async def evaluate_answer(
    question: str,
    action: AnswerAction,
    evaluation_types: List[EvaluationType],
    trackers: TrackerContext,
    all_knowledge: List[KnowledgeItem],
    schema_gen: Any
) -> EvaluationResponse:
    """评估答案"""
    result = None
    
    for evaluation_type in evaluation_types:
        
        if evaluation_type == EvaluationType.DEFINITIVE:
            prompt = get_definitive_prompt(question, action.answer)
        elif evaluation_type == EvaluationType.FRESHNESS:
            prompt = get_freshness_prompt(question, action, datetime.datetime.now().isoformat())
        elif evaluation_type == EvaluationType.PLURALITY:
            prompt = get_plurality_prompt(question, action.answer)
        elif evaluation_type == EvaluationType.COMPLETENESS:
            prompt = get_completeness_prompt(question, action.answer)
        elif evaluation_type == EvaluationType.STRICT:
            prompt = get_reject_all_answers_prompt(question, action, all_knowledge)
        else:
            print(f"Unknown evaluation type: {evaluation_type}")
            continue
            
        if prompt:
            result = await perform_evaluation(
                evaluation_type,
                prompt,
                trackers,
                schema_gen
            )
            
            # 如果一个评估失败，立即返回
            result = result.object
            if not result.get("pass_eval", False):
                result["type"] = evaluation_type
                return EvaluationResponse.model_construct(**result)
                
    return EvaluationResponse.model_construct(**result.object)

if __name__ == "__main__":
    import asyncio

    # async def test_evaluate_question():
    #     # 创建必要的上下文对象
    #     token_tracker = TokenTracker()
    #     action_tracker = ActionTracker()
    #     trackers = TrackerContext(
    #         token_tracker=token_tracker,
    #         action_tracker=action_tracker
    #     )
    #     schemas = Schemas()
        
    #     # 测试不同类型的问题
    #     test_questions = [
    #         "谁发明了微积分？牛顿和莱布尼兹各自的贡献是什么？",
    #         "2025年最值得关注的5个人工智能趋势是什么？",
    #         "目前苹果、微软和谷歌的市值是多少？",
    #         "学习一门新语言的最佳方法有哪些？",
    #         "如果一棵树在没有任何观察者的森林中倒下，它会发出声音吗？"
    #     ]
        
    #     for question in test_questions:
    #         print(f"\n测试问题: {question}")
    #         evaluation_types = await evaluate_question(question, trackers, schemas)
    #         print(f"评估类型: {evaluation_types}")
    
    async def test_evaluate_answer():
        trackers = TrackerContext(
            token_tracker=TokenTracker(),
            action_tracker=ActionTracker()
        )
        schemas = JsonSchemaGen()
        
        # 创建测试知识库
        test_knowledge = [
            KnowledgeItem(
                question="谁发明了微积分？",
                answer="微积分是由牛顿和莱布尼兹独立发明的。牛顿开发了流数和导数的概念，创立了微积分的基础。莱布尼兹则发明了现代微积分符号，建立了更系统的数学理论框架。",
                type="side-info",
                references=[Reference(
                    exact_quote="微积分是由牛顿和莱布尼兹独立发明的",
                    url="https://example.com/calculus-history",
                    date_time="2023-01-01"
                )],
                source="《微积分历史》第三章"
            ),
            KnowledgeItem(
                question="目前主要科技公司的市值是多少？",
                answer="2023年，苹果公司市值约为3万亿美元，微软为2.8万亿美元，谷歌母公司Alphabet为1.8万亿美元。",
                type="side-info",
                references=[Reference(
                    exact_quote="2023年，苹果公司市值约为3万亿美元",
                    url="https://example.com/tech-market-cap",
                    date_time="2023-12-01"
                )],
                source="财经网，2023年12月报道"
            ),
            KnowledgeItem(
                question="学习新语言的最佳方法有哪些？",
                answer="学习新语言的有效方法包括：日常实践、沉浸式学习、使用间隔重复软件、找语言交换伙伴、听原声媒体、参加语言课程等。",
                type="side-info", 
                references=[Reference(
                    exact_quote="学习新语言的有效方法包括：日常实践、沉浸式学习",
                    url="https://example.com/language-learning",
                    date_time="2022-06-15"
                )],
                source="《语言学习研究》2022年"
            )
        ]
        
        # 测试不同的问题和答案组合
        test_cases = [
            {
                "question": "谁发明了微积分？牛顿和莱布尼兹各自的贡献是什么？",
                "answer": AnswerAction(
                    action="answer",
                    think="微积分是由牛顿和莱布尼兹独立发明的。牛顿开发了流数和导数的概念，而莱布尼兹发明了现代微积分符号和更系统的理论框架。",
                    answer="微积分是由牛顿和莱布尼兹独立发明的。牛顿开发了流数和导数的概念，而莱布尼兹发明了现代微积分符号和更系统的理论框架。",
                    references=[Reference(
                        exact_quote="微积分是由牛顿和莱布尼兹独立发明的",
                        url="https://example.com/calculus-history",
                        date_time="2023-01-01"
                    )]
                )
            },
            {
                "question": "目前苹果、微软和谷歌的市值是多少？",
                "answer": AnswerAction(
                    action="answer",
                    think="我不确定目前的精确市值，但根据可用信息，可能在变动。",
                    answer="我不确定目前的精确市值，但根据可用信息，可能在变动。",
                    references=[Reference(
                        exact_quote="2023年，苹果公司市值约为3万亿美元",
                        url="https://example.com/tech-market-cap",
                        date_time="2023-12-01"
                    )]
                )
            }
        ]
        
        for i, test_case in enumerate(test_cases):
            print(f"\n\n测试用例 {i+1}:")
            print(f"问题: {test_case['question']}")
            print(f"回答: {test_case['answer'].answer}")
            
            result = await evaluate_answer(
                test_case['question'],
                test_case['answer'],
                [EvaluationType.DEFINITIVE, EvaluationType.FRESHNESS, EvaluationType.PLURALITY, EvaluationType.COMPLETENESS, EvaluationType.STRICT],
                trackers,
                test_knowledge,
                schemas
            )
            
            print("评估结果:")
            print(f"通过: {result.pass_eval}")
            print(f"类型: {result.type if hasattr(result, 'type') else '无'}")
            print(f"思考过程: {result.think}")
    
    # 运行测试
    # asyncio.run(test_evaluate_question())
    print("\n" + "="*50 + "\n")
    asyncio.run(test_evaluate_answer())