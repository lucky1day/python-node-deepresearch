import re
import random
import asyncio
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional, Set, Union, Callable
from urllib.parse import urlparse, parse_qsl, urlencode, ParseResult, unquote, quote
from ..model_types import ReadResponseData

# 确保项目根目录在Python路径中
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# 添加fetch函数的导入
try:
    from aiohttp import ClientSession
except ImportError:
    # 如果aiohttp不可用，提供一个基本的fetch实现
    import urllib.request
    import json

    async def fetch(url):
        """简单的fetch实现，用于在aiohttp不可用时提供基本功能"""

        class Response:
            def __init__(self, status, data):
                self.ok = status == 200
                self.status = status
                self._data = data

            async def json(self):
                return json.loads(self._data)

        try:
            with urllib.request.urlopen(url) as response:
                return Response(response.status, response.read())
        except Exception as e:
            print(f"Fetch error: {e}")
            return Response(500, "{}")

else:

    async def fetch(url):
        """使用aiohttp的fetch实现"""
        class Response:
            def __init__(self, status, data):
                self.ok = status == 200
                self.status = status
                self._data = data

            async def json(self):
                if isinstance(self._data, str):
                    return json.loads(self._data)
                return self._data

        async with ClientSession() as session:
            async with session.get(url) as response:
                status = response.status
                try:
                    # 预先读取响应数据，避免会话关闭后无法访问
                    data = await response.json()
                except:
                    # 如果不是JSON数据，则尝试读取文本
                    try:
                        data = await response.text()
                    except:
                        data = "{}"
                
                return Response(status, data)


# 适当导入项目模块
try:
    from ..model_types import (
        BoostedSearchSnippet,
        KnowledgeItem,
        SearchSnippet,
        TrackerContext,
        VisitAction,
        UnNormalizedSearchSnippet,
    )
    from ..utils.text_tools import get_i18n_text, smart_merge_strings
    from ..tools.jina_rerank import rerank_documents
    from ..tools.jina_read import read_url
    from ..utils.schemas import JsonSchemaGen
    from ..tools.jina_latechunk import cherry_pick
    from ..utils.date_tools import format_date_based_on_type
    from ..tools.jina_classify_spam import classify_text
    from ..utils.token_tracker import TokenTracker
    from ..utils.action_tracker import ActionTracker
except ImportError:
    from deepresearch.model_types import (
        BoostedSearchSnippet,
        KnowledgeItem,
        SearchSnippet,
        TrackerContext,
        VisitAction,
        UnNormalizedSearchSnippet,
    )
    from deepresearch.utils.text_tools import get_i18n_text, smart_merge_strings
    from deepresearch.tools.jina_rerank import rerank_documents
    from deepresearch.tools.jina_read import read_url
    from deepresearch.utils.schemas import JsonSchemaGen
    from deepresearch.tools.jina_latechunk import cherry_pick
    from deepresearch.utils.date_tools import format_date_based_on_type
    from deepresearch.tools.jina_classify_spam import classify_text
    from deepresearch.utils.token_tracker import TokenTracker
    from deepresearch.utils.action_tracker import ActionTracker


