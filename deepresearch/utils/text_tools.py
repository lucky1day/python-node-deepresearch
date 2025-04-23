"""
文本工具函数
"""
import json
import os
import re
import random
from typing import Dict, List, Any, Optional, Union
from ..model_types import AnswerAction, KnowledgeItem, Reference
from html.parser import HTMLParser
from io import StringIO


def load_i18n_data():
    """
    加载i18n数据
    
    Returns:
        i18n数据字典
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    i18n_path = os.path.join(current_dir, 'i18n.json')
    
    try:
        with open(i18n_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        # 如果文件不存在，返回空字典
        return {"en": {}}


# 加载i18n数据
i18n_data = load_i18n_data()


def get_i18n_text(key: str, lang='en', params: Dict[str, str] = {}) -> str:
    """
    获取国际化文本
    
    Args:
        key: 文本键名
        lang: 语言代码
        params: 参数字典
        
    Returns:
        国际化文本
    """
    # 确保语言代码存在，如果不存在则使用英语作为后备
    if lang not in i18n_data:
        print(f"Language '{lang}' not found, falling back to English.")
        lang = 'en'
    
    # 获取对应语言的文本
    try:
        text = i18n_data[lang][key]
    except KeyError:
        # 如果文本不存在，则使用英语作为后备
        print(f"Key '{key}' not found for language '{lang}', falling back to English.")
        
        try:
            text = i18n_data['en'][key]
        except KeyError:
            # 如果英语版本也不存在，则返回键名
            print(f"Key '{key}' not found for English either.")
            return key
    
    # 替换模板中的变量
    if params:
        for param_key, param_value in params.items():
            text = text.replace(f"${{{param_key}}}", param_value)
    
    return text


def remove_html_tags(text: str) -> str:
    """
    移除HTML标签
    
    Args:
        text: 输入文本
        
    Returns:
        移除HTML标签后的文本
    """
    return re.sub(r'<[^>]*>?', '', text)


def remove_all_line_breaks(text: str) -> str:
    """
    移除所有换行符
    
    Args:
        text: 输入文本
        
    Returns:
        移除换行符后的文本
    """
    return re.sub(r'(\r\n|\n|\r)', ' ', text)


def remove_extra_line_breaks(text: str) -> str:
    """
    移除多余的换行符，将多个连续换行符替换为两个
    
    Args:
        text: 输入文本
        
    Returns:
        处理后的文本
    """
    return re.sub(r'\n{2,}', '\n\n', text)


def build_md_from_answer(answer: AnswerAction) -> str:
    """
    从回答构建Markdown文本
    
    Args:
        answer: 回答动作
        
    Returns:
        Markdown文本
    """
    return repair_markdown_footnotes(answer.answer, answer.references)


def repair_markdown_footnotes(markdown_string: str, references: Optional[List[Reference]] = []) -> str:
    """
    修复Markdown脚注
    
    Args:
        markdown_string: Markdown文本
        references: 引用列表
        
    Returns:
        修复后的Markdown文本
    """
    # 标准脚注正则表达式 - 处理 [^1], [1^], 和 [1] 格式
    footnote_regex = r'\[(\^(\d+)|(\d+)\^|(\d+))]'
    
    # 如果没有引用，移除所有脚注引用
    if not references:
        return re.sub(footnote_regex, '', markdown_string)
    
    # 格式化引用函数
    def format_references(refs: List[Reference]) -> str:
        result = []
        for i, ref in enumerate(refs):
            clean_quote = re.sub(r'[^\w\s]', ' ', ref.exact_quote)
            clean_quote = re.sub(r'\s+', ' ', clean_quote).strip()
            
            citation = f"[^{i + 1}]: {clean_quote}"
            
            if hasattr(ref, 'url') and ref.url:
                try:
                    from urllib.parse import urlparse
                    domain_name = urlparse(ref.url).netloc.replace('www.', '')
                    title = getattr(ref, 'title', domain_name)
                    citation += f" [{title}]({ref.url})"
                except:
                    pass
                
            result.append(citation)
        
        return '\n\n'.join(result)
    
    # 标准化脚注 (将 [1^] 转换为 [^1] 格式，将 [1] 转换为 [^1] 格式)
    processed_markdown = re.sub(r'\[(\d+)\^]', lambda m: f"[^{m.group(1)}]", markdown_string)
    processed_markdown = re.sub(r'\[(\d+)]', lambda m: f"[^{m.group(1)}]", processed_markdown)
    
    # 提取所有脚注
    footnotes = []
    standard_footnote_regex = r'\[\^(\d+)]'
    for match in re.finditer(standard_footnote_regex, processed_markdown):
        footnotes.append(match.group(1))
    
    # 如果没有脚注但有引用，将引用附加到末尾
    if not footnotes:
        appended_citations = ''.join([f"[^{i + 1}]" for i in range(len(references))])
        formatted_references = format_references(references)
        
        return f"""
{processed_markdown}

