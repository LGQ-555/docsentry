# 技术文档问答 Agent — 设计文档

- 日期：2026-09-18
- 状态：待评审
- 目标：校招/实习简历项目 + 学习 Agent 工程实践
- 工期：14 天

---

## 1. 项目概述

### 1.1 要解决的问题

技术文档问答对通用 RAG 有两个失效模式：

1. **切片切坏**——固定长度切分会把代码块拦腰截断、丢掉标题层级。检索到的 chunk 是"设置 timeout 为 30 秒"，但没有上下文说明这说的是哪个类、哪个版本。
2. **版本混淆**——技术文档 API 迭代快，语料里混着多个版本的内容。用户问新版写法，检索命中的是两年前的旧 API，模型据此编出已经废弃的用法。

### 1.2 项目做什么

构建一个面向技术文档的问答 Agent，语料来自主流 Agent/AI 框架的官方文档，核心差异化在**切片层**和**版本感知**：

- 按 Markdown 标题层级切片，保留 breadcrumb 元数据，代码块作为原子单元不切断
- 每个 chunk 携带文档版本元数据，回答时标注 API 版本
- 用同一套评测集对比三种切片策略，产出可复现的数字

### 1.3 为什么这个选题适合简历

- **可现场验证**：面试官就是这些文档的用户，能当场提问验证效果
- **有数字可写**：三种切片策略在 50 题评测集上的对比，每个数字都可追溯到实验
- **差异化明确**：市面上文档问答项目多，但绝大多数用固定长度切片，讲不出切片策略的取舍
- **痛点真实**：开发者天天遇到"搜到旧版本文档"的问题

### 1.4 语料来源（已验证）

| 源 | llms.txt | 形态 | 版本信息 |
|---|---|---|---|
| MCP | `https://modelcontextprotocol.io/llms.txt` | 平铺列表，链接指向 `.md` | ✅ URL 路径自带，如 `/docs/2026-07-28/` |
| LangGraph / LangChain | `https://docs.langchain.com/llms.txt` | **层级索引**，指向子 `llms.txt` | 需从页面内容或路径提取 |

已实测：`https://docs.langchain.com/oss/python/langgraph/overview.md` → HTTP 200，`Content-Type: text/markdown`，内容为干净 Markdown。

`llms.txt` 是 2024 年起兴起的标准，为 LLM 提供文档索引。它链接的是 `.md` 源文件而非 HTML，因此无需 HTML 清洗，切片质量天然更高。

---

## 2. 验收标准

两周结束时必须交付：

1. CLI 能回答 MCP + LangGraph 文档的问题，答案带来源链接和版本标注
2. 三种切片策略（fixed / semantic / structural）在同一 50 题评测集上的对比表
3. README 含架构图、实验数据表、失败案例分析
4. 2 分钟可演示，面试官可现场提问
5. 简历条目 + 面试问答准备材料（每个数字都能说清来源）

---

## 3. 技术选型（已确定）

| 组件 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.11+ | 生态最全 |
| 包管理 | uv | 环境里已装（`F:\UV`），速度快 |
| Embedding | `BAAI/bge-m3`（本地） | 中英文均可，免费的本地方案 |
| Reranker | `BAAI/bge-reranker-v2-m3`（本地） | 与 embedding 同系列，效果匹配 |
| 向量库 | Qdrant（local mode） | 无需起服务，payload 过滤成熟，支持按版本过滤 |
| 稀疏检索 | `rank_bm25` + jieba 分词 | 纯 Python，几千 chunk 规模足够 |
| Markdown 解析 | `markdown-it-py` | CommonMark 合规，提供带位置的 token 流 |
| LLM（生成 + 评判） | 云端 OpenAI 兼容 API | 通过 `OPENAI_BASE_URL` 配置，可指向 DeepSeek / Qwen 等 |
| CLI | `typer` | 开发快，help 自动生成 |
| 配置 | `pydantic-settings` + `.env` | 类型安全 |
| 测试 | `pytest` | — |
| 报告 | `pandas` + Markdown 输出 | — |

**明确不使用**：LangChain / LangGraph / LlamaIndex 等重型框架。原因：核心逻辑（切片、检索、评测）必须自研才能在面试中讲清楚；框架会引入不可控的抽象层。

> 注意区分：LangGraph 在本项目中是**语料来源**（它的官方文档），不是运行时依赖。项目不 import 任何 langchain/langgraph 包。