def normalize_url(
    url_string: str, debug: bool = False, options: Dict[str, bool] = None
) -> Optional[str]:
    """
    规范化URL，移除跟踪参数、会话ID和其他常见的变体
    """
    if options is None:
        options = {
            "remove_anchors": True,
            "remove_session_ids": True,
            "remove_utm_params": True,
            "remove_tracking_params": True,
            "remove_x_analytics": True,
        }

    try:
        url_string = url_string.replace(" ", "").strip()

        if not url_string:
            raise ValueError("Empty URL")

        if url_string.startswith("https://google.com/") or url_string.startswith(
            "https://www.google.com"
        ):
            raise ValueError("Google search link")

        if "example.com" in url_string:
            raise ValueError("Example URL")

        # 处理x.com和twitter.com带有/analytics的URL
        if options.get("remove_x_analytics", True):
            x_com_pattern = r"^(https?:\/\/(www\.)?(x\.com|twitter\.com)\/([^/]+)\/status\/(\d+))\/analytics(\/)?(\?.*)?(#.*)?$"
            x_match = re.match(x_com_pattern, url_string, re.IGNORECASE)
            if x_match:
                clean_url = x_match.group(1)  # 不带/analytics的基本URL
                if x_match.group(7):  # 如果存在查询参数
                    clean_url += x_match.group(7)
                if x_match.group(8):  # 如果存在片段
                    clean_url += x_match.group(8)
                url_string = clean_url

        # 解析URL
        url = urlparse(url_string)

        if url.scheme not in ["http", "https"]:
            raise ValueError("Unsupported protocol")

        # 规范化主机名
        hostname = url.hostname.lower() if url.hostname else ""
        if hostname.startswith("www."):
            hostname = hostname[4:]

        # 移除默认端口
        port = ""
        if (url.scheme == "http" and url.port == 80) or (
            url.scheme == "https" and url.port == 443
        ):
            port = ""
        else:
            port = f":{url.port}" if url.port else ""

        # 路径规范化
        path_segments = url.path.split("/")
        normalized_path_segments = []
        for segment in path_segments:
            try:
                decoded_segment = unquote(segment)
                normalized_path_segments.append(decoded_segment)
            except Exception as e:
                if debug:
                    print(f"Failed to decode path segment: {segment}", e)
                normalized_path_segments.append(segment)

        path = "/".join(normalized_path_segments)
        path = re.sub(r"/+", "/", path)
        path = re.sub(r"/+$", "", path) or "/"

        # 查询参数规范化
        query_params = parse_qsl(url.query)
        filtered_params = []

        for key, value in query_params:
            if not key:
                continue

            # 移除会话ID
            if options.get("remove_session_ids", True) and re.match(
                r"^(s|session|sid|sessionid|phpsessid|jsessionid|aspsessionid|asp\.net_sessionid)$",
                key,
                re.IGNORECASE,
            ):
                continue

            # 移除UTM参数
            if options.get("remove_utm_params", True) and key.lower().startswith(
                "utm_"
            ):
                continue

            # 移除常见跟踪参数
            if options.get("remove_tracking_params", True) and re.match(
                r"^(ref|referrer|fbclid|gclid|cid|mcid|source|medium|campaign|term|content|sc_rid|mc_[a-z]+)$",
                key,
                re.IGNORECASE,
            ):
                continue

            # 规范化值
            try:
                if value == "":
                    filtered_params.append((key, value))
                else:
                    decoded_value = unquote(value)
                    if quote(decoded_value) == value:
                        filtered_params.append((key, decoded_value))
                    else:
                        filtered_params.append((key, value))
            except Exception as e:
                if debug:
                    print(f"Failed to decode query param {key}={value}", e)
                filtered_params.append((key, value))

        # 按键排序
        filtered_params.sort(key=lambda x: x[0])
        query = urlencode(filtered_params)

        # 处理片段（锚点）
        fragment = ""
        if options.get("remove_anchors", True):
            pass  # 完全移除
        elif url.fragment in ["", "top", "/"]:
            pass  # 移除常见的无意义片段
        else:
            try:
                decoded_fragment = unquote(url.fragment)
                if quote(decoded_fragment) == url.fragment:
                    fragment = decoded_fragment
                else:
                    fragment = url.fragment
            except Exception as e:
                if debug:
                    print(f"Failed to decode fragment: {url.fragment}", e)
                fragment = url.fragment

        # 构建规范化URL
        normalized_url = f"{url.scheme}://{hostname}{port}{path}"
        if query:
            normalized_url += f"?{query}"
        if fragment and not options.get("remove_anchors", True):
            normalized_url += f"#{fragment}"

        return normalized_url

    except Exception as error:
        print(f"Invalid URL '{url_string}': {error}")
        return None


