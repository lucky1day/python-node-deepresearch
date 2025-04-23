import json
import re
from typing import List, Dict, Optional, Any, Tuple
import asyncio
from datetime import datetime


from .model_types import (
    RepeatEvaluationType,
    StepAction,
    SearchAction,
    AnswerAction,
    ReflectAction,
    VisitAction,
    CodingAction,
    KnowledgeItem,
    Reference,
    BoostedSearchSnippet,
    SearchSnippet,
    EvaluationType,
    EvaluationResponse,
    UnNormalizedSearchSnippet,
    TrackerContext,
)
from .config import SEARCH_PROVIDER, STEP_SLEEP
from .tools.query_rewriter import rewrite_query
from .tools.jina_dedup import dedup_queries
from .tools.evaluator import evaluate_answer, evaluate_question
from .tools.error_analyzer import analyze_steps
from .utils.token_tracker import TokenTracker
from .utils.schemas import JsonSchemaGen
from .utils.action_tracker import ActionTracker
from .tools.jina_search import search
from .tools.code_sandbox import CodeSandbox
from .utils.safe_generator import ObjectGeneratorSafe
from .utils.url_tools import (
    add_to_all_urls,
    rank_urls,
    filter_urls,
    normalize_url,
    sort_select_urls,
    get_last_modified,
    keep_k_per_hostname,
    process_urls,
    fix_bad_url_md_links,
    extract_urls_with_description,
)
from .utils.text_tools import (
    build_md_from_answer,
    choose_k,
    convert_html_tables_to_md,
    fix_code_block_indentation,
    remove_extra_line_breaks,
    remove_html_tags,
    repair_markdown_final,
    repair_markdown_footnotes_outer,
)
from .config import (
    MAX_QUERIES_PER_STEP,
    MAX_REFLECT_PER_STEP,
    MAX_URLS_PER_STEP,
    MAX_URLS_READ_PER_STEP,
)
from .utils.date_tools import format_date_based_on_type, format_date_range
from .tools.broken_ch_fixer import repair_unknown_chars
from .tools.md_fixer import fix_markdown
from .prompt_template import (
    REVIEWER_TEMPLATE,
    ANSWER_REQUIREMENTS_TEMPLATE,
    HEADER_TEMPLATE,
    CONTEXT_TEMPLATE,
    VISIT_ACTION_TEMPLATE,
    SEARCH_ACTION_TEMPLATE,
    ANSWER_ACTION_TEMPLATE,
    BEAST_MODE_TEMPLATE,
    REFLECT_ACTION_TEMPLATE,
    CODING_ACTION_TEMPLATE,
    ACTIONS_WRAPPER_TEMPLATE,
    FOOTER_TEMPLATE,
    BAD_REQUESTS_TEMPLATE,
    DIARY_FINAL_ANSWER_TEMPLATE,
    DIARY_BAD_ANSWER_TEMPLATE,
    DIARY_SUBQUESTION_ANSWER_TEMPLATE,
    DIARY_REFLECT_NEW_QUESTIONS_TEMPLATE,
    DIARY_REFLECT_NO_NEW_QUESTIONS_TEMPLATE,
    DIARY_SEARCH_SUCCESS_TEMPLATE,
    DIARY_SEARCH_FAIL_TEMPLATE,
    DIARY_VISIT_SUCCESS_TEMPLATE,
    DIARY_VISIT_FAIL_TEMPLATE,
    DIARY_VISIT_NO_NEW_URLS_TEMPLATE,
    DIARY_CODING_SUCCESS_TEMPLATE,
    DIARY_CODING_FAIL_TEMPLATE,
)

# 类型别名
Message = Dict[str, str]
CoreMessage = Dict[str, str]
all_context: List[Dict[str, Any]] = []  # 当前会话中的所有步骤，包括导致错误结果的步骤


async def sleep(ms: int) -> None:
    """等待指定的毫秒数"""
    seconds = ms / 1000
    print(f"等待 {seconds}s...")
    await asyncio.sleep(seconds)


def build_msgs_from_knowledge(knowledge: List[KnowledgeItem]) -> List[CoreMessage]:
    """从知识构建用户-助手对话消息

    工作流程:
    1. 初始化空消息列表
    2. 遍历知识项
       a. 添加用户消息(问题)
       b. 构建助手回复，包括:
          - 日期时间信息(如果可用)
          - URL信息(如果可用)
          - 答案内容
       c. 添加助手消息(回答)
    3. 返回构建的消息列表

    Args:
        knowledge: 知识项列表

    Returns:
        构建的消息列表，格式为[用户消息, 助手消息, ...]
    """
    messages: List[CoreMessage] = []
    for k in knowledge:
        messages.append({"role": "user", "content": k.question.strip()})

        answer_msg = ""
        if k.updated and (k.type == "url" or k.type == "side-info"):
            answer_msg += f"\n<answer-datetime>\n{k.updated}\n</answer-datetime>\n"

        if k.references and k.type == "url":
            answer_msg += f"\n<url>\n{k.references[0]}\n</url>\n"

        answer_msg += f"\n{k.answer}"
        messages.append(
            {
                "role": "assistant",
                "content": remove_extra_line_breaks(answer_msg.strip()),
            }
        )

    return messages