---

## 4. 系统架构

### 4.1 模块划分

每个模块单一职责，通过明确定义的接口通信，可独立测试。

```
corpus/      文档抓取与语料管理   →  llms.txt 递归解析、.md 下载、版本提取、去重
chunking/    切片策略（核心）     →  统一接口 chunk(doc) -> list[Chunk]
indexing/    建索引              →  embedding + Qdrant upsert + BM25 索引
retrieval/   检索                →  双路召回 + RRF 融合 + rerank + 版本过滤
generation/  生成                →  prompt 组装 + 引用标注
evaluation/  评测                →  评测集管理、跑分、报告生成
```

### 4.2 数据流

```
sources.yaml
    ↓  fetch_corpus.py
data/raw/<source>/**.md          （原始 Markdown，按源分目录）
    ↓  解析 + 版本提取 + 去重
data/corpus.jsonl                （Document 列表，每行一个）
    ↓  build_index.py（调用 Chunker）
data/qdrant/                     （向量索引，payload 含完整 chunk 元数据）
data/bm25_<strategy>.pkl         （BM25 索引，每策略一份）
    ↓  cli.py ask "问题"
检索 → 融合 → rerank → 生成 → 带引用的答案
    ↓  run_eval.py
reports/eval-<chunker>-<ts>.md   （跑分报告）
```

### 4.3 核心接口

```python
# chunking/base.py
class Chunker(Protocol):
    name: str
    def chunk(self, doc: Document) -> list[Chunk]: ...

# retrieval/base.py
class Retriever(Protocol):
    def retrieve(self, query: str, k: int = 5, version: str | None = None) -> list[Chunk]: ...
```

三种 `Chunker` 实现同一接口，这是评测实验能一键切换的基础。

---

## 5. 数据模型

```python
# src/docqa/models.py

@dataclass
class Document:
    doc_id: str        # sha256(source + path)[:16]，稳定不变
    source: str        # "mcp" | "langgraph"
    version: str       # "2026-07-28"，无法提取时为 "unknown"
    url: str           # 原始页面的 .md URL
    title: str
    path: str          # 文档在站点内的路径
    content: str       # 原始 Markdown
    content_hash: str  # sha256(content)，用于增量更新

@dataclass
class Chunk:
    chunk_id: str          # sha256(doc_id + 序号 + 策略名)[:16]
    doc_id: str
    text: str
    breadcrumb: list[str]  # ["MCP", "Server Concepts", "Resources"]
    source: str
    version: str
    url: str
    kind: str              # "prose" | "code" | "table" | "mixed"
    strategy: str          # "fixed" | "semantic" | "structural"
    char_count: int
```

`breadcrumb` 和 `version` 是检索与生成阶段的关键上下文，必须落库到 Qdrant payload 支持过滤。

---

## 6. 模块详细设计

### 6.1 corpus — 抓取与语料管理

**配置**（`configs/sources.yaml`）：

```yaml
sources:
  - name: mcp
    llms_txt: https://modelcontextprotocol.io/llms.txt
    url_include: "/docs/"          # 只保留匹配的路径
  - name: langgraph
    llms_txt: https://docs.langchain.com/llms.txt
    url_include: "/oss/python/"    # 聚焦 LangGraph/LangChain OSS 部分
```

**llms.txt 解析**：

1. 下载 `llms.txt`
2. 解析行格式 `- [title](url): description`
3. **若条目 URL 以 `llms.txt` 结尾，视为子索引，递归展开**（`docs.langchain.com` 就是这样，最多 2 层，用已访问 URL 集合防环）
4. 其余条目若以 `.md` 结尾则收集；若以 `/` 结尾视为目录项，跳过

**下载**：并发 8 路，每篇超时 15s，失败重试 2 次，失败的 URL 记入 `data/fetch_failures.txt` 不中断整体流程。

**版本提取**（按优先级）：

1. URL 路径正则：`/docs/(\d{4}-\d{2}-\d{2})/` → 取日期（MCP 命中）
2. 页面 front-matter 或正文中的 `version` / `Version` 字段
3. 配置里的 `default_version`
4. 兜底 `"unknown"`

**去重**：`content_hash` 相同视为同一内容。同一 URL 重复抓取时，若 hash 未变则跳过（支持增量更新）。