def filter_urls(
    all_urls: Dict[str, SearchSnippet],
    visited_urls: List[str],
    bad_hostnames: List[str],
    only_hostnames: List[str],
) -> List[SearchSnippet]:
    """过滤URL列表，排除已访问的和不良主机名的URL"""
    return [
        snippet
        for url, snippet in all_urls.items()
        if (
            url not in visited_urls
            and extract_url_parts(url)["hostname"] not in bad_hostnames
            and (
                not only_hostnames
                or extract_url_parts(url)["hostname"] in only_hostnames
            )
        )
    ]


def extract_url_parts(url_str: str) -> Dict[str, str]:
    """从URL中提取主机名和路径"""
    try:
        url = urlparse(url_str)
        return {
            "hostname": url.hostname or "",
            "path": url.pathname if hasattr(url, "pathname") else url.path or "",
        }
    except Exception as e:
        print(f"Error parsing URL: {url_str}", e)
        return {"hostname": "", "path": ""}


def count_url_parts(url_items: List[SearchSnippet]) -> Dict[str, Any]:
    """统计主机名和路径前缀的出现次数"""
    hostname_count = {}
    path_prefix_count = {}
    total_urls = 0

    for item in url_items:
        if not item or not hasattr(item, "url") or not item.url:
            continue

        total_urls += 1
        parts = extract_url_parts(item.url)
        hostname = parts["hostname"]
        path = parts["path"]

        # 统计主机名
        hostname_count[hostname] = hostname_count.get(hostname, 0) + 1

        # 统计路径前缀（段）
        path_segments = [s for s in path.split("/") if s]
        for i in range(len(path_segments)):
            prefix = "/" + "/".join(path_segments[: i + 1])
            path_prefix_count[prefix] = path_prefix_count.get(prefix, 0) + 1

    return {
        "hostname_count": hostname_count,
        "path_prefix_count": path_prefix_count,
        "total_urls": total_urls,
    }


def normalize_count(count: int, total: int) -> float:
    """计算归一化频率用于提升权重"""
    return count / total if total > 0 else 0


