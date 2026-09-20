# CLAUDE.md — docsentry 项目上下文

本文件供 Claude Code 及其他协作者了解项目约定。**改动核心设计前请先读设计文档。**

## 项目是什么

`docsentry` 是一个面向工程师的开发者支持 Agent：帮开发者查 API 用法、排查配置问题、做跨版本迁移咨询。

**真正研究的命题**：

> 当语料是"模型训练数据里没有的内容"时，检索系统该怎么做才能答对？

时效性和私有语料是同一问题的两种表现——对模型而言，"刚发布的新文档"和"公司内部文档"都是知识盲区。

语料是 MCP 与 LangGraph 的官方文档。它是**实验载体**（公开、干净、可复现），不是项目价值本身。

## 设计文档（唯一权威来源）

`docs/superpowers/specs/2026-09-18-docsentry-design.md`

架构、模块设计、实验设计、数据模型、已知限制都在里面。**本文只记录约定和速查，冲突时以设计文档为准。**

## 技术栈

Python 3.11+ · uv · Pydantic Settings · Typer · pytest

| 组件 | 选型 |
|---|---|
| Embedding | `BAAI/bge-m3`（本地，batch=16） |
| Reranker | `BAAI/bge-reranker-v2-m3`（本地） |
| 向量库 | Qdrant local mode（`path=./data/qdrant`） |
| 稀疏检索 | `rank_bm25` + jieba |
| Markdown 解析 | `markdown-it-py` |
| 编排 | LangGraph |
| LLM | 云端 OpenAI 兼容 API（`OPENAI_BASE_URL` 可指向 DeepSeek / Qwen），支持切本地 Ollama |

## 必须遵守的约定

这几条是实现时最容易做错的地方，**改动前先确认**：

1. **框架分层使用**
   - ✅ 编排层用 LangGraph（状态管理、条件分支是配置问题）
   - ❌ 切片 / 检索融合 / 评测**必须自研**——它们是实验变量，必须完全可控才能做消融
   - 项目**不 import** `langchain` / `llama_index`

2. **切片公平性约束**
   - 三种切片策略共享同一 `target_size`（默认 1000 字符）
   - **差异只体现在"切在哪里"，不是"切多大"**——否则实验结论无法归因
   - 评测报告必须公布各策略的平均 chunk 尺寸与数量

3. **增量更新必须"先插后删"**
   ```
   ① 新内容切片 → upsert 新 chunk
   ② 按 doc_id 查出全部 chunk_id
   ③ 删除「不在新 chunk_id 集合中」的旧 chunk
   ```
   - 顺序反了会在删除成功、插入失败时**留下无人知晓的索引空洞**
   - 只 upsert 不删除会**留下孤儿 chunk**（文档变短时旧 chunk 仍被检索命中）

4. **不做常驻文件监控**（watchdog 等）
   - 索引是定期/手动触发的批处理，每次重扫目录即可
   - "上传产生快照"是时效性的敌人；正解是**注册数据源**（系统持指针，索引时重读）

5. **生成时 prompt 必须带 `breadcrumb` + `version` + `indexed_at`**
   - 不只给 chunk 文本——这是本项目的核心假设，也是评测要验证的变量
   - `temperature=0`（评测可复现性）

6. **评测集是人工筛过的**
   - 可以用 LLM 生成候选，但筛选与答案校准**必须人工做过**
   - 明确禁止"全自动生成 + 全自动评判"的闭环

7. **`uv.lock` 必须提交，不要加进 `.gitignore`**
   - `pyproject.toml` 写**范围**（`httpx>=0.27`），`uv.lock` 锁**结果**（`httpx==0.28.1`），
     且包含全部间接依赖与哈希
   - **lockfile 不是构建产物**：`node_modules` 要忽略，`uv.lock` 要提交
     （同类：`package-lock.json` / `poetry.lock` / `Cargo.lock`）
   - 本项目尤其不能忽略：核心叙事是**可复现**——评测数字必须能在别人机器上跑出来。
     依赖版本一漂，跑出的准确率就和仓库里记录的对不上，实验可信度直接崩
   - 由 `uv sync` 自动维护，**不要手改**；改了依赖就确认 `uv.lock` 有变更并一起提交
   - ⚠️ **它锁不住模型权重**：`bge-m3` / `bge-reranker-v2-m3` 从 HuggingFace 单独下载，
     不在依赖树里。要真正可复现，M3 加载时须钉住 `revision`，光有 `uv.lock` 是不够的

## 语料层已实测的细节（省得重查）

- `modelcontextprotocol.io/llms.txt` 是**平铺列表**，链接直达 `.md` 文件；URL 路径自带版本（`/docs/2026-07-28/`）
- `docs.langchain.com/llms.txt` 是**层级索引**，指向子 `llms.txt`——解析器需支持**递归展开**（最多 2 层，防环）
- MCP 文档站**无 ETag**；`Last-Modified` 是站点构建时间，**不可靠**
  → **`content_hash` 是唯一可靠的变更判据**，必须全量下载比对（成本可忽略：单页约 3 KB × 400 页 ≈ 1.2 MB）

## 常用命令

```bash
uv sync                                       # 安装依赖
uv run scripts/fetch_corpus.py --update       # 抓取/增量更新语料
uv run scripts/build_index.py                 # 建索引
uv run cli.py ask "怎么注册一个 MCP tool"      # 提问
uv run scripts/run_eval.py --strategy structural --mode agent
uv run pytest                                 # 测试
```

## 进度

见 `README.md` 的 Progress 清单。当前处于**实现阶段**（设计已完成并评审通过）。

## 工期不足时的砍功能顺序

严格按序，从下往上砍：

1. 选做四项（PDF / 图片 caption / UI / `LocalDirectorySource`）
2. `rerank`（降级纯 RRF）
3. `BM25`（降级纯向量）
4. 时效性三组对比（保留 A/C，砍 B 组）
5. agent 编排（降级 pipeline）
6. 评测集 50 → 30 题

**核心切片实验最后砍。** 它在，项目就完整；它没了，项目就废了。