**输出**：`data/corpus.jsonl`，每行一个 `Document`。

**验收**：两个源合计落地 ≥ 400 篇 `.md`，其中 MCP 的 version 字段非 `unknown` 的比例 ≥ 90%。

### 6.2 chunking — 切片策略（核心）

三种实现，同一接口。

**公平性约束（实验有效性的前提）**：三种策略共享同一个目标尺寸配置 `target_size`（默认 1000 字符，定义在 `configs/chunking.yaml`）。三者都朝这个尺寸努力，差异只体现在**切在哪里**，而非切多大。这是对比实验成立的前提——若尺寸不同，准确率差异无法归因于切片策略。

允许的例外：`structural` 策略遇到无法切分的原子单元（超长代码块）时，chunk 可以超出 `target_size`，此时在报告中记录该 chunk 的实际尺寸。评测报告中同时公布三种策略的**平均 chunk 尺寸**，证明对比是公平的。

#### 6.2.1 FixedSizeChunker（基线）

按字符数硬切，`target_size=1000, overlap=200`。不做任何结构判断，会切断代码块和段落。这是要被对比的基线。

#### 6.2.2 SemanticChunker（中间基线）

按段落边界（`\n\n`）累积到 `target_size` 后切分，不切断段落。仍不看标题层级。

#### 6.2.3 StructuralChunker（本项目核心）

用 `markdown-it-py` 解析 token 流，按标题层级组织：

**算法**：

1. 遍历 token 流，维护标题栈 `stack: list[(level, text)]`
2. 遇到 `heading_open` → 弹出栈中 level ≥ 当前的项，压入当前标题
3. 遇到内容 token（段落、代码块、表格、列表）→ 归属到当前叶子 section
4. 每个叶子 section 的内容合并为一个 chunk；`breadcrumb = [t for _, t in stack]`
5. 若叶子 section 文本超过 `target_size`：
   - 按段落二次切分成多个子 chunk
   - **每个子 chunk 继承相同的 breadcrumb**
   - 子 chunk 的 `chunk_id` 加序号区分
6. **原子单元**：代码块（`fence`）和表格作为整体不切断
   - 代码块超过 `max_code_size`（默认 3000 字符）时，按空行 + 顶层 `def` / `class` / `function` 边界切分（简单启发式，注释说明其局限）
7. `kind` 判定：section 内代码块占比 > 70% → `"code"`；表格占比 > 70% → `"table"`；两者都有 → `"mixed"`；否则 `"prose"`

**降级路径**：`markdown-it-py` 解析失败（畸形 Markdown）时，退回 `SemanticChunker` 并记录警告日志。

**测试要点**（`tests/test_chunking.py`）：

- 代码块不被切断
- 嵌套标题的 breadcrumb 正确（三级标题的 breadcrumb 长度为 3）
- 超长 section 二次切分后子 chunk 都带 breadcrumb
- 三种策略对同一文档的 chunk 数量关系合理（不做精确断言，避免脆弱）

### 6.3 indexing — 建索引

**向量索引**：

- `sentence-transformers` 加载 `BAAI/bge-m3`，batch=16
- BGE 系列检索需要 query 加前缀：query 侧加 `"Represent this sentence for searching relevant passages: "`，document 侧不加
- Qdrant local mode：`QdrantClient(path="./data/qdrant")`
- 每条 point 的 payload 存完整的 `Chunk` 字段（支持过滤和取回，避免额外查库）
- collection 名含策略名：`docqa_structural` / `docqa_fixed` / `docqa_semantic`，三套索引共存互不干扰

**BM25 索引**：

- `rank_bm25.BM25Okapi`
- 分词：英文按 `\W+` 切并转小写；含中文字符的段落用 `jieba.lcut`
- 持久化到 `data/bm25_<strategy>.pkl`

**幂等**：重复运行 `build_index.py` 时，若 collection 已存在且 chunk 数一致则跳过；`--force` 强制重建。

### 6.4 retrieval — 检索

`HybridRetriever.retrieve(query, k=5, version=None)`：

1. 向量召回 top-20（Qdrant，`version` 非空时加 payload 过滤）
2. BM25 召回 top-20
3. **RRF 融合**：`score = Σ 1/(60 + rank_i)`，取融合后 top-10
4. **Rerank**：`BAAI/bge-reranker-v2-m3` 对 top-10 重排，取 top-k
5. 返回 `list[Chunk]`