async def rank_urls(
    url_items: List[SearchSnippet],
    options: Dict[str, Any] = None,
    trackers: TrackerContext = None,
) -> List[BoostedSearchSnippet]:
    """根据多个因素对URL进行排名和加权"""
    if options is None:
        options = {}

    # 默认参数
    freq_factor = options.get("freq_factor", 0.5)
    hostname_boost_factor = options.get("hostname_boost_factor", 0.5)
    path_boost_factor = options.get("path_boost_factor", 0.4)
    decay_factor = options.get("decay_factor", 0.8)
    jina_rerank_factor = options.get("jina_rerank_factor", 0.8)
    min_boost = options.get("min_boost", 0)
    max_boost = options.get("max_boost", 5)
    question = options.get("question", "")
    boost_hostnames = options.get("boost_hostnames", [])

    # 首先计算URL部分
    counts = count_url_parts(url_items)
    hostname_count = counts["hostname_count"]
    path_prefix_count = counts["path_prefix_count"]
    total_urls = counts["total_urls"]

    # 如果有问题，使用Jina重新排名
    if question and question.strip():
        # 第1步：创建一个记录来跟踪具有原始索引的唯一内容
        unique_content_map = {}

        for i, item in enumerate(url_items):
            merged_content = smart_merge_strings(item.title, item.description)

            if merged_content not in unique_content_map:
                unique_content_map[merged_content] = [i]
            else:
                unique_content_map[merged_content].append(i)

        # 第2步：仅对唯一内容进行重新排名
        unique_contents = list(unique_content_map.keys())
        unique_indices_map = list(unique_content_map.values())
        print(f"【rerank_documents】: {len(url_items)}->{len(unique_contents)}")

        try:
            results = await rerank_documents(
                query=question, documents=unique_contents, tracker_context=trackers
            )
            jina_rerank_boosts = [0 for _ in range(len(url_items))]

            for result in results.get("results", []):
                index = result.get("index", 0)
                relevance_score = result.get("relevance_score", 0)
                boost = relevance_score * jina_rerank_factor
                for index_ in unique_indices_map[index]:
                    jina_rerank_boosts[index_] = boost

        except Exception as e:
            print(f"Error applying rerank boost: {e}")

    # 计算最终得分并创建排名结果
    result_items = []

    for i, item in enumerate(url_items):
        if not item or not hasattr(item, "url") or not item.url:
            print("Skipping invalid item:", item)
            continue

        parts = extract_url_parts(item.url)
        hostname = parts["hostname"]
        path = parts["path"]

        # 基本权重
        freq = getattr(item, "weight", 0)

        # 主机名提升（按总URL归一化）
        hostname_freq = normalize_count(hostname_count.get(hostname, 0), total_urls)
        hostname_boost = (
            hostname_freq
            * hostname_boost_factor
            * (2 if hostname in boost_hostnames else 1)
        )

        # 路径提升（考虑所有路径前缀，对更长的路径应用衰减）
        path_boost = 0
        path_segments = [s for s in path.split("/") if s]

        for i, segment in enumerate(path_segments):
            prefix = "/" + "/".join(path_segments[: i + 1])
            prefix_count = path_prefix_count.get(prefix, 0)
            prefix_freq = normalize_count(prefix_count, total_urls)

            # 根据路径深度应用衰减因子
            decayed_boost = prefix_freq * (decay_factor**i) * path_boost_factor
            path_boost += decayed_boost

        freq_boost = freq / total_urls * freq_factor if total_urls > 0 else 0

        jina_rerank_boost = jina_rerank_boosts[i]

        # 计算新权重并限制在范围内
        final_score = min(
            max(
                hostname_boost + path_boost + freq_boost + jina_rerank_boost, min_boost
            ),
            max_boost,
        )

        # 创建包含所有提升因素的结果项
        result_item = BoostedSearchSnippet(
            freq_boost=freq_boost,
            hostname_boost=hostname_boost,
            path_boost=path_boost,
            jina_rerank_boost=jina_rerank_boost,
            final_score=final_score,
            score=final_score,
            merged=smart_merge_strings(item.title, item.description),
            **item.__dict__,
        )

        result_items.append(result_item)

    # 按最终分数排序
    result_items.sort(key=lambda x: x.final_score, reverse=True)
    return result_items


# async def apply_rerank_boost(
#     question: str,
#     unique_contents: List[str],
#     unique_indices_map: List[List[int]],
#     url_items: List[SearchSnippet],
#     trackers: TrackerContext,
#     jina_rerank_factor: float
# ):
#     """异步应用Jina重排序提升 - 模拟TypeScript的Promise.then"""
#     try:
#         results = await rerank_documents(query=question, documents=unique_contents, tracker=trackers)

#         for result in results.get("results", []):
#             index = result.get("index", 0)
#             relevance_score = result.get("relevance_score", 0)
#             boost = relevance_score * jina_rerank_factor

#             # 对具有相同内容的所有项目应用相同的提升
#             for original_index in unique_indices_map[index]:
#                 # 确保url_items[original_index]是BoostedSearchSnippet类型
#                 if not hasattr(url_items[original_index], 'jina_rerank_boost'):
#                     url_items[original_index] = SearchSnippet(
#                         jina_rerank_boost= boost,
#                         **url_items[original_index].__dict__
#                     )

#                 else:
#                     url_items[original_index].jina_rerank_boost = boost
#     except Exception as e:
#         print(f"Error applying rerank boost: {e}")


def add_to_all_urls(
    r: SearchSnippet, all_urls: Dict[str, SearchSnippet], weight_delta: float = 1.0
) -> int:
    """将搜索结果添加到URL集合中，如果已存在则更新权重和描述"""
    normalized_url = normalize_url(r.url)
    if not normalized_url:
        return 0

    if normalized_url not in all_urls:
        # 创建新条目
        all_urls[normalized_url] = r
        all_urls[normalized_url].weight = weight_delta
        return 1
    else:
        # 更新现有条目
        if not hasattr(all_urls[normalized_url], "weight"):
            all_urls[normalized_url].weight = 0
        all_urls[normalized_url].weight += weight_delta
        current_desc = all_urls[normalized_url].description
        all_urls[normalized_url].description = smart_merge_strings(
            current_desc, r.description
        )
        return 0