def compose_msgs(
    messages: List[CoreMessage],
    knowledge: List[KnowledgeItem],
    question: str,
    final_answer_pip: Optional[List[str]] = None,
) -> List[CoreMessage]:

    msgs = build_msgs_from_knowledge(knowledge) + messages

    user_content = question
    if final_answer_pip:
        reviewers_content = ""
        for idx, pip in enumerate(final_answer_pip, 1):
            reviewers_content += REVIEWER_TEMPLATE.format(idx=idx, pip=pip)

        user_content += ANSWER_REQUIREMENTS_TEMPLATE.format(reviewers=reviewers_content)

    msgs.append({"role": "user", "content": remove_extra_line_breaks(user_content)})

    if len(msgs) > 1 and msgs[-2] == msgs[-1]:
        return msgs[:-1]

    return msgs


def get_prompt(
    context: Optional[List[str]] = None,
    all_keywords: Optional[List[str]] = None,
    allow_reflect: bool = True,
    allow_answer: bool = True,
    allow_read: bool = True,
    allow_search: bool = True,
    allow_coding: bool = True,
    all_urls: Optional[List[BoostedSearchSnippet]] = None,
    beast_mode: bool = False,
) -> Tuple[str, Optional[List[str]]]:

    sections: List[str] = []
    action_sections: List[str] = []

    # 添加头部
    sections.append(
        HEADER_TEMPLATE.format(
            date=datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
        )
    )

    # 添加上下文
    if context:
        sections.append(CONTEXT_TEMPLATE.format(context="\n".join(context)))

    # 构建动作部分
    url_list = sort_select_urls(all_urls or [], MAX_URLS_READ_PER_STEP)
    if allow_read and url_list:
        url_list_str = "\n".join(
            f"  - [idx={idx+1}] [weight={item['score']:.2f}] \"{item['url']}\": \"{item['merged'][:50]}\""
            for idx, item in enumerate(url_list)
        )

        action_sections.append(VISIT_ACTION_TEMPLATE.format(url_list_str=url_list_str))

    if allow_search:
        bad_requests = ""
        if all_keywords:  # 搜过的就不用再搜了
            bad_requests = BAD_REQUESTS_TEMPLATE.format(
                keywords="\n".join(all_keywords)
            )

        action_sections.append(SEARCH_ACTION_TEMPLATE.format(bad_requests=bad_requests))

    if allow_answer:
        action_sections.append(ANSWER_ACTION_TEMPLATE)

    if beast_mode:
        action_sections.append(BEAST_MODE_TEMPLATE)

    if allow_reflect:
        action_sections.append(REFLECT_ACTION_TEMPLATE)

    if allow_coding:
        action_sections.append(CODING_ACTION_TEMPLATE)

    sections.append(ACTIONS_WRAPPER_TEMPLATE.format(actions="\n".join(action_sections)))

    # 添加页脚
    sections.append(FOOTER_TEMPLATE)

    return remove_extra_line_breaks("\n\n".join(sections)), (
        [u["url"] for u in url_list] if url_list else None
    )


def update_context(step: any):
    all_context.append(step)


async def update_references(
    this_step: AnswerAction, all_urls: Dict[str, SearchSnippet]
) -> None:

    if not this_step.references:
        return

    new_refs: List[Reference] = []
    for ref in this_step.references:
        if not ref or not ref.url:
            continue

        normalized_url = normalize_url(ref.url)
        if not normalized_url:
            continue

        exact_quote = (
            ref.exact_quote
            or all_urls[normalized_url].description
            or all_urls[normalized_url].title
            or ""
        )

        # Clean up the text by replacing non-alphanumeric characters with spaces
        exact_quote = re.sub(r"[^\w\s]", " ", exact_quote)

        # Replace multiple spaces with a single space
        exact_quote = re.sub(r"\s+", " ", exact_quote)

        new_ref = Reference(
            exact_quote=exact_quote,
            title=all_urls[normalized_url].title if normalized_url in all_urls else "",
            url=normalized_url,
            date_time=ref.date_time or all_urls[normalized_url].date or "",
        )
        new_refs.append(new_ref)

    this_step.references = new_refs

    # 并行处理猜测所有url日期时间
    async def update_datetime(ref: Reference):
        if not ref.date_time:
            ref.date_time = await get_last_modified(ref.url) or ""

    await asyncio.gather(*[update_datetime(ref) for ref in this_step.references])

    print("【Updated references】:", this_step.references)


