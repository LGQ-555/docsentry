# 开发者支持 Agent（DevSupport Agent）— 设计文档

- 日期：2026-09-18
- 状态：待评审（第 2 版，含重大修订）
- 目标：校招/实习简历项目 + 学习 Agent 工程实践
- 工期：14 天

> **第 2 版修订说明**：项目定位从"通用技术文档问答"收敛为"开发者支持 Agent"；引入 LangGraph 作为编排层；补充增量更新设计；多格式/多模态/UI 降级为选做。

---

## 1. 项目概述

### 1.1 业务定位

**面向工程师的开发者支持 Agent**：帮助使用某个技术框架的开发者做自助排障与文档查询。

- **用户**：使用该框架的开发者
- **典型诉求**：查 API 用法、排查配置问题、跨版本迁移咨询
- **为什么这是个真业务**：开发者支持（DevRel / Developer Support）是真实岗位职能，成本高、重复度高、适合自动化

### 1.2 与同类项目的差异

市面上已有的企业知识库项目（如 ragent）面向**企业内部非技术用户**，语料是 HR/业务文档，难点在权限与组织架构。

本项目面向**开发者**，语料是 API 文档，难点在：

- **技术术语的精确匹配**（`StreamMode`、`checkpointer` 这类词，纯语义检索反而不如关键词准）
- **代码块的完整性**（切断了就答错）
- **版本差异**（开发者问的往往是"新版怎么写"）

**不同的场景、不同的数据、不同的难点**，不与已有项目正面竞争。

### 1.3 要解决的两个失效模式

1. **切片切坏**——固定长度切分把代码块拦腰截断、丢掉标题层级。检索到的 chunk 是"设置 timeout 为 30 秒"，但不知道说的是哪个类。
2. **版本混淆**——文档 API 迭代快，语料混着多个版本。开发者问新版写法，检索命中两年前的旧 API，模型据此编出已废弃的用法。

### 1.4 项目做什么

面向技术文档的 RAG 系统 + Agent 编排层。核心差异化在**切片层**与**版本感知**，并通过**消融实验**量化每一步的价值。

### 1.5 语料来源（已实测验证）

| 源 | llms.txt | 形态 | 版本信息 |
|---|---|---|---|
| MCP | `https://modelcontextprotocol.io/llms.txt` | 平铺列表，链接指向 `.md` | ✅ URL 路径自带：`/docs/2026-07-28/` |
| LangGraph / LangChain | `https://docs.langchain.com/llms.txt` | **层级索引**，指向子 `llms.txt` | 需从路径或内容提取 |

实测：`https://docs.langchain.com/oss/python/langgraph/overview.md` → HTTP 200，`Content-Type: text/markdown`。

`llms.txt` 是 2024 年起的标准，为 LLM 提供文档索引，链接的是 `.md` 源文件而非 HTML——无需 HTML 清洗，切片质量天然更高。

---

## 2. 验收标准

**必达（不做完不算交付）**：

1. CLI 能回答 MCP + LangGraph 文档的问题，答案带来源链接与版本标注
2. 三种切片策略在同一 50 题评测集上的对比表
3. **pipeline vs agent 编排模式的消融对比**
4. README 含架构图、实验数据表、失败案例分析
5. 2 分钟可演示，面试官可现场提问
6. 简历条目 + 面试问答准备材料

**加分（有余力才做）**：PDF/Office 转换、图片 caption、Streamlit 界面。

---

## 3. 技术选型

| 组件 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.11+ | 生态最全 |
| 包管理 | uv | 环境已装（`F:\UV`） |
| Embedding | `BAAI/bge-m3`（本地） | 中英文均可，免费 |
| Reranker | `BAAI/bge-reranker-v2-m3`（本地） | 与 embedding 同系列 |
| 向量库 | Qdrant（local mode） | 无需起服务，payload 过滤成熟 |
| 稀疏检索 | `rank_bm25` + jieba | 纯 Python，几千 chunk 足够 |
| Markdown 解析 | `markdown-it-py` | CommonMark 合规，提供带位置 token 流 |
| **编排层** | **LangGraph** | 见下方说明 |
| LLM | 云端 OpenAI 兼容 API | `OPENAI_BASE_URL` 可指向 DeepSeek / Qwen |
| CLI | `typer` | 开发快 |
| 配置 | `pydantic-settings` + `.env` | 类型安全 |
| 测试 | `pytest` | — |
| 报告 | `pandas` + Markdown 输出 | — |