⁜{appended_citations}

{formatted_references}
""".strip()
    
    # 更新内容和引用
    return f"""
{processed_markdown}

{format_references(references)}
""".strip()


def smart_merge_strings(str1: str, str2: str) -> str:
    """
    智能合并两个字符串
    
    Args:
        str1: 第一个字符串
        str2: 第二个字符串
        
    Returns:
        合并后的字符串
    """
    # 如果任一字符串为空，返回另一个
    if not str1:
        return str2
    if not str2:
        return str1
    
    # 检查一个字符串是否完全包含另一个
    if str1 in str2:
        return str2
    if str2 in str1:
        return str1
    
    # 找到可能的最大重叠长度
    max_overlap = min(len(str1), len(str2))
    best_overlap_length = 0
    
    # 从最大可能重叠开始检查
    for overlap_length in range(max_overlap, 0, -1):
        # 获取第一个字符串的结尾部分
        end_of_str1 = str1[len(str1) - overlap_length:]
        # 获取第二个字符串的开头部分
        start_of_str2 = str2[:overlap_length]
        
        # 如果匹配，我们找到了重叠部分
        if end_of_str1 == start_of_str2:
            best_overlap_length = overlap_length
            break
    
    # 使用最佳重叠合并字符串
    if best_overlap_length > 0:
        return str1[:len(str1) - best_overlap_length] + str2
    else:
        # 没有找到重叠，正常连接
        return str1 + str2


def choose_k(a: List[str], k: int) -> List[str]:
    """
    从列表中随机抽取k个元素（不重复）
    
    Args:
        a: 输入列表
        k: 要抽取的元素数量
        
    Returns:
        抽取的元素列表
    """
    items = a.copy()
    random.shuffle(items)
    
    return items[:k]


def fix_code_block_indentation(markdown_text: str) -> str:
    """
    修复Markdown代码块中的缩进问题
    
    Args:
        markdown_text: Markdown文本
        
    Returns:
        修复后的Markdown文本
    """
    # 跟踪代码块状态及其缩进
    lines = markdown_text.split('\n')
    result = []
    
    # 跟踪开放的代码块及其缩进
    code_block_stack = []
    
    for i in range(len(lines)):
        line = lines[i]
        
        # 检查行是否可能包含代码围栏标记
        if line.lstrip().startswith('```'):
            # 获取缩进
            indent = line[:line.find('```')]
            rest_of_line = line.lstrip()[3:].strip()
            
            if not code_block_stack:
                # 这是开放的代码围栏
                
                # 通过查看前几行确定是否在列表上下文中
                list_indent = ""
                if i > 0:
                    # 向上查找最多3行以查找列表标记
                    for j in range(i - 1, max(0, i - 3) - 1, -1):
                        prev_line = lines[j]
                        # 检查列表标记，如*，-，1.等
                        if re.match(r'^\s*(?:[*\-+]|\d+\.)\s', prev_line):
                            # 提取列表的基本缩进
                            match = re.match(r'^(\s*)', prev_line)
                            if match:
                                list_indent = match.group(1)
                                break
                
                code_block_stack.append({
                    'indent': indent, 
                    'language': rest_of_line, 
                    'list_indent': list_indent
                })
                result.append(line)
            else:
                # 这是关闭的代码围栏
                opening_block = code_block_stack.pop()
                
                if opening_block:
                    # 用开放围栏的缩进替换
                    result.append(f"{opening_block['indent']}```")
                else:
                    # 出错了，保持原样
                    result.append(line)
        elif code_block_stack:
            # 在代码块内部 - 处理缩进
            opening_block = code_block_stack[-1]
            
            if line.strip():
                # 计算代码块的适当基本缩进
                if opening_block['list_indent']:
                    # 列表中的代码块
                    base_indent = opening_block['list_indent'] + "    "
                else:
                    # 不在列表中
                    base_indent = opening_block['indent']
                
                # 获取此特定行的缩进
                line_indent_match = re.match(r'^(\s*)', line)
                line_indent = line_indent_match.group(0) if line_indent_match else ''
                
                # 查找行缩进和开放块缩进之间的共同前缀
                # 这表示由于markdown结构而产生的缩进部分
                common_prefix = ''
                min_length = min(len(line_indent), len(opening_block['indent']))
                for i in range(min_length):
                    if line_indent[i] == opening_block['indent'][i]:
                        common_prefix += line_indent[i]
                    else:
                        break
                
                # 只删除共同前缀（markdown结构缩进）
                # 并保留其余部分（代码自身的缩进）
                content_after_common_indent = line[len(common_prefix):]
                
                # 添加适当的基本缩进加上保留的代码缩进
                result.append(f"{base_indent}{content_after_common_indent}")
            else:
                # 对于空行，保持原样
                result.append(line)
        else:
            # 不在代码块中，保持原样
            result.append(line)
    
    return '\n'.join(result)


def get_knowledge_str(all_knowledge: List['KnowledgeItem']) -> str:
    """
    将知识项列表转换为格式化字符串
    
    Args:
        all_knowledge: 知识项列表
        
    Returns:
        格式化的知识字符串
    """
    knowledge_strings = []
    
    for idx, k in enumerate(all_knowledge):
        msg = f"<knowledge-{idx + 1}>\n{k.question}\n\n"
        
        # 添加日期时间（如果有）
        if getattr(k, 'updated', None) and (getattr(k, 'type', None) == 'url' or getattr(k, 'type', None) == 'side-info'):
            msg += f"<knowledge-datetime>\n{k.updated}\n</knowledge-datetime>\n\n"
        
        # 添加URL（如果有）
        if getattr(k, 'references', None) and getattr(k, 'type', None) == 'url':
            msg += f"<knowledge-url>\n{k.references[0]}\n</knowledge-url>\n\n\n"
        
        # 添加答案
        msg += f"{k.answer}\n</knowledge-{idx + 1}>"
        
        knowledge_strings.append(remove_extra_line_breaks(msg))
    
    return "\n\n".join(knowledge_strings)


class HTMLTableParser(HTMLParser):
    """
    HTML表格解析器类，用于将HTML表格转换为Markdown格式
    """
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_thead = False
        self.in_tbody = False
        self.in_tr = False
        self.in_th = False
        self.in_td = False
        self.current_cell = StringIO()
        self.rows = []
        self.current_row = []
        self.headers = []

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.in_table = True
        elif tag == 'thead':
            self.in_thead = True
        elif tag == 'tbody':
            self.in_tbody = True
        elif tag == 'tr':
            self.in_tr = True
            self.current_row = []
        elif tag == 'th':
            self.in_th = True
            self.current_cell = StringIO()
        elif tag == 'td':
            self.in_td = True
            self.current_cell = StringIO()
        elif tag in ['strong', 'b'] and (self.in_td or self.in_th):
            self.current_cell.write('**')
        elif tag in ['em', 'i'] and (self.in_td or self.in_th):
            self.current_cell.write('_')
        elif tag == 'br' and (self.in_td or self.in_th):
            self.current_cell.write('<br>')
        elif tag == 'li' and (self.in_td or self.in_th):
            self.current_cell.write('• ')

    def handle_endtag(self, tag):
        if tag == 'table':
            self.in_table = False
        elif tag == 'thead':
            self.in_thead = False
        elif tag == 'tbody':
            self.in_tbody = False
        elif tag == 'tr':
            self.in_tr = False
            if self.in_thead or (not self.headers and not self.rows):
                # 如果是表头行或者还没有表头但有行
                self.headers = self.current_row
            else:
                self.rows.append(self.current_row)
        elif tag == 'th':
            self.in_th = False
            cell_content = self.current_cell.getvalue()
            self.current_row.append(sanitize_cell(cell_content))
        elif tag == 'td':
            self.in_td = False
            cell_content = self.current_cell.getvalue()
            self.current_row.append(sanitize_cell(cell_content))
        elif tag in ['strong', 'b'] and (self.in_td or self.in_th):
            self.current_cell.write('**')
        elif tag in ['em', 'i'] and (self.in_td or self.in_th):
            self.current_cell.write('_')
        elif tag == 'p' and (self.in_td or self.in_th):
            self.current_cell.write('<br>')

    def handle_data(self, data):
        if self.in_td or self.in_th:
            self.current_cell.write(data)


def sanitize_cell(content: str) -> str:
    """
    对单元格内容进行清理，以便在Markdown表格中使用
    
    Args:
        content: 单元格内容
        
    Returns:
        清理后的内容
    """
    # 清理空白
    sanitized = content.strip()
    
    # 规范化内容中的管道字符（转义它们）
    sanitized = sanitized.replace('|', '\\|')
    
    # 保持换行符
    sanitized = sanitized.replace('\n', '<br>')
    
    # 保持现有的<br>标签完整（不要转义它们）
    sanitized = sanitized.replace('&lt;br&gt;', '<br>')
    
    # 保持Markdown格式
    sanitized = (sanitized
        .replace('\\*\\*', '**')  # 修复转义的粗体标记
        .replace('\\*', '*')      # 修复转义的列表标记
        .replace('\\_', '_'))     # 修复转义的斜体标记
    
    return sanitized


def convert_single_html_table_to_md(html_table: str) -> str:
    """
    将单个HTML表格转换为Markdown表格
    
    Args:
        html_table: HTML表格字符串
        
    Returns:
        Markdown表格字符串，如果转换失败则返回None
    """
    try:
        parser = HTMLTableParser()
        parser.feed(html_table)
        
        # 如果没有表头，使用第一行
        if not parser.headers and parser.rows:
            parser.headers = parser.rows[0]
            parser.rows = parser.rows[1:]
        
        # 如果没有表头，无法创建有效的Markdown表格
        if not parser.headers:
            return None
        
        # 开始构建Markdown表格
        md_table = ''
        
        # 添加表头行
        md_table += '| ' + ' | '.join(parser.headers) + ' |\n'
        
        # 添加分隔行
        md_table += '| ' + ' | '.join(['---'] * len(parser.headers)) + ' |\n'
        
        # 添加数据行
        for row in parser.rows:
            # 确保每行的单元格数量与表头相同
            cells = row.copy()
            while len(cells) < len(parser.headers):
                cells.append('')
                
            md_table += '| ' + ' | '.join(cells) + ' |\n'
        
        return md_table
    except Exception as error:
        print('转换单个HTML表格时出错:', error)
        return None


def convert_html_tables_to_md(md_string: str) -> str:
    """
    将Markdown字符串中的HTML表格转换为Markdown表格
    
    Args:
        md_string: 包含潜在HTML表格的Markdown字符串
        
    Returns:
        HTML表格转换为Markdown表格的Markdown字符串，如果没有进行转换则返回原始字符串
    """
    try:
        result = md_string
        
        # 首先检查HTML表格
        if '<table>' in md_string:
            # 用于查找HTML表格的正则表达式
            table_regex = re.compile(r'<table>([\s\S]*?)<\/table>')
            
            # 处理找到的每个表格
            for match in table_regex.finditer(md_string):
                html_table = match.group(0)
                converted_table = convert_single_html_table_to_md(html_table)
                
                if converted_table:
                    result = result.replace(html_table, converted_table)
        
        return result
    except Exception as error:
        print('将HTML表格转换为Markdown时出错:', error)
        return md_string  # 如果转换失败，则返回原始字符串


def repair_markdown_final(markdown: str) -> str:
    """
    修复Markdown，包括：
    1. 移除不在表格内的<hr>和<br>标签
    2. 将冒号移到粗体和斜体格式之外
    
    Args:
        markdown: 要修复的Markdown字符串
        
    Returns:
        修复后的Markdown，如果出错则返回原始内容
    """
    try:
        repaired_markdown = markdown
        
        # 移除任何''
        repaired_markdown = repaired_markdown.replace('', '')
        
        # 步骤1：处理表格外的<hr>和<br>标签
        
        # 首先，识别表格区域以将它们排除在替换之外
        table_regions = []
        
        # 查找HTML表格
        html_table_regex = re.compile(r'<table[\s\S]*?<\/table>')
        for match in html_table_regex.finditer(repaired_markdown):
            table_regions.append((match.start(), match.end()))
        
        # 查找Markdown表格
        lines = repaired_markdown.split('\n')
        in_markdown_table = False
        markdown_table_start = 0
        
        for i, line in enumerate(lines):
            line = line.strip()
            
            if line.startswith('|') and '|' in line[1:]:
                if not in_markdown_table:
                    in_markdown_table = True
                    markdown_table_start = repaired_markdown.find(lines[i])
            elif in_markdown_table and line == '':
                in_markdown_table = False
                table_end = repaired_markdown.find(lines[i-1]) + len(lines[i-1])
                table_regions.append((markdown_table_start, table_end))
        
        if in_markdown_table:
            table_end = len(repaired_markdown)
            table_regions.append((markdown_table_start, table_end))
        
        # 检查索引是否在任何表格区域内
        def is_in_table(index):
            return any(start <= index < end for start, end in table_regions)
        
        # 移除表格外的<hr>和<br>标签
        result = ''
        i = 0
        
        while i < len(repaired_markdown):
            if (repaired_markdown[i:i+4] == '<hr>' and not is_in_table(i)):
                i += 4
            elif (repaired_markdown[i:i+4] == '<br>' and not is_in_table(i)):
                i += 4
            else:
                result += repaired_markdown[i]
                i += 1
        
        repaired_markdown = result
        
        # 步骤2：修复带有冒号的格式
        # 从最具体（最长）模式到最一般的模式处理
        formatting_patterns = [
            ('****', '****'),  # 四个星号
            ('****', '***'),   # 四个开头，三个结尾
            ('***', '****'),   # 三个开头，四个结尾
            ('***', '***'),    # 三个星号
            ('**', '**'),      # 两个星号（粗体）
            ('*', '*')         # 一个星号（斜体）
        ]
        
        for open_marker, close_marker in formatting_patterns:
            repaired_markdown = process_formatted_text(repaired_markdown, open_marker, close_marker)
        
        return repaired_markdown
    except Exception as error:
        print('修复Markdown时出错:', error)
        # 如果出现任何错误，则返回原始Markdown
        return markdown


def process_formatted_text(text: str, open_marker: str, close_marker: str) -> str:
    """
    处理格式化文本并将冒号移到格式标记之外
    
    Args:
        text: 要处理的文本
        open_marker: 开始格式标记
        close_marker: 结束格式标记
        
    Returns:
        处理后的文本
    """
    # 转义特殊的正则表达式字符
    escaped_open = re.escape(open_marker)
    escaped_close = re.escape(close_marker)
    
    # 创建模式
    pattern = re.compile(f'{escaped_open}(.*?){escaped_close}')
    
    def replace_func(match):
        content = match.group(1)
        
        # 检查内容是否包含冒号
        if ':' in content or '：' in content:
            # 计算冒号数量
            standard_colon_count = content.count(':')
            wide_colon_count = content.count('：')
            
            # 移除冒号并清理内容
            trimmed_content = re.sub(r'[:：]', '', content).strip()
            
            # 在格式外添加冒号
            standard_colons = ':' * standard_colon_count
            wide_colons = '：' * wide_colon_count
            
            return f'{open_marker}{trimmed_content}{close_marker}{standard_colons}{wide_colons}'
        
        return match.group(0)
    
    return pattern.sub(replace_func, text)


def escape_regex(string: str) -> str:
    """
    转义字符串中的特殊正则表达式字符
    
    Args:
        string: 要转义的字符串
        
    Returns:
        转义后的字符串
    """
    return re.escape(string)


def count_char(text: str, char: str) -> int:
    """
    计算字符串中特定字符的出现次数
    
    Args:
        text: 要搜索的文本
        char: 要计数的字符
        
    Returns:
        字符出现的次数
    """
    return text.count(char)


def repair_markdown_footnotes_outer(markdown_string: str) -> str:
    """
    修复Markdown脚注的外部变体，只需要Markdown字符串
    它提取现有的脚注定义并将它们用作引用
    
    Args:
        markdown_string: Markdown文本
        
    Returns:
        修复后的Markdown文本
    """
    # 首先清理字符串以处理任何额外的空白
    markdown_string = markdown_string.strip()
    
    # 解开文档中的所有代码围栏
    # 匹配```markdown或```html和结束```之间的任何内容
    code_block_regex = re.compile(r'```(markdown|html)\n([\s\S]*?)\n```')
    processed_string = markdown_string
    
    for match in code_block_regex.finditer(markdown_string):
        entire_match = match.group(0)
        code_content = match.group(2)
        processed_string = processed_string.replace(entire_match, code_content)
    
    markdown_string = processed_string
    
    # 提取现有的脚注定义
    footnote_def_regex = re.compile(r'\[\^(\d+)]:\s*(.*?)(?=\n\[\^|$)', re.DOTALL)
    references = []
    
    # 提取内容部分（不带脚注定义）
    content_part = markdown_string
    footnotes_part = ''
    
    # 尝试找到脚注定义开始的位置
    first_footnote_match = re.search(r'\[\^(\d+)]:', markdown_string)
    if first_footnote_match:
        footnote_start_index = first_footnote_match.start()
        content_part = markdown_string[:footnote_start_index]
        footnotes_part = markdown_string[footnote_start_index:]
    
    # 提取所有脚注定义
    for match in footnote_def_regex.finditer(footnotes_part):
        # 脚注内容
        content = match.group(2).strip()
        
        # 提取URL和标题（如果存在）
        # 查找content末尾的[domain.com](url)模式
        url_match = re.search(r'\s*\[([^\]]+)]\(([^)]+)\)\s*$', content)
        
        url = ''
        title = ''
        
        if url_match:
            # 提取域名作为标题
            title = url_match.group(1)
            # 提取URL
            url = url_match.group(2)
            
            # 从内容中删除URL部分以获得干净的exactQuote
            content = content.replace(url_match.group(0), '').strip()
        
        # 添加到引用数组
        references.append({
            'exact_quote': content,
            'url': url,
            'title': title
        })
    
    # 只有当我们找到有效的引用时才处理
    if references:
        return repair_markdown_footnotes(content_part, references)
    
    # 否则，返回未更改的原始markdown
    return markdown_string


async def detect_broken_unicode_via_file_io(str_text: str) -> dict:
    """
    通过文件IO检测字符串中是否存在破损的Unicode字符
    这个函数会将字符串写入临时文件，然后再读出来，以检测破损的Unicode
    
    Args:
        str_text: 要检查的字符串
        
    Returns:
        包含broken和readStr的字典，broken表示是否检测到破损字符，readStr是读取后的字符串
    """
    import os
    import tempfile
    import time
    import random
    import string
    import asyncio
    from pathlib import Path
    
    # 创建一个使用时间戳和随机字符串的临时文件名
    timestamp = int(time.time() * 1000)
    random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    temp_file_path = Path(tempfile.gettempdir()) / f"temp_unicode_check_{timestamp}_{random_str}.txt"
    
    try:
        # 将字符串写入文件（强制编码/解码）
        with open(temp_file_path, 'w', encoding='utf-8') as f:
            f.write(str_text)
        
        # 读回来
        with open(temp_file_path, 'r', encoding='utf-8') as f:
            read_str = f.read()
        
        # 清理
        os.unlink(temp_file_path)
        
        # 检查是否包含可见的替换字符（Unicode 替换字符 U+FFFD）
        return {"broken": '\uFFFD' in read_str, "read_str": read_str}
    except Exception as error:
        # 确保临时文件被删除
        if temp_file_path.exists():
            os.unlink(temp_file_path)
        print(f"检测Unicode时出错: {error}")
        # 如果出错，假设没有破损
        return {"broken": False, "read_str": str_text} 