async def execute_search_queries(
    keywords_queries: List[Dict[str, Any]],
    tracker_context: TrackerContext,
    all_urls: Dict[str, SearchSnippet],
    json_schema_gen: JsonSchemaGen,
    only_hostnames: Optional[List[str]] = None,
) -> Tuple[List[KnowledgeItem], List[str]]:
    """执行搜索查询，获取搜索结果并转换为知识项

    Args:
        keywords_queries: 关键词查询列表，每项包含查询文本
        tracker_context: 跟踪器上下文，用于记录令牌使用和操作历史
        all_urls: 所有已收集的URL信息字典
        json_schema_gen: JSON模式生成器，包含语言设置
        only_hostnames: 可选，限制搜索的主机名列表

    Returns:
        包含两个元素的元组: (新知识列表, 已搜索查询列表)
    """
    # ---------- 1. 初始化变量 ----------
    # 提取所有查询文本
    uniq_q_only = [q["q"] for q in keywords_queries]

    # 初始化结果容器
    new_knowledge: List[KnowledgeItem] = []  # 搜索生成的新知识
    searched_queries: List[str] = []  # 实际执行的查询
    utility_score = 0  # 搜索结果有用性评分

    # 记录搜索动作
    tracker_context.action_tracker.track_think(
        "search_for",
        json_schema_gen.language_code,
        {"keywords": ", ".join(uniq_q_only)},
    )

    # ---------- 2. 执行每个查询 ----------
    for query in keywords_queries:
        # 保存原始查询文本
        old_query = query["q"]

        # 如果指定了主机名限制，修改查询文本添加site:语法
        if only_hostnames:
            query["q"] = f"{query['q']} site:{' OR site:'.join(only_hostnames)}"

        # 用于存储搜索结果
        results: List[UnNormalizedSearchSnippet] = []

        # ---------- 2.1 执行搜索请求 ----------
        try:
            print("【execute_search_queries】:", query)

            # 根据配置的搜索提供商执行搜索
            if SEARCH_PROVIDER == "jina":
                search_result = await search(query["q"], tracker_context)
                results = search_result.data if search_result.data else []
            else:
                results = []

            # 如果没有结果，抛出异常
            if not results:
                raise ValueError("No results found")

        except Exception as error:
            print(f"{SEARCH_PROVIDER} search failed for query:", query, error)
            continue  # 跳过当前查询，继续下一个

        finally:
            # 无论搜索成功与否，都等待一段时间避免请求过于频繁
            await sleep(STEP_SLEEP)

        # ---------- 2.2 处理搜索结果 ----------
        # 将搜索结果标准化为SearchSnippet格式
        min_results: List[SearchSnippet] = []
        for r in results:
            # 规范化URL
            url = normalize_url(r.url if hasattr(r, "url") else r.link)
            if not url:
                continue  # 跳过无效URL

            # 创建标准化的搜索结果片段
            min_results.append(
                SearchSnippet(
                    title=r.title,
                    url=url,
                    description=(
                        r.description if hasattr(r, "description") else r.snippet
                    ),
                    weight=1,  # 初始权重为1
                    date=r.date if hasattr(r, "date") else None,
                )
            )

        # ---------- 2.3 添加结果到URL集合 ----------
        # 将每个结果添加到全局URL字典，并累计效用分数
        for r in min_results:
            utility_score += add_to_all_urls(r, all_urls)

        # 记录已执行的查询
        searched_queries.append(query["q"])

        # ---------- 2.4 创建知识项 ----------
        # 为当前查询创建知识项并添加到结果列表
        new_knowledge.append(
            KnowledgeItem(
                type="side-info",  # 类型为侧面信息
                question=f'What do Internet say about "{old_query}"?',  # 构建问题
                answer=remove_html_tags(
                    "; ".join(r.description for r in min_results)
                ),  # 合并所有描述作为答案
                updated=(
                    format_date_range(query) if query.get("tbs") else None
                ),  # 添加日期范围（如果有）
            )
        )

    # ---------- 3. 处理搜索结果汇总 ----------
    # 处理无结果情况
    if not searched_queries:
        if only_hostnames:
            # 如果限制了主机名但没有结果，记录日志
            print(
                f"No results found for queries: {', '.join(uniq_q_only)} on hostnames: {', '.join(only_hostnames)}"
            )
            tracker_context.action_tracker.track_think(
                "hostnames_no_results",
                json_schema_gen.language_code,
                {"hostnames": ", ".join(only_hostnames)},
            )
    else:
        # 输出搜索效用统计
        print(f"Utility/Queries: {utility_score}/{len(searched_queries)}")

        # 当查询数量超过限制时发出警告
        if len(searched_queries) > MAX_QUERIES_PER_STEP:
            queries_str = ", ".join([f'"{q}"' for q in searched_queries])
            print(f"So many queries??? {queries_str}")

    # ---------- 4. 返回结果 ----------
    return new_knowledge, searched_queries


def includes_eval(
    all_checks: List[RepeatEvaluationType], eval_type: EvaluationType
) -> bool:
    """检查是否包含特定评估类型

    工作流程:
    1. 遍历所有检查项
    2. 如果找到匹配项则返回True
    3. 否则返回False

    Args:
        all_checks: 所有评估类型检查列表
        eval_type: 要查找的评估类型

    Returns:
        如果包含指定评估类型则为True，否则为False
    """
    return any(c.type == eval_type for c in all_checks)