### 3.1 关于框架使用的立场（重要）

**分层使用，不是全用也不是全不用**：

| 层 | 是否用框架 | 理由 |
|---|---|---|
| **编排层** | ✅ 用 LangGraph | 编排是"配置"不是"算法"，用框架省时；且是招聘 JD 的真实关键词 |
| 切片层 | ❌ 自研 | 这是项目差异化所在，用现成 splitter 就讲不出东西 |
| 检索层 | ❌ 自研 | RRF 融合、版本过滤是实验变量，必须可控 |
| 评测层 | ❌ 自研 | 现成 eval 框架（ragas 等）不贴合本项目的分类指标 |
| 生成层 | ❌ 自研 | 简单的 prompt 组装，套框架反而增加不可控 |

**面试话术**："编排我用了 LangGraph，因为它解决的是状态管理和条件分支，这是配置问题；但切片、检索融合和评测我全部自研，因为这些是实验变量，我必须完全控制才能做消融对比。"

> 注意区分：LangGraph 在本项目中**既是编排框架，也是语料来源**（它的官方文档）。这两件事互不冲突，但说明时要讲清楚。

---

## 4. 系统架构

### 4.1 模块划分

```
corpus/       语料获取与管理     →  llms.txt 递归解析、下载、版本提取、增量更新
  converters/ 格式转换（可插拔）  →  Converter: Path -> Document
chunking/     切片策略（核心）    →  统一接口 chunk(doc) -> list[Chunk]
indexing/     建索引             →  embedding + Qdrant upsert + BM25
retrieval/    检索               →  双路召回 + RRF 融合 + rerank + 版本过滤
generation/   生成               →  prompt 组装 + 引用标注
agent/        编排层（LangGraph） →  多步检索状态图
evaluation/   评测               →  评测集、跑分、报告
```

**分层原则**：`retrieval` 和 `generation` 必须能被**独立调用**（不经过 agent），这是消融实验的前提。`agent/` 是它们之上的编排层，不侵入下层。

### 4.2 数据流

```
configs/sources.yaml
    ↓  scripts/fetch_corpus.py
data/raw/<source>/**.md                 （原始文件）
data/manifest.json                      （URL → {content_hash, version, fetched_at}）
    ↓  解析 + 版本提取 + 变更检测
data/corpus.jsonl                       （Document 列表）
    ↓  scripts/build_index.py（调用 Chunker）
data/qdrant/                            （向量索引，payload 含完整 chunk 元数据）
data/bm25_<strategy>.pkl                （BM25 索引）
    ↓  cli.py ask "问题" [--mode pipeline|agent]
检索 → 融合 → rerank → 生成 → 带引用的答案
    ↓  scripts/run_eval.py --strategy X --mode Y
reports/eval-<strategy>-<mode>-<ts>.md  （跑分报告）
```

### 4.3 核心接口

```python
# corpus/converters/base.py
class Converter(Protocol):
    supported: set[str]                       # {".md", ".pdf", ".docx", ...}
    def convert(self, path: Path) -> Document: ...

# chunking/base.py
class Chunker(Protocol):
    name: str
    def chunk(self, doc: Document) -> list[Chunk]: ...

# retrieval/base.py
class Retriever(Protocol):
    def retrieve(self, query: str, k: int = 5, version: str | None = None) -> list[Chunk]: ...
```

三个接口各自屏蔽实现差异——`Converter` 屏蔽格式、`Chunker` 屏蔽切片策略、`Retriever` 屏蔽检索方案。三者都是消融实验的切换点。

---

## 5. 数据模型