def sort_select_urls(
    all_urls: List[BoostedSearchSnippet], max_urls: int = 70
) -> List[Dict[str, Any]]:
    """根据分数排序并选择前N个URL"""
    if not all_urls or len(all_urls) == 0:
        return []

    result = []
    for r in all_urls.values():
        merged = smart_merge_strings(r.title, r.description)
        if merged and merged != "" and merged is not None:
            result.append(
                {
                    "url": r.url,
                    "score": getattr(r, "final_score", getattr(r, "weight", 0)),
                    "merged": merged,
                }
            )

    # 按分数降序排序并限制数量
    return sorted(result, key=lambda x: x.get("score", 0) or 0, reverse=True)[:max_urls]


def sample_multinomial(items: List[Tuple[Any, float]]) -> Optional[Any]:
    """从多项分布中抽样"""
    if not items:
        return None

    # 计算总权重
    total_weight = sum(weight for _, weight in items)

    if total_weight == 0:
        return None

    # 生成0到总权重之间的随机数
    rand_value = random.random() * total_weight

    # 找到对应于随机值的项
    cumulative_weight = 0
    for item, weight in items:
        cumulative_weight += weight
        if rand_value <= cumulative_weight:
            return item

    # 作为浮点精度问题的后备
    return items[-1][0]


async def get_last_modified(url: str) -> Optional[str]:
    """使用日期时间检测API获取URL的最后修改日期"""
    try:
        # 调用API并正确编码
        api_url = f"https://api-beta-datetime.jina.ai?url={quote(url)}"
        response = await fetch(api_url)

        if not response.ok:
            raise ValueError(f"API returned {response.status}")

        data = await response.json()

        # 如果可用，返回bestGuess日期
        if data.get("bestGuess") and data.get("confidence", 0) >= 70:
            return data["bestGuess"]

        return None
    except Exception as error:
        print("Failed to fetch last modified date:", error)
        return None


def keep_k_per_hostname(
    results: List[BoostedSearchSnippet], k: int
) -> List[BoostedSearchSnippet]:
    """每个主机名最多保留K个结果"""
    hostname_map = {}
    filtered_results = []

    for result in results:
        hostname = extract_url_parts(result.url).get("hostname", "")

        if hostname not in hostname_map:
            hostname_map[hostname] = 0

        if hostname_map[hostname] < k:
            filtered_results.append(result)
            hostname_map[hostname] += 1

    return filtered_results


async def process_urls(
    urls: List[str],
    tracker_context: TrackerContext,
    all_knowledge: List[KnowledgeItem],
    all_urls: Dict[str, SearchSnippet],
    visited_urls: List[str],
    bad_urls: List[str],
    schema_gen: JsonSchemaGen,
    question: str,
) -> Dict[str, Any]:
    """处理URL列表，读取内容并更新知识库"""
    # 如果没有URL要处理则跳过
    if not urls:
        return {"url_results": [], "success": False}

    bad_hostnames: List[str] = []

    # 跟踪阅读操作
    this_step = {
        "action": "visit",
        "think": get_i18n_text(
            "read_for", schema_gen.language_code, {"urls": ", ".join(urls)}
        ),
        "URLTargets": urls,
    }
    tracker_context.action_tracker.track_action({"this_step": this_step})

    # 并行处理每个URL
    tasks = [
        process_url(
            url=url,
            tracker_context=tracker_context,
            all_knowledge=all_knowledge,
            all_urls=all_urls,
            visited_urls=visited_urls,
            bad_urls=bad_urls,
            schema_gen=schema_gen,
            question=question,
            bad_hostnames=bad_hostnames,
        )
        for url in urls
    ]
    url_results = await asyncio.gather(*tasks)

    # 过滤出有效结果
    valid_results = [result for result in url_results if result]

    # 从all_urls中删除任何具有不良主机名的URL
    if bad_hostnames:
        for url in list(all_urls.keys()):
            if extract_url_parts(url)["hostname"] in bad_hostnames:
                del all_urls[url]
                print(f"Removed {url} from all_urls")

    return {
        "url_results": valid_results,
        "success": len(valid_results) > 0,
    }


