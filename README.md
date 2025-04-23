# DeepResearch

DeepResearch是一个高级研究助手代理，能够帮助您搜索网络、分析信息并回答复杂问题。本项目是[Jina AI的node-DeepResearch](https://github.com/jina-ai/node-DeepResearch)的Python实现版本。

## 项目介绍

DeepResearch是一个基于Python的Deep Research 系统，它是Jina AI原始Node.js版本DeepResearch的Python实现。与原始版本一样，把问题抽象成在一个 loop 中由 llm 执行以下四个动作之一，不断循环，直到得到最终满意的答案：
- Search（搜索）
- Visit（阅读）
- Reflect（反思）
- Answer（回答）

## 项目结构

项目的主要目录结构如下：

```
deepresearch/
├── tools/            # API请求和专业工具函数
│   ├── jina_search.py        # Jina搜索API集成
│   ├── jina_read.py          # 网页内容读取与处理
│   ├── jina_rerank.py        # 搜索结果重排序
│   ├── jina_dedup.py         # 重复内容去除
│   ├── jina_embedding.py     # 文本向量嵌入
│   ├── jina_classify_spam.py # 垃圾内容分类
│   ├── jina_latechunk.py     # 长文本处理
│   ├── query_rewriter.py     # 查询重写优化
│   ├── evaluator.py          # 答案质量评估
│   ├── error_analyzer.py     # 错误分析与诊断
│   ├── code_sandbox.py       # 代码安全执行环境
│   ├── broken_ch_fixer.py    # 中文文本修复
│   └── md_fixer.py           # Markdown格式修复
├── utils/            # 通用工具函数
│   ├── url_tools.py          # URL处理工具
│   ├── text_tools.py         # 文本处理工具
│   ├── token_tracker.py      # 令牌使用追踪
│   ├── date_tools.py         # 日期时间工具
│   ├── action_tracker.py     # 代理动作追踪
│   ├── safe_generator.py     # 安全内容生成
│   ├── schemas.py            # 数据模式定义
│   └── i18n.json             # 国际化翻译数据
├── agent.py          # 核心代理逻辑
├── config.py         # 配置管理
├── model_types.py    # 类型定义
├── prompt_template.py # 中文提示模板
└── prompt_template_en.py # 英文提示模板
```

# 运行方法

## 配置调用llm和jina api的key

创建一个`.env`文件在deepresearch目录中，或者修改现有的，添加必要的API密钥：
```
OPENAI_API_KEY=your_openai_api_key
JINA_API_KEY=your_jina_api_key
```

## 使用方法

使用命令行运行DeepResearch：

```bash
python run_agent.py "你的问题或研究主题"
```

例如：
```bash
python run_agent.py "京东为什么要做外卖？它到底能如何利用现有优势来挑战美团的老大地位？"
```