```python
# src/docqa/models.py

@dataclass
class Document:
    doc_id: str        # sha256(source + path)[:16]，稳定不变
    source: str        # "mcp" | "langgraph"
    version: str       # "2026-07-28"，无法提取时为 "unknown"
    url: str
    title: str
    path: str
    content: str       # 统一为 Markdown
    content_hash: str  # sha256(content)
    origin_format: str # "md" | "pdf" | "docx" | ...  用于按格式分析

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
    strategy: str
    char_count: int

@dataclass
class Answer:
    text: str
    citations: list[Citation]   # Citation: chunk_id, index, url, version
    mode: str                   # "pipeline" | "agent"
    rounds: int                 # agent 模式的检索轮数
```

`breadcrumb` 与 `version` 是检索和生成阶段的关键上下文，必须落库到 Qdrant payload 以支持过滤。

---

## 6. 模块详细设计

### 6.1 corpus — 语料获取与增量更新

#### 6.1.1 配置

```yaml
# configs/sources.yaml
sources:
  - name: mcp
    llms_txt: https://modelcontextprotocol.io/llms.txt
    url_include: "/docs/"
    keep_all_versions: true        # 多版本共存
  - name: langgraph
    llms_txt: https://docs.langchain.com/llms.txt
    url_include: "/oss/python/"
    keep_all_versions: true
```

#### 6.1.2 llms.txt 递归解析

1. 下载 `llms.txt`
2. 解析行格式 `- [title](url): description`
3. **若条目 URL 以 `llms.txt` 结尾 → 视为子索引，递归展开**（`docs.langchain.com` 即此形态），最多 2 层，用已访问 URL 集合防环
4. 收集 `.md` 结尾的条目；目录项（以 `/` 结尾）跳过

#### 6.1.3 版本提取（按优先级）

1. URL 路径正则 `/docs/(\d{4}-\d{2}-\d{2})/` → MCP 命中
2. front-matter 或正文中的 `version` 字段
3. 配置的 `default_version`
4. 兜底 `"unknown"`

#### 6.1.4 增量更新（v2 新增）

**变更检测**：维护 `data/manifest.json`，记录每个 URL 的 `content_hash` 与 `version`。

```
重新抓取 llms.txt
  ↓
URL 集合 diff  →  新增 / 删除 / 保留
  ↓
对保留项下载并比对 content_hash  →  未变（跳过）/ 已变（标记更新）
```

**索引同步**：

| 变更类型 | 操作 |
|---|---|
| 新增文档 | 切片 → embed → upsert |
| 内容修改 | **先按 `doc_id` 删除该文档全部旧 chunk**，再重新切片 upsert |
| 文档删除 | 按 `doc_id` 删除全部 chunk |

> ⚠️ **必须"先删后插"**。若只 upsert，当文档内容变短（如 10 个 chunk 缩到 6 个）时，第 7–10 个 chunk 因 `chunk_id` 不变而**不会被覆盖，成为孤儿**，仍会被检索命中并返回已失效内容。这是 v1 设计的缺陷，v2 修正。

**版本演进策略**：`keep_all_versions: true` 时新旧版本共存于索引，chunk 各带 `version` 标签，检索时可按版本过滤。这直接支撑"版本感知"这一差异化卖点。

**BM25 索引**：内存索引增量更新复杂度高，收益低——直接全量重建（几千 chunk 秒级完成）。

**幂等性**：`fetch_corpus.py` 与 `build_index.py` 均可重复运行，结果一致。

### 6.2 converters — 格式转换（可插拔，选做）

统一接口，把任意格式转成 Markdown 后交给下游，下游模块完全不感知原始格式。

| 实现 | 优先级 | 依赖 | 说明 |
|---|---|---|---|
| `MarkdownConverter` | **必做** | 无 | 直接读取 |
| `PdfConverter` | 选做 | `pymupdf4llm` 或 `markitdown` | 仅处理文字版 PDF |
| `OfficeConverter` | 选做 | `markitdown` | docx / pptx / xlsx |
| `ImageConverter` | 选做 | VLM API | 生成图片描述文本入索引 |