async def get_response(
    question: str,
    token_budget: int = 400000,
    max_bad_attempts: int = 2,
    existing_context: Optional[Dict[str, Any]] = None,
    num_returned_urls: int = 100,
    no_direct_answer: bool = False,
    boost_hostnames: List[str] = [],
    bad_hostnames: List[str] = [],
    only_hostnames: List[str] = [],
) -> Dict[str, Any]:

    # 初始化步骤计数器
    step = 0
    total_step = 0

    # ---------- 问题处理与消息管理 ----------
    question = question.strip()
    messages = [{"role": "user", "content": question}]

    # ---------- 初始化工具和上下文 ----------
    # 初始化JSON模式生成器
    json_schema_gen = JsonSchemaGen()
    await json_schema_gen.set_language(question)

    # 初始化跟踪上下文（用于令牌和操作跟踪）
    tracker_context = TrackerContext(
        token_tracker=(
            existing_context.get("token_tracker", TokenTracker(token_budget))
            if existing_context
            else TokenTracker(token_budget)
        ),
        action_tracker=(
            existing_context.get("action_tracker", ActionTracker())
            if existing_context
            else ActionTracker()
        ),
    )

    # 初始化安全对象生成器
    generator = ObjectGeneratorSafe(tracker_context.token_tracker)

    # ---------- 初始化核心变量 ----------
    # 问题和知识管理
    gaps = [question]  # 待解决的问题队列
    all_questions = [question]  # 所有问题历史记录
    all_keywords: List[str] = []  # 搜索关键词历史
    all_knowledge: List[KnowledgeItem] = []  # 中间问题的答案知识

    # URL和资源管理
    all_urls: Dict[str, SearchSnippet] = {}  # 所有URL信息
    weighted_urls: List[BoostedSearchSnippet] = []  # 排序后的URL列表
    visited_urls: List[str] = []  # 已访问的URL
    bad_urls: List[str] = []  # 无效的URL

    # 操作控制标志
    allow_answer = True  # 允许直接回答
    allow_search = True  # 允许搜索
    allow_read = True  # 允许阅读URL
    allow_reflect = True  # 允许反思
    allow_coding = False  # 允许编码（默认禁用）

    # 上下文和响应管理
    diary_context: List[str] = []  # 日志上下文
    msg_with_knowledge: List[CoreMessage] = []  # 带知识的消息
    this_step: StepAction = {  # 当前步骤动作
        "action": "answer",
        "answer": "",
        "references": [],
        "think": "",
        "is_final": False,
    }

    # 评估和预算管理
    regular_budget = token_budget * 0.85  # 常规预算（保留15%给beast模式）
    evaluation_metrics: Dict[str, List[RepeatEvaluationType]] = {}  # 评估指标
    final_answer_pip: List[str] = []  # 最终答案改进计划
    trivial_question = False  # 是否为简单问题标志

    # ---------- 从消息中提取URL ----------
    for m in messages:
        content = m["content"]
        # 处理字符串内容
        if isinstance(content, str):
            content = content.strip()
        # 处理字典内容，提取文本
        elif isinstance(content, dict) and "text" in content:
            content = "\n".join(
                c["text"] for c in content if c["type"] == "text"
            ).strip()

        # 从内容中提取URL并添加到URL集合
        for u in extract_urls_with_description(content):
            add_to_all_urls(u, all_urls)

    # ---------- 主处理循环 ----------
    while (
        tracker_context.token_tracker.get_total_usage()["total_tokens"] < regular_budget
    ):
        # 更新步骤计数器
        step += 1
        total_step += 1

        # 计算预算使用百分比
        budget_percentage = (
            tracker_context.token_tracker.get_total_usage()["total_tokens"]
            / token_budget
            * 100
        )

        # 轮询选择当前问题
        current_question = gaps[total_step % len(gaps)]

        # 打印当前步骤信息
        print("\n" + "=" * 50)
        print(f"步骤 {total_step} / 预算使用 {budget_percentage:.2f}%")
        print("=" * 50)
        print(f"【待解决问题】: {gaps}")
        print(f"【当前问题】: {current_question}")

        # ---------- 问题评估设置 ----------
        # 处理原始问题（第一步）
        if current_question.strip() == question and total_step == 1:
            # 为原始问题设置评估指标
            evaluation_metrics[current_question] = [
                RepeatEvaluationType(type=e, num_evals_required=max_bad_attempts)
                for e in (
                    await evaluate_question(
                        current_question, tracker_context, json_schema_gen
                    )
                )
            ]
            # 额外添加严格评估类型
            evaluation_metrics[current_question].append(
                RepeatEvaluationType(
                    type=EvaluationType.STRICT, num_evals_required=max_bad_attempts
                )
            )
        # 处理子问题
        elif current_question.strip() != question:
            # 子问题使用空评估指标列表
            evaluation_metrics[current_question] = []

        # ---------- URL处理与排序 ----------
        if all_urls:
            # 过滤、排序URL
            weighted_urls = await rank_urls(
                filter_urls(all_urls, visited_urls, bad_hostnames, only_hostnames),
                {"question": current_question, "boost_hostnames": boost_hostnames},
                tracker_context,
            )
            # 每个域名最多保留2个URL，增加信息来源多样性
            weighted_urls = keep_k_per_hostname(weighted_urls, 2)
            print("【每个域名最多保留2个URL】:", len(weighted_urls))

        # 处理需要最新信息的问题
        if total_step == 1 and includes_eval(
            evaluation_metrics[current_question], EvaluationType.FRESHNESS
        ):
            # 强制搜索最新信息，禁用直接回答和反思
            allow_answer = False
            allow_reflect = False

        # 动态调整操作许可
        allow_read = allow_read and weighted_urls  # 只有当有URL时才允许阅读
        allow_search = allow_search and len(weighted_urls) < 200  # 防止过度搜索
        allow_reflect = allow_reflect and (
            len(gaps) <= MAX_REFLECT_PER_STEP
        )  # 限制反思次数


        if step == 1:
            allow_search = True
            allow_read = False
            allow_answer = False
            allow_reflect = False
            allow_coding = False
        if step == 2:
            allow_search = False
            allow_read = True
            allow_answer = False
            allow_reflect = False
            allow_coding = False
        if step == 3:
            allow_search = False
            allow_read = False
            allow_answer = True
            allow_reflect = False
            allow_coding = False
        if step == 4:
            allow_search = False
            allow_read = False
            allow_answer = False
            allow_reflect = True
            allow_coding = False


        # ---------- 生成提示和模式 ----------
        # 构建提示信息
        prompt, url_list = get_prompt(
            context=diary_context,
            all_keywords=all_keywords,
            allow_reflect=allow_reflect,
            allow_answer=allow_answer,
            allow_read=allow_read,
            allow_search=allow_search,
            allow_coding=allow_coding,
            all_urls=all_urls,
            beast_mode=False,
        )

        # 根据当前问题和允许的操作生成模式
        schema = json_schema_gen.get_agent_schema(
            allow_reflect,
            allow_read,
            allow_answer,
            allow_search,
            allow_coding,
            current_question,
        )

        # 组合消息和知识
        msg_with_knowledge = compose_msgs(
            messages,
            all_knowledge,
            current_question,
            final_answer_pip if current_question == question else None,
        )

        print(f"【prompt】: >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>{prompt}")
        print(
            f"【messages】: >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>{json.dumps(msg_with_knowledge, indent=4, ensure_ascii=False)}"
        )

        # ---------- 生成代理动作 ----------
        result = await generator.generate_object(
            {
                "model": "agent",
                "schema": schema,
                "system": prompt,
                "messages": msg_with_knowledge,
                "num_retries": 2,
            }
        )

        # 根据动作类型动态实例化对应的Action类
        action_type = result.object["action"]
        action_class = {
            "search": SearchAction,
            "answer": AnswerAction,
            "reflect": ReflectAction,
            "visit": VisitAction,
            "coding": CodingAction,
        }[action_type]

        # 构建步骤动作
        this_step = action_class(
            action=action_type,
            think=result.object["think"],
            **result.object[action_type],
        )

        # 打印允许的动作
        actions_str = ", ".join(
            action
            for action, allowed in [
                ("search", allow_search),
                ("read", allow_read),
                ("answer", allow_answer),
                ("reflect", allow_reflect),
            ]
            if allowed
        )

        print("【Action 选择】: >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
        print(f"[选择动作]: {this_step.action} <- [可用动作: {actions_str}]")
        print("[动作详情]: ", this_step)

        tracker_context.action_tracker.track_action(
            {
                "total_step": total_step,
                "this_step": this_step.__dict__,
                "gaps": gaps,
            }
        )

        # 重置标志
        allow_answer = True
        allow_reflect = True
        allow_read = True
        allow_search = True
        allow_coding = True

        # 执行步骤和动作
        if this_step.action == "answer" and this_step.answer:
            # ======== 回答动作处理 ========
            # 1. 更新引用，确保URL和引用信息正确
            await update_references(this_step, all_urls)

            # 2. 处理简单问题的直接回答情况
            if total_step == 1 and not this_step.references and not no_direct_answer:
                this_step.is_final = True
                trivial_question = True
                break

            # 3. 处理引用中的URL
            if this_step.references:
                # 3.1 收集新的URL
                urls = [
                    ref.url
                    for ref in this_step.references
                    if ref.url not in visited_urls
                ]
                unique_new_urls = list(set(urls))

                # 3.2 处理这些URL，获取内容
                await process_urls(
                    unique_new_urls,
                    tracker_context,
                    all_knowledge,
                    all_urls,
                    visited_urls,
                    bad_urls,
                    json_schema_gen,
                    current_question,
                )

                # 3.3 过滤掉坏URL的引用
                this_step.references = [
                    ref for ref in this_step.references if ref.url not in bad_urls
                ]

            # 4. 更新上下文
            update_context(
                {
                    "total_step": total_step,
                    "question": current_question,
                    **this_step.dict(),
                }
            )

            # 5. 评估回答质量
            print(f"【评估问题】: {current_question}")
            print(f"【评估指标】: {evaluation_metrics[current_question]}")
            evaluation = EvaluationResponse.model_construct(pass_eval=True, think="")

            if evaluation_metrics[current_question]:
                tracker_context.action_tracker.track_think(
                    "eval_first", json_schema_gen.language_code
                )
                evaluation = (
                    await evaluate_answer(
                        current_question,
                        this_step,
                        [e.type for e in evaluation_metrics[current_question]],
                        tracker_context,
                        all_knowledge,
                        json_schema_gen,
                    )
                    or evaluation
                )

            # 6. 处理原始问题的回答
            if current_question.strip() == question:
                allow_coding = False

                # 6.1 如果评估通过，完成处理
                if evaluation.pass_eval:
                    diary_context.append(
                        DIARY_FINAL_ANSWER_TEMPLATE.format(
                            step=step,
                            question=current_question,
                            answer=this_step.answer,
                            evaluation_think=evaluation.think,
                        )
                    )
                    this_step.is_final = True
                    break
                # 6.2 如果评估不通过，更新评估指标并尝试改进
                else:
                    evaluation_metrics[current_question] = [
                        e
                        for e in evaluation_metrics[current_question]
                        if (
                            e.type != evaluation.type
                            or (e.type == evaluation.type and e.num_evals_required > 1)
                        )
                    ]

                    # 收集改进计划
                    if (
                        evaluation.type == EvaluationType.STRICT
                    ) and evaluation.improvement_plan:
                        final_answer_pip.append(evaluation.improvement_plan)

                    # 如果没有更多评估指标，停止处理
                    if not evaluation_metrics[current_question]:
                        this_step.is_final = False
                        break

                    # 记录失败原因
                    diary_context.append(
                        DIARY_BAD_ANSWER_TEMPLATE.format(
                            step=step,
                            question=current_question,
                            answer=this_step.answer,
                            evaluation_think=evaluation.think,
                        )
                    )

                    # 分析错误并添加到知识
                    error_analysis = await analyze_steps(
                        diary_context, tracker_context, json_schema_gen
                    )

                    all_knowledge.append(
                        KnowledgeItem(
                            type="qa",
                            question=f"""
为什么下面这个答案对这个问题来说不好呢？请反思一下。

<question>
{current_question}
</question>

<answer>
{this_step.answer}
</answer>
""",
                            answer=f"""
{evaluation.think}

{error_analysis.recap}

{error_analysis.blame}

{error_analysis.improvement}
""",
                        )
                    )

                    # 重置参数准备下一轮尝试
                    allow_answer = False
                    # diary_context = []
                    # step = 0

            # 7. 处理子问题的回答
            elif evaluation.pass_eval:
                diary_context.append(
                    DIARY_SUBQUESTION_ANSWER_TEMPLATE.format(
                        step=step,
                        question=current_question,
                        answer=this_step.answer,
                        evaluation_think=evaluation.think,
                    )
                )

                # 将子问题答案添加到知识库
                all_knowledge.append(
                    KnowledgeItem(
                        type="qa",
                        question=current_question,
                        answer=this_step.answer,
                        references=this_step.references,
                        updated=format_date_based_on_type(datetime.now(), "full"),
                    )
                )

                # 从缺口中移除已回答的问题
                gaps.remove(current_question)

        # 711
        elif this_step.action == "reflect" and this_step.questions_to_answer:
            # ======== 反思动作处理 ========
            # 1. 对问题进行去重处理
            this_step.questions_to_answer = choose_k(
                (
                    await dedup_queries(
                        this_step.questions_to_answer, all_questions, tracker_context
                    )
                )["unique_queries"],
                MAX_QUERIES_PER_STEP,
            )
            new_gap_questions = this_step.questions_to_answer

            # 2. 如果有新的子问题，添加到缺口中
            if new_gap_questions:
                diary_context.append(
                    DIARY_REFLECT_NEW_QUESTIONS_TEMPLATE.format(
                        step=step,
                        question=current_question,
                        subquestions="\n".join(f"- {q}" for q in new_gap_questions),
                    )
                )
                gaps.extend(new_gap_questions)
                all_questions.extend(new_gap_questions)
                update_context({"total_step": total_step, **this_step.dict()})
            # 3. 如果没有新的子问题，记录到日志
            else:
                diary_context.append(
                    DIARY_REFLECT_NO_NEW_QUESTIONS_TEMPLATE.format(
                        step=step,
                        question=current_question,
                        gap_questions=", ".join(new_gap_questions),
                    )
                )
                update_context(
                    {
                        "total_step": total_step,
                        **this_step.dict(),
                        "result": "You have tried all possible questions and found no useful information. You must think out of the box or different angle!!!",
                    }
                )

            # 4. 禁用反思动作以防止循环
            allow_reflect = False

        # 742
        elif this_step.action == "search" and this_step.search_requests:
            # ======== 搜索动作处理 ========
            # 1. 去重和限制搜索请求数量
            this_step.search_requests = choose_k(
                (await dedup_queries(this_step.search_requests, [], tracker_context))[
                    "unique_queries"
                ],
                MAX_QUERIES_PER_STEP,
            )

            # 2. 执行第一轮搜索
            new_knowledge, searched_queries = await execute_search_queries(
                [{"q": q} for q in this_step.search_requests],
                tracker_context,
                all_urls,
                json_schema_gen,
            )

            # 3. 记录关键词和知识
            all_keywords.extend(searched_queries)
            all_knowledge.extend(new_knowledge)

            # 4. 根据初步结果重写查询
            sound_bites = " ".join(k.answer for k in new_knowledge)
            keywords_queries = await rewrite_query(
                this_step, sound_bites, tracker_context, json_schema_gen
            )
            q_only = [q["q"] for q in keywords_queries if q.get("q")]

            # 5. 去重并避免重复搜索
            uniq_q_only = choose_k(
                (await dedup_queries(q_only, all_keywords, tracker_context))[
                    "unique_queries"
                ],
                MAX_QUERIES_PER_STEP,
            )

            keywords_queries = [
                next((kq for kq in keywords_queries if kq["q"] == q), {"q": q})
                for q in uniq_q_only
            ]

            any_result = False

            # 6. 执行第二轮优化搜索(如果有新查询)
            if keywords_queries:
                new_knowledge, searched_queries = await execute_search_queries(
                    keywords_queries,
                    tracker_context,
                    all_urls,
                    json_schema_gen,
                    only_hostnames,
                )

                # 如果有结果，记录信息
                if searched_queries:
                    any_result = True
                    all_keywords.extend(searched_queries)
                    all_knowledge.extend(new_knowledge)

                    diary_context.append(
                        DIARY_SEARCH_SUCCESS_TEMPLATE.format(
                            step=step,
                            question=current_question,
                            keywords=", ".join(q["q"] for q in keywords_queries),
                        )
                    )

                    update_context(
                        {
                            "total_step": total_step,
                            "question": current_question,
                            **this_step.dict(),
                            "result": result,
                        }
                    )

            # 7. 如果没有结果，记录到日志
            if not any_result or not keywords_queries:
                diary_context.append(
                    DIARY_SEARCH_FAIL_TEMPLATE.format(
                        step=step,
                        question=current_question,
                        keywords=", ".join(q["q"] for q in keywords_queries),
                    )
                )

                update_context(
                    {
                        "total_step": total_step,
                        **this_step.dict(),
                        "result": "You have tried all possible queries and found no new information. You must think out of the box or different angle!!!",
                    }
                )

            # 8. 禁用搜索动作以防止循环
            allow_search = False

        # 816
        elif this_step.action == "visit" and this_step.url_targets and url_list:
            # ======== 访问URL动作处理 ========
            # 1. 处理URL目标，确保规范化并去重
            this_step.url_targets = [
                normalize_url(url_list[idx - 1])
                for idx in this_step.url_targets
                if isinstance(idx, int)
                and normalize_url(url_list[idx - 1]) not in visited_urls
            ]

            # 2. 合并目标URL和优先级URL
            this_step.url_targets = list(
                set([*this_step.url_targets, *[u.url for u in weighted_urls]])
            )[:MAX_URLS_PER_STEP]

            unique_urls = this_step.url_targets
            print("【visit】:", unique_urls)

            # 3. 如果有URL，处理它们
            if unique_urls:
                # 3.1 读取URL内容
                process_results = await process_urls(
                    urls=unique_urls,
                    tracker_context=tracker_context,
                    all_knowledge=all_knowledge,
                    all_urls=all_urls,
                    visited_urls=visited_urls,
                    bad_urls=bad_urls,
                    schema_gen=json_schema_gen,
                    question=current_question,
                )
                url_results = process_results["url_results"]
                success = process_results["success"]

                # 3.2 记录结果到日志
                diary_context.append(
                    DIARY_VISIT_SUCCESS_TEMPLATE.format(
                        step=step, urls="\n".join(str(r.url) for r in url_results)
                    )
                    if success
                    else DIARY_VISIT_FAIL_TEMPLATE.format(step=step)
                )

                # 3.3 更新上下文
                update_context(
                    {
                        "total_step": total_step,
                        **(
                            {
                                "question": current_question,
                                **this_step.dict(),
                                "result": url_results,
                            }
                            if success
                            else {
                                **this_step.dict(),
                                "result": "You have tried all possible URLs and found no new information. You must think out of the box or different angle!!!",
                            }
                        ),
                    }
                )
            # 4. 如果没有新URL，记录到日志
            else:
                diary_context.append(DIARY_VISIT_NO_NEW_URLS_TEMPLATE.format(step=step))

                update_context(
                    {
                        "total_step": total_step,
                        **this_step.dict(),
                        "result": "You have visited all possible URLs and found no new information. You must think out of the box or different angle!!!",
                    }
                )

            # 5. 禁用读取动作以防止循环
            allow_read = False

        elif this_step.action == "coding" and this_step.coding_issue:
            # ======== 编码动作处理 ========
            # 1. 初始化代码沙箱
            sandbox = CodeSandbox(
                {
                    "all_context": all_context,
                    "URLs": weighted_urls[:20],
                    "all_knowledge": all_knowledge,
                },
                tracker_context,
                json_schema_gen,
            )

            try:
                # 2. 尝试解决编码问题
                result = await sandbox.solve(this_step.coding_issue)

                # 3. 将解决方案添加到知识库
                all_knowledge.append(
                    KnowledgeItem(
                        type="coding",
                        question=f"What is the solution to the coding issue: {this_step.coding_issue}?",
                        answer=result.solution.output,
                        source_code=result.solution.code,
                        updated=format_date_based_on_type(datetime.now(), "full"),
                    )
                )

                # 4. 记录结果到日志
                diary_context.append(
                    DIARY_CODING_SUCCESS_TEMPLATE.format(
                        step=step, issue=this_step.coding_issue
                    )
                )

                # 5. 更新上下文
                update_context(
                    {"total_step": total_step, **this_step.dict(), "result": result}
                )

            except Exception as error:
                # 6. 处理错误情况
                print("解决编码问题时出错:", error)
                diary_context.append(
                    DIARY_CODING_FAIL_TEMPLATE.format(
                        step=step, issue=this_step.coding_issue
                    )
                )

                update_context(
                    {
                        "total_step": total_step,
                        **this_step.dict(),
                        "result": "You have tried all possible solutions and found no new information. You must think out of the box or different angle!!!",
                    }
                )

            finally:
                # 7. 禁用编码动作以防止循环
                allow_coding = False

        await store_context(
            question,
            prompt,
            schema,
            this_step,
            {
                "all_context": all_context,
                "all_keywords": all_keywords,
                "all_questions": all_questions,
                "all_knowledge": all_knowledge,
                "weighted_urls": weighted_urls,
                "msg_with_knowledge": msg_with_knowledge,
            },
            total_step,
        )

        await sleep(STEP_SLEEP)

    # ======== 野兽模式(Beast Mode) ========
    # 当正常预算耗尽但仍未得到最终答案时激活
    if "is_final" not in this_step or not this_step.is_final:
        print("\n" + "=" * 50)
        print("进入野兽模式!!!")
        print("=" * 50)
        step += 1
        total_step += 1

        # 1. 生成特殊的"野兽模式"提示
        prompt, _ = get_prompt(
            context=diary_context,
            all_keywords=all_keywords,
            allow_reflect=False,  # 禁用反思
            allow_answer=False,  # 禁用常规回答
            allow_read=False,  # 禁用URL读取
            allow_search=False,  # 禁用搜索
            allow_coding=False,  # 禁用编码
            all_urls=all_urls,
            beast_mode=True,  # 启用野兽模式
        )

        # 2. 准备最终回答的模式和消息
        schema = json_schema_gen.get_agent_schema(
            allow_reflect=False,
            allow_read=False,
            allow_answer=True,
            allow_search=False,
            allow_coding=False,
            current_question=question,
        )
        msg_with_knowledge = compose_msgs(
            messages, all_knowledge, question, final_answer_pip
        )

        result = await generator.generate_object(
            {
                "model": "agentBeastMode",
                "schema": schema,
                "system": prompt,
                "messages": msg_with_knowledge,
                "numRetries": 2,
            }
        )

        print(f"【prompt】: >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>{prompt}")
        print(
            f"【messages】: >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>{json.dumps(msg_with_knowledge, indent=4, ensure_ascii=False)}"
        )

        this_step = AnswerAction(
            action=result.object["action"],
            think=result.object["think"],
            **result.object[result.object["action"]],
        )

        # 4. 更新引用并标记为最终答案
        await update_references(this_step, all_urls)
        this_step.is_final = True

        # 5. 记录动作
        tracker_context.action_tracker.track_action(
            {"total_step": total_step, "this_step": this_step, "gaps": gaps}
        )

        await store_context(
            question,
            prompt,
            schema,
            this_step,
            {
                "all_context": all_context,
                "all_keywords": all_keywords,
                "all_questions": all_questions,
                "all_knowledge": all_knowledge,
                "weighted_urls": weighted_urls,
                "msg_with_knowledge": msg_with_knowledge,
            },
            total_step,
        )

    # ======== 最终处理 ========
    # 1. 根据问题类型处理Markdown格式
    # TODO
    # if not trivial_question:
    #     # 复杂问题的完整处
    #     this_step.md_answer = repair_markdown_final(
    #         convert_html_tables_to_md(
    #             fix_bad_url_md_links(
    #                 fix_code_block_indentation(
    #                     repair_markdown_footnotes_outer(
    #                         await repair_unknown_chars(
    #                             await fix_markdown(
    #                                 build_md_from_answer(this_step),
    #                                 all_knowledge,
    #                                 tracker_context,
    #                                 json_schema_gen,
    #                             ),
    #                             tracker_context,
    #                         )
    #                     )
    #                 ),
    #                 all_urls,
    #             )
    #         )
    #     )
    # else:
    #     # 简单问题的基本处理
    #     this_step.md_answer = convert_html_tables_to_md(
    #         fix_code_block_indentation(build_md_from_answer(this_step))
    #     )

    # 2. 返回结果、上下文和URL信息(最多返回300个url)

    print("\n" + "=" * 50)
    print("最终答案:", this_step.answer)
    print("Read URLs:", this_step.references)
    print("=" * 50)

    return {
        "result": this_step,
        "context": tracker_context,
        "visited_urls": [r.url for r in weighted_urls[:num_returned_urls]],
        "read_urls": [url for url in visited_urls if url not in bad_urls],
        "all_urls": [r.url for r in weighted_urls],
    }


async def store_context(
    question: str,
    prompt: str,
    schema: Any,
    this_step: StepAction,
    memory: Dict[str, Any],
    step: int,
) -> None:

    try:
        import json
        from pathlib import Path

        # 写入提示和schema
        with open(
            f"./context/prompt-{question[:20]}-{step}.txt", "w", encoding="utf-8"
        ) as f:
            f.write(
                f"""
【Prompt】:
{prompt}

【message】:
{json.dumps(memory["msg_with_knowledge"], indent=2, ensure_ascii=False)}

【JSONSchema】:
{json.dumps(schema, indent=2, ensure_ascii=False)}

【this_step】:
{json.dumps(this_step.dict(), indent=2, ensure_ascii=False)}
"""
            )

        # # 写入其他上下文数据
        # for name, data in memory.items():
        #     with open(f"{name}.json", "w", encoding="utf-8") as f:
        #         json.dumps(
        #             data,
        #             indent=2,
        #             default=lambda x: x.dict() if hasattr(x, "dict") else str(x),
        #         )

    except Exception as error:
        print("Context storage failed:", error)