async def process_url(
    url: str,
    tracker_context: TrackerContext,
    all_knowledge: List[KnowledgeItem],
    all_urls: Dict[str, SearchSnippet],
    visited_urls: List[str],
    bad_urls: List[str],
    schema_gen: JsonSchemaGen,
    question: str,
    bad_hostnames: List[str],
) -> ReadResponseData:
    """处理单个URL - process_urls的辅助函数"""
    try:
        normalized_url = normalize_url(url)
        if not normalized_url:
            return None

        # 存储规范化URL以供一致引用
        url = normalized_url

        # 读取URL内容
        response = await read_url(url, True, tracker_context)
        data = response.data

        # 尝试获取时间信息
        guessed_time = await get_last_modified(url)
        if guessed_time:
            print("Guessed time for", url, guessed_time)

        # 如果没有有效数据则提前返回
        if not data.url or not data.content:
            raise ValueError("No content found")

        # 检查内容是否是来自付费墙、机器人检测等的阻止消息
        # 仅检查短内容，因为大多数阻止消息都很短
        spam_detect_length = 300
        is_good_content = len(
            data.content
        ) > spam_detect_length or not await classify_text(data.content)

        if not is_good_content:
            print(
                f"Blocked content {len(data.content)}:",
                url,
                data.content[:spam_detect_length],
            )
            raise ValueError(f"Blocked content {url}")

        # 添加到知识库
        all_knowledge.append(
            KnowledgeItem(
                type="url",
                question=f'What do expert say about "{question}"?',
                answer=await cherry_pick(
                    question, data.content, {}, tracker_context, url, schema_gen
                ),
                references=[data.url],
                updated=(
                    format_date_based_on_type(guessed_time, "full")
                    if guessed_time
                    else None
                ),
            )
        )

        # 处理页面链接
        if data.links:
            for link in data.links:
                nn_url = normalize_url(link[1])
                if not nn_url:
                    continue

                r = SearchSnippet(title=link[0], url=nn_url, description=link[0])
                # 页面内链接与搜索链接相比具有较低的初始权重
                add_to_all_urls(r, all_urls, 0.1)

        return data
        
    except Exception as error:
        print("Error reading URL:", url, error)
        bad_urls.append(url)

        # 从URL中提取主机名
        error_str = str(error)
        if (
            (
                getattr(error, "name", "") == "ParamValidationError"
                and "Domain" in getattr(error, "message", "")
            )
            or (
                getattr(error, "name", "") == "AssertionFailureError"
                and "resolve host name" in getattr(error, "message", "")
            )
            or "Couldn't resolve host name" in error_str
            or "could not be resolved" in error_str
            or "ERR_CERT_COMMON_NAME_INVALID" in error_str
            or "ERR_CONNECTION_REFUSED" in error_str
        ):
            try:
                hostname = extract_url_parts(url)["hostname"]
                if hostname:
                    bad_hostnames.append(hostname)
                    print(f"Added {hostname} to bad hostnames list")
            except Exception as e:
                print("Error parsing URL for hostname:", url, e)
        return None
    finally:
        # 只将有效URL添加到已访问URL列表
        if url:
            visited_urls.append(url)

            # 确认此URL的访问操作已完成
            tracker_context.action_tracker.track_action(
                {"thisStep": {"action": "visit", "think": "", "URLTargets": [url]}}
            )