**明确不做完整多模态**：ColPali 类视觉检索（约 5 天）在本场景收益低——开发者支持场景的图片主要是架构图与报错截图，用 VLM 生成 caption 入索引即可覆盖，成本约为其 1/5。

所有转换器产出的 `Document.origin_format` 需正确标注，以便评测时按格式分析。

### 6.3 chunking — 切片策略（核心）

三种实现，同一接口。

**公平性约束（实验有效性的前提）**：三种策略共享同一 `target_size`（默认 1000 字符，定义在 `configs/chunking.yaml`）。三者都朝这个尺寸努力，**差异只体现在"切在哪里"，而非切多大**。若尺寸不同，准确率差异无法归因于切片策略本身。

允许的例外：`structural` 遇到无法切分的原子单元（超长代码块）时可超出 `target_size`，此时在报告中记录实际尺寸。评测报告同时公布三策略的**平均 chunk 尺寸与 chunk 总数**，自证对比公平。

#### 6.3.1 FixedSizeChunker（基线）

按字符数硬切，`target_size=1000, overlap=200`。不做任何结构判断，会切断代码块和段落。

#### 6.3.2 SemanticChunker（中间基线）

按段落边界（`\n\n`）累积到 `target_size` 后切分，不切断段落。仍不看标题层级。

#### 6.3.3 StructuralChunker（核心）

用 `markdown-it-py` 解析 token 流，按标题层级组织：

1. 遍历 token 流，维护标题栈 `stack: list[(level, text)]`
2. 遇 `heading_open` → 弹出栈中 `level >= 当前` 的项，压入当前标题
3. 遇内容 token（段落/代码块/表格/列表）→ 归属当前叶子 section
4. 每个叶子 section 合并为一个 chunk，`breadcrumb = [t for _, t in stack]`
5. 若叶子 section 超过 `target_size`：
   - 按段落二次切分为多个子 chunk
   - **每个子 chunk 继承相同 breadcrumb**
   - `chunk_id` 加序号区分
6. **原子单元**：代码块（`fence`）与表格整体不切断
   - 代码块超 `max_code_size`（默认 3000 字符）时，按空行 + 顶层 `def`/`class`/`function` 边界切分（启发式，代码中注明局限）
7. `kind` 判定：section 内代码块占比 > 70% → `"code"`；表格 > 70% → `"table"`；两者皆有 → `"mixed"`；否则 `"prose"`

**降级路径**：解析失败（畸形 Markdown）时退回 `SemanticChunker` 并记录警告。

**测试要点**（`tests/test_chunking.py`）：

- 代码块不被切断
- 三级标题的 breadcrumb 长度为 3
- 超长 section 二次切分后子 chunk 均带 breadcrumb
- 三策略对同一文档的 chunk 数量关系合理（不做精确断言，避免脆弱）

### 6.4 indexing — 建索引

**向量索引**：

- `sentence-transformers` 加载 `BAAI/bge-m3`，batch=16
- BGE 系列需 query 前缀：query 侧加 `"Represent this sentence for searching relevant passages: "`，document 侧不加
- Qdrant local mode：`QdrantClient(path="./data/qdrant")`
- payload 存完整 `Chunk` 字段（支持过滤与取回）
- collection 名含策略名：`docqa_structural` / `docqa_fixed` / `docqa_semantic`，三套索引共存

**BM25 索引**：`rank_bm25.BM25Okapi`；英文按 `\W+` 切并小写，含中文段落用 `jieba.lcut`；持久化 `data/bm25_<strategy>.pkl`。

**幂等**：collection 已存在且 chunk 数一致则跳过，`--force` 强制重建。

### 6.5 retrieval — 检索

`HybridRetriever.retrieve(query, k=5, version=None)`：

1. 向量召回 top-20（Qdrant，`version` 非空时加 payload 过滤）
2. BM25 召回 top-20
3. **RRF 融合**：`score = Σ 1/(60 + rank_i)`，取 top-10
4. **Rerank**：`bge-reranker-v2-m3` 重排，取 top-k
5. 返回 `list[Chunk]`

