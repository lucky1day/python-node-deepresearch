
from enum import Enum
from typing import List, Dict, Optional, Tuple, Union, TypedDict, Any, Literal
from pydantic import BaseModel, Field

# 添加 TokenTracker 和 ActionTracker 的导入
from .utils.token_tracker import TokenTracker
from .utils.action_tracker import ActionTracker


class BaseAction(BaseModel):
    """基础动作类型"""

    action: Literal["search", "answer", "reflect", "visit", "coding"]
    think: str


class SERPQuery(BaseModel):
    """搜索引擎查询参数"""

    q: str
    hl: Optional[str] = None
    gl: Optional[str] = None
    location: Optional[str] = None
    tbs: Optional[str] = None


class Reference(BaseModel):
    """引用信息"""

    exact_quote: str
    url: str
    title: Optional[str] = None  # CHECK
    date_time: Optional[str] = None


class SearchAction(BaseAction):
    """搜索动作"""

    action: Literal["search"] = "search"
    search_requests: List[str]


class AnswerAction(BaseAction):
    """回答动作"""

    action: Literal["answer"] = "answer"
    answer: str
    references: List[Reference]
    is_final: Optional[bool] = None
    md_answer: Optional[str] = None


class KnowledgeItem(BaseModel):
    """知识项目"""
    type: Literal["qa", "side-info", "chat-history", "url", "coding"]
    question: str
    answer: str
    references: Optional[List[Union[Reference, Any]]] = None
    updated: Optional[str] = None
    source_code: Optional[str] = None


class ReflectAction(BaseAction):
    """反思动作"""

    action: Literal["reflect"] = "reflect"
    questions_to_answer: List[str]


class VisitAction(BaseAction):
    """访问动作"""

    action: Literal["visit"] = "visit"
    url_targets: List[Union[int, str]]


class CodingAction(BaseAction):
    """编码动作"""

    action: Literal["coding"] = "coding"
    coding_issue: str


# 动作类型联合
StepAction = Union[SearchAction, AnswerAction, ReflectAction, VisitAction, CodingAction]


class EvaluationType(str, Enum):
    """评估类型"""

    DEFINITIVE = "definitive"  # 明确性评估 - 检查答案是否明确和准确
    FRESHNESS = "freshness"  # 时效性评估 - 检查信息是否足够新近
    PLURALITY = "plurality"  # 多样性评估 - 检查是否包含多个观点或来源
    ATTRIBUTION = "attribution"  # 归因评估 - 检查信息来源是否可靠且有适当引用
    COMPLETENESS = "completeness"  # 完整性评估 - 检查答案是否完整覆盖所有要点
    STRICT = "strict"  # 严格评估 - 进行更严格的标准检查


class RepeatEvaluationType(BaseModel):
    """重复评估类型"""

    type: EvaluationType
    num_evals_required: int


class TokenUsage(BaseModel):
    """令牌使用情况"""

    tool: str
    usage: Dict[str, int]


class SearchResult(BaseModel):
    """搜索结果项"""

    title: str
    description: str
    url: str
    content: str
    usage: Dict[str, int]


class SearchResponse(BaseModel):
    """搜索响应"""

    code: int
    status: int
    data: Optional[List[SearchResult]] = None
    name: Optional[str] = None
    message: Optional[str] = None
    readable_message: Optional[str] = None


class BraveSearchResult(BaseModel):
    """Brave搜索结果项"""

    title: str
    description: str
    url: str


class BraveSearchResponse(BaseModel):
    """Brave搜索响应"""

    web: Dict[str, List[BraveSearchResult]]


class SerperSearchResponse(BaseModel):
    """Serper搜索响应"""

    knowledge_graph: Optional[Dict[str, Any]] = None
    organic: List[Dict[str, Any]]
    top_stories: Optional[List[Dict[str, Any]]] = None
    related_searches: Optional[List[str]] = None
    credits: int


class ReadResponseData(BaseModel):
    """读取响应数据"""

    title: str
    description: str
    url: str
    content: str
    usage: Dict[str, int]
    links: List[Tuple[str, str]]

class ReadResponse(BaseModel):
    """读取响应"""

    code: int
    status: int
    data: Optional[ReadResponseData] = None
    name: Optional[str] = None
    message: Optional[str] = None
    readable_message: Optional[str] = None