**降级开关**：配置项 `retrieval.use_bm25` 和 `retrieval.use_rerank`，便于做消融实验（也用于工期紧张时砍功能）。

### 6.5 generation — 生成

**Prompt 结构**：

```
[system]
你是技术文档助手。只依据提供的材料回答，材料不足以回答时明确说"文档中没有找到"。
每个论断后用 [n] 标注来源编号。若材料来自多个版本，指出你依据的版本。

[user]
材料：
[1] (MCP > Server Concepts > Resources, version=2026-07-28)
<chunk text>

[2] ...

问题：{question}
```

**关键点**：材料里不只给 chunk 文本，**必须带上 breadcrumb 路径和 version**——这是本项目的核心假设，也是评测要验证的变量之一。

**输出**：

```python
@dataclass
class Answer:
    text: str
    citations: list[Citation]   # Citation: chunk_id, index, url, version
```

**参数**：`temperature=0`（评测可复现性要求）。

### 6.6 evaluation — 评测（项目的灵魂）

#### 6.6.1 评测集构建

共 **50 题，四类均衡**（每类 12–13 题）：

| 类型 | 考察点 | 例 |
|---|---|---|
| `factual` | 基础召回 | "MCP 的 Roots 是什么？" |
| `api` | 代码块完整性 | "怎么注册一个 tool？" |
| `cross_doc` | 多跳检索 | "MCP 和 LangGraph 的状态管理有什么区别？" |
| `version` | 版本感知 | "新版 MCP 为什么取消了握手？" |

**构建流程**（面试必问，流程必须是可辩护的）：

1. `scripts/gen_questions.py`：按文档 section 采样，用 LLM 生成候选问题 + 参考答案 + 出处 URL
2. **人工筛选修正**：删除语料覆盖不到的、答案有歧义的、纯常识不需要检索就能答的
3. 每题标注 `gold_urls`（标准答案所在的文档 URL）
4. 落盘 `evalset/evalset.jsonl`

**格式**：

```json
{
  "id": "q001",
  "type": "factual",
  "question": "...",
  "gold_answer": "...",
  "gold_urls": ["https://modelcontextprotocol.io/docs/2026-07-28/learn/server-concepts.md"]
}
```

**明确不做**：不使用全自动生成 + 全自动评判的闭环。生成可以用 LLM 加速，但筛选和答案校准必须人工做过。

#### 6.6.2 指标

| 指标 | 定义 | 计算方式 |
|---|---|---|
| `answer_accuracy` | 答案正确率 | LLM-judge 三档打分（correct=1 / partial=0.5 / wrong=0），`temperature=0`；每题评 2 次，不一致的转人工仲裁 |
| `recall@5` | 检索召回率 | `gold_urls` 是否出现在 top-5 检索结果的 `url` 集合中 |
| `citation_accuracy` | 引用准确率 | 抽样 20 题，人工核查回答中的 `[n]` 是否真的支持对应论断 |

**人工抽查**：`answer_accuracy` 随机抽 20%（10 题）人工复核，报告里公布 LLM-judge 与人工的一致率——这本身就是一个可信度指标。

#### 6.6.3 跑分与报告

```bash
uv run scripts/run_eval.py --strategy structural --limit 50
```

输出 `reports/eval-<strategy>-<timestamp>.md`，包含：

- **汇总表**：三类指标 × 三种策略，**附各策略的平均 chunk 尺寸和 chunk 总数**（证明对比公平）
- **分类别拆分**：四类问题各自的准确率（**这是最有价值的分析**——预期 `api` 类和 `version` 类上结构切片的优势最明显）
- **逐题明细**：问题、模型答案、参考答案、是否命中、引用
- **失败案例分析**：按失败原因归类（未召回 / 召回但答错 / 引用错误 / 拒答），每类给出 2–3 个具体例子

---

## 7. 目录结构