**降级开关**：`use_bm25` / `use_rerank` 配置项，支持消融（也用于工期紧张时砍功能）。

### 6.6 generation — 生成

**Prompt 结构**：

```
[system]
你是开发者支持助手。只依据提供的材料回答，材料不足时明确说"文档中没有找到"。
每个论断用 [n] 标注来源。若材料含多个版本，指出你依据的版本。

[user]
材料：
[1] (MCP > Server Concepts > Resources, version=2026-07-28)
<chunk text>

[2] ...

问题：{question}
```

**关键点**：材料中不只给 chunk 文本，**必须带 breadcrumb 路径与 version**——这是本项目的核心假设，也是评测要验证的变量之一。

**参数**：`temperature=0`（评测可复现性要求）。

### 6.7 agent — 编排层（LangGraph，v2 新增）

#### 6.7.1 状态图设计

```python
class AgentState(TypedDict):
    question: str
    query_type: str            # factual | api | cross_doc | version
    queries: list[str]         # 改写后的查询
    retrieved: list[Chunk]
    rounds: int
    sufficient: bool
    answer: Answer | None
```

```
        ┌──────────┐
        │ analyze  │  判断问题类型，生成检索查询
        └────┬─────┘
             ↓
        ┌──────────┐
   ┌───→│ retrieve │  调用 HybridRetriever（带版本过滤）
   │    └────┬─────┘
   │         ↓
   │    ┌──────────┐
   │    │  assess  │  材料是否足够回答？
   │    └────┬─────┘
   │         │
   │  不足且 rounds < max_rounds(3)
   └────┬────┘
        │ 足够 或 达到轮数上限
        ↓
   ┌──────────┐
   │ generate │  生成答案 + 引用标注
   └────┬─────┘
        ↓
       END
```

**为什么这个 agent 不是硬凑的**：开发者支持场景中，"MCP 和 LangGraph 状态管理的区别"这类跨文档问题，单次检索必然召不全；而 `assess` 节点判断材料是否充分、不足则改写查询再检索，是真实需要的能力。`max_rounds=3` 防止无限循环与成本失控。

#### 6.7.2 消融实验（重要产出）

`agent/` 层不侵入下层，因此可以干净地对比两种模式：

| 模式 | 流程 | 说明 |
|---|---|---|
| `pipeline` | analyze → retrieve → generate | 单次检索，无自我评估 |
| `agent` | 完整状态图 | 多步检索 + 材料充分性判断 |

**对比指标**：准确率（分问题类型）、平均检索轮数、token 成本、延迟。

**预期（需实验验证，不能预设结论）**：agent 模式在 `cross_doc` 类应有提升，在 `factual` 类可能持平但成本更高。**若实验结果与预期不符，如实报告**——"我发现 agent 编排在这个场景下性价比不高，数据是……"这样的结论比强行证明 agent 有用更有说服力。

### 6.8 evaluation — 评测（项目的灵魂）

#### 6.8.1 评测集构建

**50 题，四类均衡**（每类 12–13 题）：

| 类型 | 考察点 | 例 |
|---|---|---|
| `factual` | 基础召回 | "MCP 的 Roots 是什么？" |
| `api` | 代码块完整性 | "怎么注册一个 tool？" |
| `cross_doc` | 多跳检索 | "MCP 和 LangGraph 的状态管理有什么区别？" |
| `version` | 版本感知 | "新版 MCP 为什么取消了握手？" |

**构建流程**（面试必问，必须可辩护）：

1. `scripts/gen_questions.py`：按 section 采样，用 LLM 生成候选问题 + 参考答案 + 出处 URL
2. **人工筛选修正**：删除语料覆盖不到的、答案有歧义的、不检索也能答的常识题
3. 每题标注 `gold_urls`
4. 落盘 `evalset/evalset.jsonl`

```json
{
  "id": "q001",
  "type": "factual",
  "question": "...",
  "gold_answer": "...",
  "gold_urls": ["https://modelcontextprotocol.io/docs/2026-07-28/learn/server-concepts.md"],
  "origin_format": "md"
}
```