class EvaluationResponse(BaseModel):
    """评估响应"""

    pass_eval: bool = Field(..., alias="pass")
    think: str
    type: Optional[EvaluationType] = None
    freshness_analysis: Optional[Dict[str, int]] = None
    plurality_analysis: Optional[Dict[str, int]] = None
    exact_quote: Optional[str] = None
    completeness_analysis: Optional[Dict[str, str]] = None
    improvement_plan: Optional[str] = None


class CodeGenResponse(BaseModel):
    """代码生成响应"""

    think: str
    code: str


class ErrorAnalysisResponse(BaseModel):
    """错误分析响应"""

    recap: str
    blame: str
    improvement: str


class UnNormalizedSearchSnippet(BaseModel):
    """未规范化的搜索片段"""

    title: str
    url: Optional[str] = None
    description: Optional[str] = None
    link: Optional[str] = None
    snippet: Optional[str] = None
    weight: Optional[float] = None
    date: Optional[str] = None


class SearchSnippet(UnNormalizedSearchSnippet):
    """搜索片段"""

    url: str
    description: str


class BoostedSearchSnippet(SearchSnippet):
    """增强的搜索片段"""

    freq_boost: float
    hostname_boost: float
    path_boost: float
    jina_rerank_boost: float
    final_score: float
    score: float
    merged: str


class Model(BaseModel):
    """模型信息"""

    id: str
    object: str = "model"
    created: int
    owned_by: str


class PromptPair(BaseModel):
    """提示对"""

    system: str
    user: str


class ResponseFormat(BaseModel):
    """响应格式"""

    type: Literal["json_schema", "json_object"]
    json_schema: Optional[Dict[str, Any]] = None


class ChatCompletionRequest(BaseModel):
    """聊天完成请求"""

    model: str
    messages: List[Dict[str, str]]
    stream: Optional[bool] = None
    reasoning_effort: Optional[Literal["low", "medium", "high"]] = None
    max_completion_tokens: Optional[int] = None
    budget_tokens: Optional[int] = None
    max_attempts: Optional[int] = None
    response_format: Optional[ResponseFormat] = None
    no_direct_answer: Optional[bool] = None
    max_returned_urls: Optional[int] = None
    boost_hostnames: Optional[List[str]] = None
    bad_hostnames: Optional[List[str]] = None
    only_hostnames: Optional[List[str]] = None


class URLAnnotation(BaseModel):
    """URL注释"""

    type: Literal["url_citation"]
    url_citation: Reference


class ChatCompletionChoice(BaseModel):
    """聊天完成选择"""

    index: int
    message: Dict[str, Any]
    logprobs: None = None
    finish_reason: Literal["stop", "error"]


class ChatCompletionResponse(BaseModel):
    """聊天完成响应"""

    id: str
    object: Literal["chat.completion"]
    created: int
    model: str
    system_fingerprint: str
    choices: List[ChatCompletionChoice]
    usage: Dict[str, int]
    visited_urls: Optional[List[str]] = None
    read_urls: Optional[List[str]] = None
    num_urls: Optional[int] = None


class ChatCompletionChoiceDelta(BaseModel):
    """聊天完成选择的增量部分"""

    role: Optional[str] = None
    content: Optional[str] = None
    type: Optional[Literal["text", "think", "json", "error"]] = None
    url: Optional[str] = None
    annotations: Optional[List[URLAnnotation]] = None


class ChatCompletionChunkChoice(BaseModel):
    """聊天完成分块的选择项"""

    index: int
    delta: ChatCompletionChoiceDelta
    logprobs: None = None
    finish_reason: Optional[Literal["stop", "thinking_end", "error"]] = None


class ChatCompletionChunk(BaseModel):
    """聊天完成分块"""

    id: str
    object: Literal["chat.completion.chunk"]
    created: int
    model: str
    system_fingerprint: str
    choices: List[ChatCompletionChunkChoice]
    usage: Optional[Dict[str, Any]] = None
    visited_urls: Optional[List[str]] = None
    read_urls: Optional[List[str]] = None
    num_urls: Optional[int] = None


class TrackerContext(BaseModel):
    """跟踪上下文"""

    token_tracker: TokenTracker
    action_tracker: ActionTracker

    model_config = {"arbitrary_types_allowed": True}


class PDFReadResponse(BaseModel):
    """PDF阅读响应"""

    success: bool = False
    error: str = ""
    title: str = ""
    pages: int = 0
    content: str = ""
    summary: str = ""