```
doc-qa/
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── configs/
│   └── sources.yaml
├── src/docqa/
│   ├── __init__.py
│   ├── config.py           # pydantic-settings
│   ├── models.py           # Document / Chunk / Answer
│   ├── corpus/
│   │   ├── llms_txt.py     # llms.txt 递归解析
│   │   ├── fetcher.py      # 并发下载
│   │   └── versioning.py   # 版本提取
│   ├── chunking/
│   │   ├── base.py
│   │   ├── fixed.py
│   │   ├── semantic.py
│   │   └── structural.py   # 核心
│   ├── indexing/
│   │   ├── embedder.py
│   │   ├── vector_store.py
│   │   └── bm25_index.py
│   ├── retrieval/
│   │   ├── fusion.py       # RRF
│   │   └── hybrid.py
│   ├── generation/
│   │   ├── prompt.py
│   │   └── generator.py
│   └── evaluation/
│       ├── evalset.py
│       ├── judge.py
│       └── report.py
├── scripts/
│   ├── fetch_corpus.py
│   ├── build_index.py
│   ├── gen_questions.py
│   └── run_eval.py
├── cli.py
├── evalset/
│   └── evalset.jsonl
├── reports/
├── tests/
│   ├── test_llms_txt.py
│   ├── test_chunking.py
│   └── test_fusion.py
└── docs/
    └── superpowers/specs/
        └── 2026-09-18-doc-qa-design.md
```

**`.gitignore` 要点**：`data/`（原始语料和索引体积大）、`.env`、`__pycache__`、`.venv`。`evalset/evalset.jsonl` **必须提交**——它是你劳动成果的证明。

---

## 8. 非目标（YAGNI）

以下明确不做，防止两周不够用：

- ❌ Web UI（先用 CLI；仅在全部里程碑完成后有余力再加 Streamlit）
- ❌ 用户系统、鉴权、多轮对话
- ❌ Agent 自主决策 / 多跳检索编排（那是方向 B）
- ❌ 文档源数量——**先只做 MCP + LangGraph 两个**，跑通再考虑加
- ❌ 部署上线、Docker、CI
- ❌ 微调模型

---

## 9. 里程碑

| 里程碑 | 截止 | 验收标准 |
|---|---|---|
| M1 语料落地 | D2 | 两源 ≥400 篇 `.md`，`corpus.jsonl` 生成，MCP 版本字段非 unknown ≥90% |
| M2 切片策略 | D4 | 三种 Chunker 实现 + 测试通过 |
| M3 检索可用 | D5 | 索引构建完成，CLI 能返回带来源的检索结果 |
| M4 生成完成 | D7 | CLI 能返回带引用和版本标注的答案 |
| M5 评测跑分 | D10 | 50 题评测集完成，三策略对比报告生成 |
| M6 迭代优化 | D12 | 失败分析完成 + 至少一轮针对性优化 |
| M7 交付 | D14 | README + demo + 简历材料 + 面试问答准备 |

---

## 10. 风险与应对

| 风险 | 概率 | 应对 |
|---|---|---|
| 某源无 llms.txt 或 `.md` 不可下 | 低（已实测） | 降级：`git clone` 官方文档仓库，取 `docs/` 目录 |
| BGE-M3 本地推理太慢（CPU） | 中 | 降级 `bge-small-en-v1.5`；或批量离线编码 + 缓存 |
| 评测集构建超时 | **高** | 先做 30 题保底（M5 前半程），剩余 20 题在 D11-12 补；报告里注明题量 |
| LLM-judge 不稳定 | 中 | `temperature=0` + 每题评 2 次取一致 + 人工抽查 20% 并公布一致率 |
| 两周不够 | 中 | 按此顺序砍：rerank → BM25 → 评测集 50→30 题。**核心实验（三策略对比）最后砍** |
| 本地环境跑不动 embedding | 低 | 切换到云端 embedding API，架构不变 |

---

## 11. 简历与面试材料（D13-14 产出）

README 必须包含的内容：

1. **一句话说清项目**：面向技术文档的结构感知 RAG，解决切片切坏和版本混淆
2. **架构图**（Mermaid）
3. **实验数据表**：三策略 × 三指标的完整对比
4. **失败案例分析**：至少 3 个具体例子，说清原因和改进方向
5. **快速开始**：`uv sync` → 抓语料 → 建索引 → 提问，三步以内跑起来
6. **设计取舍**：为什么不用 LangChain、为什么 BM25 和向量都要、为什么这么切

**面试预备问答**（必须能答）：

- 为什么不用现成的 RAG 框架？
- 结构切片具体提升在哪一类问题上？为什么？
- 评测集怎么保证客观？LLM-judge 可信吗？
- 如果文档更新了，你的索引怎么同步？
- 这个方案在什么情况下会失效？