**明确不做**：不使用全自动生成 + 全自动评判的闭环。生成可用 LLM 加速，但筛选与答案校准必须人工做过。

#### 6.8.2 指标

| 指标 | 定义 | 计算 |
|---|---|---|
| `answer_accuracy` | 答案正确率 | LLM-judge 三档（correct=1 / partial=0.5 / wrong=0），`temperature=0`；每题评 2 次，不一致转人工仲裁 |
| `recall@5` | 检索召回率 | `gold_urls` 是否出现在 top-5 结果的 url 集合中 |
| `citation_accuracy` | 引用准确率 | 抽 20 题人工核查 `[n]` 是否支持对应论断 |
| `avg_rounds` / `avg_tokens` / `avg_latency` | 成本指标 | agent 消融实验必需 |

**人工抽查**：`answer_accuracy` 随机抽 20%（10 题）人工复核，报告中公布 LLM-judge 与人工的一致率——这本身就是一个可信度指标。

#### 6.8.3 跑分与报告

```bash
uv run scripts/run_eval.py --strategy structural --mode agent --limit 50
```

输出 `reports/eval-<strategy>-<mode>-<ts>.md`：

- **汇总表**：三类指标 × 三种策略 × 两种模式，附各策略平均 chunk 尺寸与总数（证明对比公平）
- **分类别拆分**：四类问题各自准确率（**最有价值的分析**）
- **逐题明细**：问题、模型答案、参考答案、是否命中、引用
- **失败案例分析**：按原因归类（未召回 / 召回但答错 / 引用错误 / 拒答），每类给 2–3 个具体例子

---

## 7. 目录结构

```
doc-qa/
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── configs/
│   ├── sources.yaml
│   └── chunking.yaml
├── src/docqa/
│   ├── config.py
│   ├── models.py
│   ├── corpus/
│   │   ├── llms_txt.py
│   │   ├── fetcher.py
│   │   ├── manifest.py        # 增量更新：变更检测
│   │   ├── versioning.py
│   │   └── converters/
│   │       ├── base.py
│   │       └── markdown.py
│   ├── chunking/
│   │   ├── base.py
│   │   ├── fixed.py
│   │   ├── semantic.py
│   │   └── structural.py      # 核心
│   ├── indexing/
│   │   ├── embedder.py
│   │   ├── vector_store.py
│   │   └── bm25_index.py
│   ├── retrieval/
│   │   ├── fusion.py
│   │   └── hybrid.py
│   ├── generation/
│   │   ├── prompt.py
│   │   └── generator.py
│   ├── agent/
│   │   ├── state.py
│   │   └── graph.py           # LangGraph 状态图
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
├── evalset/evalset.jsonl
├── reports/
├── tests/
└── docs/superpowers/specs/2026-09-18-doc-qa-design.md
```

**`.gitignore` 要点**：`data/`、`.env`、`.venv/`、`__pycache__/`。**`evalset/evalset.jsonl` 必须提交**——它是核心劳动成果的证明。

---

## 8. 范围与优先级

### 8.1 必做（护城河，11 天）

语料管线 + 增量更新 / 结构感知切片（三策略）/ 检索 / 生成 / 评测 + 跑分 / 失败分析

**这部分别人抄不走**——它是"实验"不是"功能"。

### 8.2 应做（简历关键词，2 天）

LangGraph 编排层 + pipeline vs agent 消融实验。

### 8.3 选做（有余力才做，各 0.5–2 天）

| 项 | 成本 | 收益 |
|---|---|---|
| PDF / Office 转换器 | 1 天 | "支持多格式"关键词 |
| 图片 VLM caption | 1 天 | "多模态"关键词 |
| Streamlit 对话界面 | 1 天 | 演示更好看 |

### 8.4 明确不做