def fix_bad_url_md_links(md_content: str, all_urls: Dict[str, SearchSnippet]) -> str:
    """修复Markdown中的不良URL链接，使其更美观"""
    # 用于查找[url](url)模式的Markdown链接的正则表达式
    md_link_regex = r"\[([^\]]+)]\(([^)]+)\)"

    def replace_match(match):
        text, url = match.groups()

        # 检查文本和URL是否相同
        if text == url:
            # 直接在记录中查找URL
            url_info = all_urls.get(url)

            if url_info:
                try:
                    # 从URL中提取主机名
                    hostname = urlparse(url).hostname

                    # 如果标题可用，使用[title - hostname](url)格式
                    if url_info.title:
                        return f"[{url_info.title} - {hostname}]({url})"
                    # 否则使用[hostname](url)格式
                    else:
                        return f"[{hostname}]({url})"
                except Exception:
                    # 如果URL解析失败，返回原始链接
                    return match.group(0)
            else:
                # 如果URL不在all_urls中，尝试提取主机名
                try:
                    hostname = urlparse(url).hostname
                    return f"[{hostname}]({url})"
                except Exception:
                    # 如果URL解析失败，返回原始链接
                    return match.group(0)
        else:
            # 如果文本和URL不同，保持链接原样
            return match.group(0)

    # 替换每个匹配项
    return re.sub(md_link_regex, replace_match, md_content)


def extract_urls_with_description(
    text: str, context_window_size: int = 50
) -> List[SearchSnippet]:
    """从文本中提取URL及其上下文描述"""
    # 使用更精确的正则表达式进行URL检测，适用于多语言文本
    url_pattern = r"https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_+.~#?&//=]*)"

    # 查找所有匹配项
    matches = []

    for match in re.finditer(url_pattern, text):
        url = match.group(0)
        length = len(url)

        # 清理尾随标点符号（句号、逗号等）
        if re.search(r"[.,;:!?)]$", url):
            url = url[:-1]
            length = len(url)

        matches.append({"url": url, "index": match.start(), "length": length})

    # 如果没有找到URL，则返回空数组
    if not matches:
        return []

    # 提取每个URL的上下文
    results = []

    for i, match in enumerate(matches):
        url = match["url"]
        index = match["index"]
        length = match["length"]

        # 计算上下文边界
        start_pos = max(0, index - context_window_size)
        end_pos = min(len(text), index + length + context_window_size)

        # 调整边界以避免与其他URL重叠
        if i > 0:
            prev_url = matches[i - 1]
            if start_pos < prev_url["index"] + prev_url["length"]:
                start_pos = prev_url["index"] + prev_url["length"]

        if i < len(matches) - 1:
            next_url = matches[i + 1]
            if end_pos > next_url["index"]:
                end_pos = next_url["index"]

        # 提取上下文
        before_text = text[start_pos:index]
        after_text = text[index + length : end_pos]

        # 组合成描述
        description = ""
        if before_text and after_text:
            description = f"{before_text.strip()} ... {after_text.strip()}"
        elif before_text:
            description = before_text.strip()
        elif after_text:
            description = after_text.strip()
        else:
            description = "No context available"

        # 清理描述
        description = re.sub(r"\s+", " ", description).strip()

        results.append(
            SearchSnippet(
                url=url, description=description, title=""  # 保持title字段为空
            )
        )

    return results


if __name__ == "__main__":
    # 测试URL样本
    test_urls = [
        "https://www.python.org/",
        "https://github.com/python/cpython",
        "https://en.wikipedia.org/wiki/Python_(programming_language)",
        "https://docs.python.org/3/tutorial/",
        "https://nonexistentwebsite123456789.com/",  # 不存在的网站，测试错误处理
    ]

    # 运行异步测试函数
    async def run_tests():
        print("开始测试get_last_modified函数...")

        # 为测试创建简单的令牌跟踪器
        tracker_context = TrackerContext(
            token_tracker=TokenTracker(),
            action_tracker=ActionTracker(),
        )

        for i, url in enumerate(test_urls):
            print(f"\n测试 {i+1}: {url}")

            try:
                result = await get_last_modified(url)
                if result:
                    print(f"最后修改日期: {result}")
                else:
                    print("未能获取最后修改日期")
            except Exception as e:
                print(f"测试出错: {e}")

        print("\n测试完成")

    # 运行测试
    asyncio.run(run_tests())