- ❌ 完整多模态视觉检索（ColPali，约 5 天，本场景收益低）
- ❌ Web 上传 UI（会把项目推向上传/存储/多用户的复杂度，偏离定位）
- ❌ 用户系统、鉴权、多租户
- ❌ 部署上线、Docker、CI
- ❌ 模型微调
- ❌ 文档源扩张（先只做 MCP + LangGraph，跑通再说）

### 8.5 工期不足时的砍功能顺序

**严格按此顺序**，从下往上砍：

1. 选做三项（PDF / 图片 / UI）—— 先砍
2. `rerank`（降级为纯 RRF 融合）
3. `BM25`（降级为纯向量检索）
4. agent 编排（降级为 pipeline 单次检索）
5. 评测集 50 → 30 题

**核心实验（三策略切片对比）最后砍。** 只要它在，项目就是完整的；它没了，项目就废了。

> 更好的做法：D11 结束后做一次中期检查，如果进度落后，当场按此顺序砍，而不是拖到最后崩盘。

---

## 9. 里程碑

| 里程碑 | 截止 | 验收标准 |
|---|---|---|
| M1 语料落地 | D2 | 两源 ≥400 篇 `.md`；`corpus.jsonl` 生成；MCP 版本字段非 unknown ≥90%；`--update` 增量更新可运行 |
| M2 切片策略 | D5 | 三种 Chunker 实现 + 测试通过 + 平均尺寸一致性检查通过 |
| M3 检索可用 | D6 | 索引构建完成，CLI 返回带来源的检索结果 |
| M4 生成完成 | D7 | CLI 返回带引用与版本标注的答案 |
| M5 评测跑分 | D10 | 50 题评测集完成；三策略对比报告生成 |
| M6 agent 编排 | D12 | LangGraph 状态图完成；pipeline vs agent 消融报告生成 |
| M7 交付 | D14 | README + demo + 简历材料 + 面试问答准备 |

**中期检查点（D11）**：评估进度，必要时按 8.5 砍功能。

---

## 10. 风险与应对

| 风险 | 概率 | 应对 |
|---|---|---|
| 某源 `.md` 不可下 | 低（已实测） | 降级：`git clone` 官方文档仓库取 `docs/` |
| bge-m3 本地推理太慢（CPU） | 中 | 降级 `bge-small-en-v1.5`；或离线批量编码 + 缓存 |
| 评测集构建超时 | **高** | 先做 30 题保底（M5 前半程），D11-12 补足 50；报告注明题量 |
| LLM-judge 不稳定 | 中 | `temperature=0` + 每题评 2 次 + 人工抽查 20% 并公布一致率 |
| LangGraph 学习成本超预期 | 中 | D11 中期检查时评估；必要时降级为手写循环（保留 agent 语义，只是不用框架） |
| 工期不足 | 中 | 按 8.5 顺序砍；**核心实验最后砍** |
| 本地跑不动 embedding | 低 | 切云端 embedding API，架构不变 |

---

## 11. 交付材料（D14 产出）

README 必须包含：

1. **一句话说清项目**：面向开发者的技术文档支持 Agent，解决切片切坏与版本混淆
2. **架构图**（Mermaid）
3. **实验数据表**：三策略 × 两模式 × 三指标的完整对比
4. **失败案例分析**：至少 3 个具体例子，说清原因与改进方向
5. **快速开始**：`uv sync` → 抓语料 → 建索引 → 提问，三步内跑起来
6. **设计取舍**：为什么编排用 LangGraph 而切片自研、为什么 BM25 和向量都要、为什么多模态排到选做

**面试预备问答**（必须能答）：

- 为什么编排用 LangGraph，切片却自己写？
- 结构切片具体在哪一类问题上提升？为什么？
- 评测集怎么保证客观？LLM-judge 可信吗？
- agent 编排比单次检索强多少？值得吗？（**要用数据回答**）
- 如果文档更新了，你的索引怎么同步？（**答案：增量更新 + 先删后插 + 多版本共存**）
- 这个方案在什么情况下会失效？
- 你的项目和一个成熟的企业知识库项目（如 ragent）区别在哪？（**答案：场景不同、数据不同、难点不同，且我有量化实验**）
