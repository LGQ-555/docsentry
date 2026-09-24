# docsentry — 开发者支持 Agent 设计文档

- 日期：2026-09-18
- 状态：待评审（第 3 版）
- 目标：构建可实际使用的开发者支持 Agent
- 工期：14 天（压缩排期，见 §9 说明）

> **版本演进**
> - **v1**：通用文档问答，Markdown only，不用任何框架
> - **v2**：定位收敛为"开发者支持 Agent"；引入 LangGraph 编排层；补增量更新设计；修复孤儿 chunk 缺陷；多格式/多模态/UI 降级为选做
> - **v3**：语料层重构为 `Source` 抽象（支持无 `llms.txt` 的私有语料）；增量更新改为**先插后删**；新增可观测性与触发机制；新增数据新鲜度（provenance）设计；新增时效性三组对比实验；新增"已知限制"章节

---

## 1. 项目概述

### 1.1 业务定位

**面向工程师的开发者支持 Agent**：帮助使用某个技术框架的开发者做自助排障与文档查询。

- **用户**：使用该框架的开发者
- **典型诉求**：查 API 用法、排查配置问题、跨版本迁移咨询
- **为什么是真业务**：开发者支持（DevRel / Developer Support）是真实岗位职能，成本高、重复度高、适合自动化

### 1.2 与同类项目的差异

已有企业知识库项目（如 ragent）面向**企业内部非技术用户**，语料是 HR/业务文档，难点在权限与组织架构。

本项目面向**开发者**，语料是 API 文档，难点在：技术术语的精确匹配、代码块完整性、版本差异。**不同场景、不同数据、不同难点，不正面竞争。**

### 1.3 项目的真正命题

技术文档**不是**本项目的价值所在，它是**实验载体**——公开、干净、可复现、任何人能当场验证。

本项目研究的问题是：

> **在语料是"模型训练数据里没有的内容"时，检索系统该怎么做才能答对？**

这个问题有两类表现，它们本质是同一件事：

| 表现 | 说明 |
|---|---|
| **时效性** | 文档在模型训练截止后更新了（如 MCP 2026-07-28 大改，模型只知道旧版） |
| **私有语料** | 企业内部文档、私有 SDK——模型训练时根本没见过 |

**关键洞察**：对模型而言，"刚发布的新文档"和"公司内部文档"是同一种东西——**都是知识盲区**。因此可以在公开语料上等价验证私有语料场景的效果，无需真实企业数据。

结论可迁移到任何 RAG 场景；这也正是企业做 RAG 的根本原因。

### 1.4 要解决的两个失效模式

1. **切片切坏**——固定长度切分把代码块拦腰截断、丢掉标题层级。检索到的 chunk 是"设置 timeout 为 30 秒"，但不知道说的是哪个类。
2. **版本混淆**——文档 API 迭代快，语料混着多个版本。开发者问新版写法，检索命中两年前的旧 API，模型据此编出已废弃的用法。

### 1.5 语料来源（已实测验证）

| 源 | llms.txt | 形态 | 版本信息 |
|---|---|---|---|
| MCP | `https://modelcontextprotocol.io/llms.txt` | 平铺列表，链接指向 `.md` | ✅ URL 路径自带：`/docs/2026-07-28/` |
| LangGraph / LangChain | `https://docs.langchain.com/llms.txt` | **混合**：58 个 `llms.txt` 子索引 + 119 条直连 `.md`（同一文件内并存） | 需从路径或内容提取 |

实测：`https://docs.langchain.com/oss/python/langgraph/overview.md` → HTTP 200，`Content-Type: text/markdown`。

**语料规模实测（2026-09-21 复核）**：MCP 347 条唯一 `.md`（经 `url_include` 过滤后 252）；LangChain 顶层为 58 个子索引 + 119 条直连 `.md`，其 `/oss/python/llms.txt` 展开出 369 条唯一 `.md`。两边**均 0 个** URL 含 `?` / `#` / `:` 或端口。MCP 的 `llms.txt` 含 **5 条重复链接**（352 条链接 / 347 唯一），**解析器必须去重**。

**HTTP 缓存实测结论**：MCP 文档站**无 ETag**，`Last-Modified` 是站点构建时间（非内容修改时间）**不可靠**。因此 **`content_hash` 是唯一可靠的变更判据**，必须全量下载比对。成本可接受（单页约 3 KB × 621 页 ≈ 1.8 MB；621 = MCP 过滤后 252 + LangChain 369）。

---

## 2. 验收标准

**必达**：

1. CLI 能回答 MCP + LangGraph 文档的问题，答案带来源链接、版本标注与索引时间
2. 三种切片策略在同一 50 题评测集上的对比表
3. **pipeline vs agent 编排模式的消融对比**
4. **时效性三组对比实验**（模型直答 / 过期索引 / 最新索引）
5. README 含架构图、实验数据表、失败案例分析、已知限制
6. 2 分钟可演示，任何人可当场提问
7. 设计决策说明（FAQ）

**加分**：PDF/Office 转换、图片 caption、Streamlit 界面。

---

## 3. 技术选型

| 组件 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.11+ | 生态最全 |
| 包管理 | uv | 环境已装（`F:\UV`） |
| Embedding | `BAAI/bge-m3`（**本地**） | 中英文均可；**且是数据不出域的合规优势** |
| Reranker | `BAAI/bge-reranker-v2-m3`（本地） | 与 embedding 同系列 |
| 向量库 | Qdrant（local mode） | 无需起服务，payload 过滤成熟 |
| 稀疏检索 | `rank_bm25` + jieba | 纯 Python，几千 chunk 足够 |
| Markdown 解析 | `markdown-it-py` | CommonMark 合规，带位置 token 流 |
| 编排层 | LangGraph | 见 §3.1 |
| LLM | 云端 OpenAI 兼容 API，**支持切换本地 Ollama** | 私有语料场景可完全离线 |
| CLI | `typer` | 开发快 |
| 配置 | `pydantic-settings` + `.env` | 类型安全 |
| 测试 | `pytest` | — |
| 报告 | `pandas` + Markdown 输出 | — |

**明确不使用**：`watchdog` 等常驻文件监控。理由见 §6.1.5——索引是定期触发的批处理，每次重扫目录即可，不需要常驻进程。

### 3.1 关于框架使用的立场

**分层使用，不是全用也不是全不用**：

| 层 | 是否用框架 | 理由 |
|---|---|---|
| **编排层** | ✅ LangGraph | 编排是"配置"不是"算法"，省时；且是招聘 JD 的关键词 |
| 切片层 | ❌ 自研 | 项目差异化所在，用现成 splitter 就讲不出东西 |
| 检索层 | ❌ 自研 | RRF 融合、版本过滤是实验变量，必须可控 |
| 评测层 | ❌ 自研 | 现成 eval 框架不贴合本项目的分类指标 |
| 语料层 | ❌ 自研 | `Source` / `Converter` 抽象是本项目的架构主张 |

**设计说明**："编排用 LangGraph，因为它解决的是状态管理和条件分支，是配置问题；切片、检索、评测全部自研，因为它们是实验变量，我必须完全控制才能做消融对比。"

> LangGraph 在本项目中**既是编排框架，也是语料来源**（其官方文档）。说明时要讲清是两件事。

---

## 4. 系统架构

### 4.1 模块划分

```
corpus/
  sources/      数据源（v3 新增抽象）  →  LlmsTxtSource / LocalDirectorySource
  converters/   格式转换（可插拔）     →  Converter: Path -> Document
  manifest.py   变更检测与增量更新      →  content_hash 比对、先插后删
chunking/       切片策略（核心）       →  统一接口 chunk(doc) -> list[Chunk]
indexing/       建索引                →  embedding + Qdrant upsert + BM25
retrieval/      检索                  →  双路召回 + RRF 融合 + rerank + 版本过滤
generation/     生成                  →  prompt 组装 + 引用标注 + provenance
agent/          编排层（LangGraph）    →  多步检索状态图
evaluation/     评测                  →  评测集、跑分、报告
```

**分层原则**：`retrieval` 与 `generation` 必须能被**独立调用**（不经过 agent），这是消融实验的前提。`agent/` 是它们之上的编排层，不侵入下层。

### 4.2 数据流

```
configs/sources.yaml
    ↓  scripts/fetch_corpus.py（Source.discover → Converter.convert）
data/raw/<source>/**.md                 （原始文件）
data/manifests/<source>.json            （URL → {content_hash, version, fetched_at}，每源一份）
    ↓  变更检测 + 版本提取
data/corpus.jsonl                       （Document 列表）
    ↓  scripts/build_index.py（调用 Chunker）
data/qdrant/                            （向量索引，payload 含完整 chunk 元数据）
data/bm25_<strategy>.pkl                （BM25 索引）
    ↓  cli.py ask "问题" [--mode pipeline|agent] [--max-age 30d]
检索 → 融合 → rerank → 生成 → 带引用、版本、索引时间的答案
    ↓  scripts/run_eval.py --strategy X --mode Y [--index-stale]
reports/eval-<strategy>-<mode>-<ts>.md
```

### 4.3 核心接口

```python
# corpus/sources/base.py
class Source(Protocol):
    name: str
    def discover(self) -> list[DocRef]: ...      # 产出文档引用
    def refreshable(self) -> bool: ...           # 是否支持自动重新发现

# corpus/converters/base.py
class Converter(Protocol):
    supported: set[str]
    def convert(self, path: Path) -> Document: ...

# chunking/base.py
class Chunker(Protocol):
    name: str
    def chunk(self, doc: Document) -> list[Chunk]: ...

# retrieval/base.py
class Retriever(Protocol):
    def retrieve(self, query: str, k: int = 5,
                 version: str | None = None,
                 max_age: timedelta | None = None) -> list[Chunk]: ...
```

四个接口各自屏蔽一类差异——`Source` 屏蔽数据来源、`Converter` 屏蔽格式、`Chunker` 屏蔽切片策略、`Retriever` 屏蔽检索方案。**都是可替换点，也是消融实验的切换点。**

---

## 5. 数据模型

```python
# src/docsentry/models.py

class SourceKind(str, Enum):
    LLMS_TXT   = "llms_txt"        # 公开文档站，可自动轮询
    LOCAL_DIR  = "local_dir"       # 本地目录，每次索引重扫
    SNAPSHOT   = "snapshot"        # 一次性上传，无法自动同步

@dataclass
class DocRef:
    source: str
    kind: SourceKind
    locator: str          # URL；或 local_dir 的「相对源目录的路径」，如 sub/a.md
    version_hint: str | None

@dataclass
class Document:
    doc_id: str           # sha256(source + locator)[:16]
    source: str
    kind: SourceKind
    version: str          # "2026-07-28"，提取不到为 "unknown"
    url: str              # 展示用来源链接（local_dir 即上面的相对 locator）
    title: str
    path: str
    content: str          # 统一为 Markdown
    content_hash: str
    origin_format: str    # "md" | "pdf" | "docx" | ...
    fetched_at: datetime  # 从源获取的时间
    indexed_at: datetime  # 进入索引的时间  ← v3 新增，provenance 用

@dataclass
class Chunk:
    chunk_id: str          # sha256(doc_id + 序号 + 策略名)[:16]
    doc_id: str
    text: str
    breadcrumb: list[str]
    source: str
    version: str
    indexed_at: datetime   # ← 下沉到 chunk，检索后可直接展示
    url: str
    kind: str              # "prose" | "code" | "table" | "mixed"
    strategy: str
    char_count: int

@dataclass
class Answer:
    text: str
    citations: list[Citation]   # Citation: chunk_id, index, url, version, indexed_at
    mode: str                   # "pipeline" | "agent"
    rounds: int
    staleness_warning: str | None   # ← v3 新增，见 §6.9
```

---

## 6. 模块详细设计

### 6.1 corpus — 语料层

#### 6.1.1 配置

```yaml
# configs/sources.yaml
sources:
  - name: mcp
    kind: llms_txt
    llms_txt: https://modelcontextprotocol.io/llms.txt
    url_include:
      - /docs/
      - /specification/
    keep_all_versions: true

  - name: langgraph
    kind: llms_txt
    llms_txt: https://docs.langchain.com/llms.txt
    url_include: "/oss/python/"
    keep_all_versions: true

  # 私有语料示例（选做）
  - name: internal
    kind: local_dir
    path: ./data/internal_docs
    default_version: "internal-2026Q3"
```

> **`url_include` 必须同时包含 `/specification/`**（2026-09-20 实测修正）：MCP 站点把
> 教程放在 `/docs/`，把协议规范正文放在 `/specification/`，两者各自带日期版本段。
> 只写 `/docs/` 会拿到 110 篇而漏掉全部 111 篇规范正文——而 2026-07-28 协议变更的
> 证据链正在那里。
>
> `/seps/` 与 `/community/` 故意不收录：这两类页面本身不带版本段，收进来只会让版本
> 标注率虚降，且对"查 API 用法"帮助有限。
>
> **`name` 必须是普通标识符**（`^[A-Za-z0-9][A-Za-z0-9._-]*$`，2026-09-22 补）：它同时是
> 目录名（`raw/<name>/`）和文件名（`manifests/<name>.json`），所以 `../x` 或 `a/b` 在 load 期
> 就被拒——与 `paths.py` 的盘符逃逸防护同类，只是提前。

#### 6.1.2 `Source` 抽象（v3 核心改动）

**动机**：v2 的抓取层完全依赖 `llms.txt`，这意味着**私有语料无法接入**（企业内网 Wiki 不会有 `llms.txt`）。

**四类源及其时效性保障方式**（v3 新增，这是本设计的核心主张）：

| `kind` | 系统持有 | 原件变了怎么办 | 自动化 |
|---|---|---|---|
| `llms_txt` | 指针（URL） | 定期重抓 + hash 比对 | ✅ 全自动 |
| `local_dir` | 指针（路径） | **每次索引重扫目录** + hash 比对 | ✅ 全自动 |
| `sitemap`（可选） | 指针（URL） | 同 `llms_txt` | ✅ 全自动 |
| `snapshot` | **副本** | **无法自动感知** → 显式标注新鲜度 | ❌ 做不到 |

**核心主张**：

> **"上传文件"是时效性的敌人。** 上传产生的是快照，快照天然会过期，且系统无从感知源的变化。
>
> 正解是**注册数据源**而非上传副本：系统持有一个**指针**，每次索引时重新读取。这样"同步"问题根本不存在。

**推论**：如果用户的文档在本地目录里，就不该"上传"，而应该注册一个 `local_dir` 源。索引流程每次重扫该目录，内容变了自然被 hash 检测到。

**源的承诺是有边界的：它兑现「重新读取指针」，不兑现「内容和上次一样，或和你要的格式一样」。**（2026-09-22 实测补记）
`docs.langchain.com` 的 `llms.txt` 列着 16 条 `.md` 链接，但站点对它们返回 `200 text/html`——SDK
reference 转储、changelog、academy 落地页，站点根本没有这些页面的 markdown 版本。照单全收的后果是
语料里混进 13.4 MB 的应用外壳，**占全部正文字节的 48%**，而语料是"按 Markdown 构造"的；其中 4 条还内嵌
per-request CSRF token，字节每次都变，于是幂等性也永远不成立。
**因此 `Fetched` 把服务器的 `Content-Type` 一起带上来，由管线（不是源）决定收不收**：不是 markdown 就
记为一次失败——写进报告的失败清单，和 404 并列。丢弃是诚实的：这些页面确实不以 markdown 提供。

**因此明确不做常驻文件监控**（watchdog）：索引是定期/手动触发的批处理，每次触发时重扫目录即可，无需常驻进程。**更简单，且足够。**

#### 6.1.3 `llms.txt` 递归解析

1. 下载 `llms.txt`
2. 解析行格式 `- [title](url): description`
3. **条目 URL 以 `llms.txt` 结尾 → 子索引，递归展开**（`docs.langchain.com` 即此形态），最多 2 层，用已访问集合防环
4. 收集 `.md` 结尾条目；目录项（以 `/` 结尾）跳过
5. **同一文件内两种形态可能并存，按文件二选一是错的**：`docs.langchain.com` 顶层既有 58 个 `llms.txt` 子索引（`### Section indexes` 下），又有 119 条直连 `.md`（散在 `## Docs` / `## Open source` / `## LangSmith Fleet` / `## Agent Server API`），两条路都要走
6. **按 URL 去重后再交给上层**：MCP 的 `llms.txt` 实测 352 条链接 / 347 唯一
7. **索引会列站点并不以 markdown 提供的页面**（2026-09-22 实测）：LangChain 的 539 条 `.md` 里 16 条
   实际返回 `200 text/html`。**递归解析照常收下它们**——解析器只看 URL 形态；格式的裁决在抓取层，
   见 §6.1.2 的 `Content-Type` 拒收。

**子索引会重组**：上表第 5 条记的"58 个子索引 + 119 条直连"是 2026-09-20 的观测。2026-09-22 再测时，
`/oss/python/` 已从一个大索引拆成 8 个平级子索引（`/oss/python/llms.txt` 369 条 + concepts 4 +
contributing 8 + deepagents 40 + langchain 76 + langgraph 43 + migrate 4 + releases 3，去重后 539）。
**递归展开因此必须按结构做，不能按"当初那份索引长什么样"做**——这也是为什么 M1 的验收测试断言的是
"递归发生过"而不是"总数等于 369"。

#### 6.1.4 增量更新（v3 修正为"先插后删"）

**变更检测**：`data/manifests/<source>.json` 记录**该源**每个 locator 的 `content_hash` / `version` / `fetched_at`。

**每个源一份，不共用。**（2026-09-22 实测修正）manifest 不只是"我们有什么"的缓存，它同时是**删除基线**
（`vanished = manifest 记得的 locator - 本次发现的 locator`）。一份共享的文件会让每个源都把别人的页面
读成"已消失"：删掉它们的条目、把别人的页数记成 `deleted`，而因为这些条目没了，下一次运行又把它们当成
全新页面重新写入。实测两源共用一份时，第二次运行报 `mcp added=252 deleted=538` /
`langgraph added=538 deleted=252`，两者**都永远不幂等**，且 manifest 最终只剩最后一个源的条目
（`health.py` 因此只能看到一半语料）。raw 文件本身是安全的——`_forget` 推出的路径在对方源的子树下，
那儿什么都没有——**被毁的是记录，不是数据**，所以这个缺陷不会自己暴露。

```
Source.discover()
  ↓
locator 集合 diff  →  新增 / 删除 / 保留
  ↓
保留项重新读取 → content_hash 比对  →  未变(跳过) / 已变(标记更新)
```

**同步顺序（v3 修正）**：

```
① 新内容切片 → upsert 新 chunk          ← 此步完成时索引已含新内容
② 按 doc_id 查出该文档全部 chunk_id
③ 删除「不在新 chunk_id 集合中」的旧 chunk
```

> **为什么是"先插后删"而不是"先删后插"**
>
> v2 写的是先删后插。缺陷：删除完成、插入失败时，**索引出现空洞且无人知晓**。
>
> 改为先插后删后：过程中新旧共存，**任何时刻索引都是完整可用的**；中途失败最多留下冗余，不会丢数据；孤儿 chunk（文档变短时遗留的旧 chunk）照样在步骤 ③ 被清理。

**版本演进**：`keep_all_versions: true` 时新旧版本共存于索引，chunk 各带 `version` 标签，检索时可按版本过滤。这支撑"版本感知"这一差异化卖点。

**BM25 索引**：内存索引增量更新复杂度高、收益低——直接全量重建（几千 chunk 秒级完成）。

**幂等性**：`fetch_corpus.py` / `build_index.py` 均可重复运行，结果一致。

#### 6.1.5 可观测性与触发（v3 新增）

**最大的风险不是"更新慢"，而是"你以为更新了，其实某个源抓失败了，索引缺内容是静默的"。**

**抓取报告**（每次运行输出 + 落盘 `reports/fetch-<ts>.json`）：

| 字段 | 含义 |
|---|---|
| `added` / `updated` / `skipped` / `deleted` | 各状态文档数 |
| `failed` | **失败清单（附 locator 与错误原因）** |
| `duration` | 耗时 |

**索引健康检查**（`scripts/health.py`）：

- 每个文档的 `version` + `indexed_at` 清单
- **陈旧清单**：索引中的 version vs 源站当前 version 的差异
- 超过 N 天未校验的文档告警

**触发**：

- 手动：`uv run scripts/fetch_corpus.py --update`
- 定时：**Windows 计划任务**调用同一命令

### 6.2 converters — 格式转换（可插拔）

| 实现 | 优先级 | 依赖 | 说明 |
|---|---|---|---|
| `MarkdownConverter` | **必做** | 无 | 直接读取 |
| `PdfConverter` | 选做 | `pymupdf4llm` / `markitdown` | 仅文字版 PDF |
| `OfficeConverter` | 选做 | `markitdown` | docx / pptx / xlsx |
| `ImageConverter` | 选做 | VLM API | 生成图片描述入索引 |

#### 6.2.1 MarkdownConverter 的三处归一化（实测依据）

除直读外它还做三件事，都不是"顺手清理"：

**剥除页首 `> ## Documentation Index` 样板块。** MCP 与 LangChain 的每一页都带它（真实抽样 30/30 命中），实测长 **186 字符**、跨文档逐字节相同。

它的成本**不在总量，在位置**：

| 口径 | 实测值 |
|---|---|
| 占语料总量 | **0.53%**（页面平均约 35 KB，样板块是固定成本） |
| 占首个 chunk（`target_size = 1000`） | **18.6%** |

- 报告与答辩只应引用"**位置**"这条：它落在每个文档的头部，把每篇首 chunk 的 embedding 朝同一方向拉。总量 0.53% 是个经不起追问的数字。
- **不宜声称"对 BM25 是高频干扰项"**：IDF 恰好把"出现在每个文档里"的词压到近零，高频正是它设计上要降权的东西；残留成本只有长度归一化带来的轻度稀释。
- **剥除必须在切片之前**：`structural` 按标题层级切分时，样板块位于首个标题之前，可能自成一块纯样板 chunk——切完再剥就晚了。管线顺序（fetch → convert → chunk）已保证这一点。

**从首个标题提取 `title`**，跳过围栏代码块——否则 shell 片段里的 `#` 注释会被当成标题。`llms_txt` 源已自带标题，这一步是让裸 `local_dir` 也能用。

**展开 MDX 布局容器**（2026-09-24 新增，M2 设计期间发现）。

MCP 与 LangChain 都用 Mintlify 式的 MDX 容器组织内容（`<Tabs>` / `<Tab title="X">` / `<CodeGroup>`），
容器内的正文缩进 4–6 空格，**CommonMark 把它读成缩进代码块**。后果三层：标题对解析器不可见、
`kind` 被判成 `"code"`、第 6 步的原子规则把它整块保护起来。

**影响面实测**：**1,235,578 字符 = 语料的 8.5%**，涉及 **211 篇**文档（MCP 1,106,054 + LangChain 129,524）。
受影响的几乎全是 **MCP 的教程核心页**——`build-client.md` 在解析器眼里只有 **2 个标题**，
而正文里实际有上百个。**这是必须修而不能记为已知限制的原因：评测的 `api` 类问题大概率命中它们，
而切片的收益本来最该在那类题上体现。**

处理规则：

1. 识别布局容器并按**嵌套层级** dedent（不是固定减 4——`<CodeGroup>` 嵌在 `<Tab>` 里是两层）
2. 带 `title` 的容器**重写成合成标题**，层级取容器内最浅标题，容器内所有标题相应 +1。
   于是 `<Tab title="Python">` 内的 `## System Requirements` 成为 `### System Requirements`，
   breadcrumb 得到 `Build an MCP client > Python > System Requirements`
3. 剥语义标签留文本（`<Note>` / `<Warning>` 等）

> **第 2 条是必需的**：`build-client.md` 的教程在 **7 个语言 Tab 里重复了 7 遍**
> （Python / TypeScript / Java / Kotlin / C# / Ruby / Rust）。不区分的话 top-5 会被 7 个近乎相同的
> chunk 占满。带上语言标签后它们可区分、可过滤，对开发者支持场景是**加分而非负担**。

> ⚠️ **必须防的假标题**：朴素 dedent 会把围栏代码块内的 shell 注释（`# Create virtual environment`）
> 顶到行首、被读成 **H1**。实测 `build-client.md` 因此从 2 个标题"暴涨"到 132 个，其中混着大量假标题。
> **dedent 必须跟踪围栏状态**，围栏内的内容与围栏一起整体平移。这条要有专门的测试钉住。

理由与完整证据见 [M2 设计文档](2026-09-24-m2-chunking-design.md) §3。

> **改了 converter 不需要失效机制**：`content_hash` 是**原始字节**的哈希，而
> `converter.convert(raw_path)` 每次运行都会重跑（`corpus/pipeline.py`），所以重跑
> `fetch_corpus.py --update` 就会重建 `corpus.jsonl`。代价是全量重抓（约 2,370 次请求、实测 4 分 57 秒）。

**多格式对私有语料是刚需**：私有语料格式更脏（PDF/Word/扫描件多），这不是"为了支持而支持"。

**明确不做完整多模态**：ColPali 类视觉检索（约 5 天）在本场景收益低——开发者支持场景的图片主要是架构图与报错截图，VLM 生成 caption 入索引即可覆盖，成本约为其 1/5。

所有转换器须正确标注 `Document.origin_format`，以便评测时按格式分析。

### 6.3 chunking — 切片策略（核心）

三种实现，同一接口。

**公平性约束（实验有效性的前提）**：三者共享同一 `target_size`（默认 1000 字符，见 `configs/chunking.yaml`）。**差异只体现在"切在哪里"，而非切多大。** 若尺寸不同，准确率差异无法归因于切片策略本身。

评测报告公布三策略的**平均 chunk 尺寸、中位数、chunk 总数、以及总索引字符数**，自证对比公平。

> **2026-09-24 实测修正（overlap 的披露）**：`fixed` 的 `overlap=200` 让它的索引字符总量达到语料的
> **1.24×**，而 `semantic` / `structural` 切在天然边界上、无重叠，是 **1.08×** 与 **1.06×**。
> **这个差异不消除，但必须披露。**
> 原文只要求公布"平均尺寸与总数"，漏掉了会随 overlap 变化的"总索引字符数"。
> 理由（为什么不给另两个也加 overlap）见 [M2 设计文档](2026-09-24-m2-chunking-design.md) 决策 4。
>
> 附注：另两个不是 1.00× 而是**超过**语料——原子单元强制降级切分时表格子块重复表头行，
> 这是与 overlap 无关的第二条"索引量 > 语料"路径。同上 §决策 4。

> **2026-09-24 实测修正（原子单元的上限）**：原文允许 `structural` 的原子单元（超长代码块 / 表格）
> 无限超出 `target_size`，只要求"报告中记录实际尺寸"。照字面实现，实测产出 **106,728 字符**的单 chunk
> （LangChain 的 "All tools and toolkits" 表格，99% 表格内容），另有一批 80,000–90,000 字符的
> （MCP 的 `build-server.md` / `build-client.md` 各 6 个版本）。这类 chunk 会**静默失效**——
> embedding 按模型输入上限截断，prompt 装不下，超出部分等于不存在。
> **改为硬上限 `max_atomic_size`（默认 4000），超过必须降级切分并标记 `split_atomic=True`。**
> 见 M2 设计文档决策 2。

#### 6.3.1 FixedSizeChunker（基线）

按字符数硬切，`target_size=1000, overlap=200`。不做任何结构判断，会切断代码块和段落。

#### 6.3.2 SemanticChunker（中间基线）

按段落边界（`\n\n`）累积到 `target_size` 后切分，不切断段落。仍不看标题层级。

> **2026-09-24 实测修正（`max_atomic_size` 是系统级规则，不只属于 `structural`）**：原文的
> "不切断段落"照字面实现后，实测 **288 个 chunk（2.20%）超过 4,000 字符**，占 semantic
> 索引字符总量的 **21.5%**，最大一个 **106,158**。这类 chunk 与 §6.3.3 step 6 修掉的是**同一个
> 失效模式**：embedding 按模型输入上限截断，超出部分等于不存在。同时它让消融实验里的一部分
> 变成在比"谁截断得多"而不是"谁切在哪里"。
>
> §6.3.3 的决策 2 已经确立先例（`structural` 的"代码块绝不切断"让位给了可嵌入性），同一条
> 理由对 `semantic` 一样成立。故上限**提升为系统级规则**：`semantic` 同样对超过
> `max_atomic_size` 的块强制降级切分并标记 `split_atomic=True`。**普通多段落文本行为完全不变**
> （仍按段落切、不标记），上限只在真正的超长块上生效。
> 落地后 semantic 的索引总量从 1.00× 升到 1.08× 语料、chunk 数从 13,088 升到 14,651，
> 触及 774 篇中的 57 篇，其余 717 篇逐字节不变。详见
> [M2 设计文档](2026-09-24-m2-chunking-design.md) 决策 2。

#### 6.3.3 StructuralChunker（核心）

用 `markdown-it-py` 解析 token 流：

1. 遍历 token 流，维护标题栈 `stack: list[(level, text)]`
2. 遇 `heading_open` → 弹出栈中 `level >= 当前` 的项，压入当前标题
3. 遇内容 token → 归属**当前栈顶 section**
4. **flush-on-close**：正文累积在栈顶；遇到关闭当前标题的新标题时，**先发出这段正文再弹栈**。发出 chunk 的 `breadcrumb = [t for _, t in stack]`
5. section 正文超过 `target_size` 时：按段落二次切分为子 chunk，**每个子 chunk 继承相同 breadcrumb**，`chunk_id` 加序号
6. **原子单元与硬上限**：代码块（`fence`）与表格整体不切断；但超过 `max_atomic_size`（默认 4000 字符）时**必须降级切分**——表格按行切且**每个子块重复表头**，代码块按空行 + 顶层 `def`/`class`/`function` 边界切（启发式，代码中注明局限）——并标记 `split_atomic=True`
7. `kind` 判定：代码块占比 > 70% → `"code"`；表格 > 70% → `"table"`；皆有 → `"mixed"`；否则 `"prose"`
8. **不合并小碎片**：一个 section 一个 chunk，即使只有几十字符。仅当正文剥掉 HTML 标签与空白后为空时丢弃，**丢弃数进报告**

> **2026-09-24 实测修正（step 3 / 4，最重要的一处）**：原文写"归属当前**叶子** section"、
> "每个**叶子** section 合并为一个 chunk"。按字面实现，**非叶节点自己的正文不会成为任何 chunk**：
> 实测丢掉 **2,618,528 字符 = 语料的 18.0%**（flush-on-close 得 16,695 chunks，只发叶子得 13,650 chunks，
> 两者均值都是 857）。**这三个数是规划期在 MDX 归一化之前的语料上测的**；归一化之后
> flush-on-close 的当前输出是 18,442 chunks / 均值 805（M2 设计文档开头表格）。
> 损失量在归一化后会缩小，但**规则不变**——它针对的是普遍情形，不是某一个极端样本。
>
> 最严重的一例是 `build-client.md`：全长 2,522 行**只有两个标题**（第 5 行 `# Build an MCP client`、
> 第 2516 行 `## Next steps`），那 80,448 字符的完整教程挂在**父**节点下 —— 按字面实现产出的 chunk
> 是 "Next steps" 那 172 个字符，**MCP 最核心的教程页整页检索不到**。同类还有 `build-server.md`
> （89,755 × 6 版）、`deepagents/overview.md`（49,873）等，非叶正文超 500 字符的有 772 个。
>
> **"叶子"这个词是这处缺陷的根源**：正文属于"它所在的 section"，不属于"最终没有子标题的那个 section"。

> **2026-09-24 实测补充（step 8）**：flush-on-close 之后 31.4% 的 chunk 小于 500 字符（10.1% 小于 200）。
> **抽样 18 条后确认这些不是碎片而是精确的 API 片段**（如 `Chroma integration > Manage vector store >
> Delete items from vector store`，179 字符），正是开发者提问的粒度；合并反而会破坏 breadcrumb 精确性，
> 而实现完成之后的实测均值是 974 / 1034 / 805（fixed / semantic / structural），
> 全部落在 `target_size` 的 ±25% 区间内。故**不合并**。

**降级路径**：解析失败（畸形 Markdown）时退回 `SemanticChunker` 并记录警告。

**测试要点**（`tests/test_chunking.py`）：代码块不被切断 / 三级标题 breadcrumb 长度为 3 / 超长 section 子 chunk 均带 breadcrumb / 三策略 chunk 数量关系合理（不做精确断言）/ **非叶 prelude 不被丢弃** / **超 `max_atomic_size` 的表格子块重复表头** / **纯噪声 chunk 的丢弃数被计入报告**。

公平性检查是**一个真的会跑的产物**（不是测试里的断言）：三策略均值**均落在 `target_size`
的 ±25% 内**，并输出均值 / 中位数 / chunk 总数 / 总索引字符数 / **均值最差对的比值**。

> **2026-09-24 实现期修正（判据从"两两比值 ≤ 1.30"改为区间）**：规划期实测最差对是 **1.34×**
> （semantic 1072 / structural 802）——没有任何东西出错，却不及格。根因是 §6.3.3 step 8
> 的不合并决定拉低了 `structural` 的均值：**两个各自成立的决定在一个数字上撞车了**。
> 实验真正需要的只是"尺寸不至于成为分数差异的主因"，区间直接陈述这一点；比值是它的差代理。
> **1.34× 仍如实公布**，不是把阈值调到过关。
> 实现完成后的实测是 **1.29×**（974 / 1034 / 805），已经低于原来那个 1.30 门槛——
> **但判据不是因此才改的**，改判据的依据是上面那段论证。详见
> [M2 设计文档](2026-09-24-m2-chunking-design.md) §6.2。

**断言按区间/比值定，不写死绝对数**——语料本身在动
（LangChain 的索引结构 2026-09-20 → 09-22 就重组过一次，369 → 539 篇）。

### 6.4 indexing — 建索引

**向量索引**：

- `sentence-transformers` 加载 `BAAI/bge-m3`，batch=16
- BGE 系列 query 侧需加前缀 `"Represent this sentence for searching relevant passages: "`，document 侧不加
- Qdrant local mode：`QdrantClient(path="./data/qdrant")`
- payload 存完整 `Chunk` 字段（含 `indexed_at`，支持过滤与取回）
- collection 名含策略名：`docsentry_structural` / `docsentry_fixed` / `docsentry_semantic`

**BM25 索引**：`rank_bm25.BM25Okapi`；英文按 `\W+` 切并小写，含中文段落用 `jieba.lcut`；持久化 `data/bm25_<strategy>.pkl`。

### 6.5 retrieval — 检索

`HybridRetriever.retrieve(query, k=5, version=None, max_age=None)`：

1. 向量召回 top-20（Qdrant，`version` / `max_age` 非空时加 payload 过滤）
2. BM25 召回 top-20
3. **RRF 融合**：`score = Σ 1/(60 + rank_i)`，取 top-10
4. **Rerank**：`bge-reranker-v2-m3` 重排，取 top-k
5. 返回 `list[Chunk]`

**降级开关**：`use_bm25` / `use_rerank` 配置项，支持消融，也用于工期紧张时砍功能。

### 6.6 generation — 生成

**Prompt 结构**：

```
[system]
你是开发者支持助手。只依据提供的材料回答，材料不足时明确说"文档中没有找到"。
每个论断用 [n] 标注来源。若材料含多个版本，指出你依据的版本。

[user]
材料：
[1] (MCP > Server Concepts > Resources | version=2026-07-28 | indexed=2026-09-18)
<chunk text>

[2] ...

问题：{question}
```

**关键点**：材料中不只给 chunk 文本，**必须带 breadcrumb、version、indexed_at**——这是本项目的核心假设，也是评测要验证的变量。

**参数**：`temperature=0`（评测可复现性要求）。

### 6.7 agent — 编排层（LangGraph）

#### 6.7.1 状态图

```python
class AgentState(TypedDict):
    question: str
    query_type: str            # factual | api | cross_doc | version
    queries: list[str]
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
┌─→│ retrieve │  调用 HybridRetriever（带版本/时效过滤）
│  └────┬─────┘
│       ↓
│  ┌──────────┐
│  │  assess  │  材料是否足够回答？
│  └────┬─────┘
│       │
└───┬───┘  不足且 rounds < max_rounds(3)
    │
    │ 足够 或 达上限
    ↓
┌──────────┐
│ generate │  生成答案 + 引用标注
└────┬─────┘
     ↓   END
```

**为什么不是硬凑**：开发者支持场景中，"MCP 和 LangGraph 状态管理的区别"这类跨文档问题单次检索必然召不全；`assess` 节点判断材料充分性、不足则改写查询再检索，是真实需要的能力。`max_rounds=3` 防止无限循环与成本失控。

#### 6.7.2 消融实验

`agent/` 不侵入下层，因此可干净对比：

| 模式 | 流程 |
|---|---|
| `pipeline` | analyze → retrieve → generate（单次检索） |
| `agent` | 完整状态图（多步 + 充分性判断） |

**对比指标**：准确率（分问题类型）、平均检索轮数、token 成本、延迟。

**预期需实验验证，不能预设结论**：agent 模式在 `cross_doc` 类应有提升，在 `factual` 类可能持平但成本更高。**若结果与预期不符，如实报告**——"agent 编排在此场景性价比不高，数据是……"比强行证明 agent 有用更有说服力。

### 6.8 evaluation — 评测

#### 6.8.1 评测集

**50 题四类均衡**（每类 12–13 题）：

| 类型 | 考察点 | 例 |
|---|---|---|
| `factual` | 基础召回 | "MCP 的 Roots 是什么？" |
| `api` | 代码块完整性 | "怎么注册一个 tool？" |
| `cross_doc` | 多跳检索 | "MCP 和 LangGraph 的状态管理有什么区别？" |
| `version` | **版本与时效** | "新版 MCP 为什么取消了握手？" |

**构建流程**（必须可辩护）：

1. `scripts/gen_questions.py`：按 section 采样，LLM 生成候选问题 + 参考答案 + 出处 URL
2. **人工筛选修正**：删除语料覆盖不到的、答案有歧义的、不检索也能答的常识题
3. 每题标注 `gold_urls`
4. 落盘 `evalset/evalset.jsonl`

**明确不做**：不使用全自动生成 + 全自动评判的闭环。生成可用 LLM 加速，但筛选与答案校准必须人工做过。

#### 6.8.2 指标

| 指标 | 定义 | 计算 |
|---|---|---|
| `answer_accuracy` | 答案正确率 | LLM-judge 三档（correct=1 / partial=0.5 / wrong=0），`temperature=0`，每题评 2 次，不一致转人工仲裁 |
| `recall@5` | 检索召回率 | `gold_urls` 是否在 top-5 结果的 url 集合中 |
| `citation_accuracy` | 引用准确率 | 抽 20 题人工核查 `[n]` 是否支持论断 |
| `version_accuracy` | **版本正确率** | **在 `version` 类题上，答案依据的是否为当前版本**（v3 新增） |
| `index_freshness` | 索引新鲜度 | 索引中 version vs 源站当前 version 的差异比例（v3 新增） |
| `avg_rounds` / `avg_tokens` / `avg_latency` | 成本指标 | agent 消融实验必需 |

**人工抽查**：`answer_accuracy` 随机抽 20%（10 题）人工复核，报告公布 LLM-judge 与人工的一致率——这本身是可信度指标。

#### 6.8.3 时效性三组对比实验（v3 新增，核心产出）

同一评测集，三组对照：

| 组 | 设置 | 模拟的现实问题 |
|---|---|---|
| **A. 模型直答** | 不检索，直接问 LLM | 用户直接开 Claude 问 |
| **B. 过期索引** | 用**旧版本**语料建索引 | **索引未同步**的真实事故 |
| **C. 最新索引** | 本项目系统 | — |

**A、B、C 在 `version` 类问题上的准确率差 = 时效性的价值量化。**

B 组是关键——它模拟的是"文档更新了但索引没同步"这个真实且常见的事故。

> 实现方式：`--index-stale` 参数指向一份用旧版语料构建的索引快照。语料可用 MCP 的历史版本（`/docs/<旧日期>/` 路径下的文档）。

#### 6.8.4 跑分与报告

```bash
uv run scripts/run_eval.py --strategy structural --mode agent --limit 50
```

输出 `reports/eval-<strategy>-<mode>-<ts>.md`：

- **汇总表**：全部指标 × 三策略 × 两模式，附各策略平均 chunk 尺寸与总数（证明对比公平）
- **分类别拆分**：四类问题各自准确率（**最有价值的分析**）
- **时效性三组对比**：A/B/C 在 `version` 类上的差异
- **逐题明细**：问题、模型答案、参考答案、是否命中、引用
- **失败案例分析**：按原因归类（未召回 / 召回但答错 / 引用错误 / 拒答 / **依据过期版本**），每类给 2–3 个具体例子

### 6.9 数据新鲜度与 provenance（v3 新增）

**问题**：并非所有数据源都能自动同步。`snapshot` 类源（同事发来的 PDF、别人给的 Word）**系统无从感知原件变化**。

**原则**：

> **做不到全自动，就不假装能做到。把限制显式暴露给用户，远好于静默返回过期答案。**

**机制**：

1. **元数据下沉**：每个 chunk 携带 `version` + `indexed_at`，检索后直接可用
2. **答案标注**：每条答案的来源列表展示 `版本` 与 `索引时间`
3. **陈旧告警**：检索结果中的 chunk 若 `indexed_at` 超过阈值（默认 90 天），在答案中插入 `staleness_warning`
4. **时间过滤**：`retrieve(max_age=...)` 支持"只要 N 天内的内容"

这在企业场景中对应 **data lineage / provenance** 概念。

### 6.10 数据安全边界（v3 新增）

私有语料场景下企业最关心的问题：

| 关注点 | 方案 | 本项目状态 |
|---|---|---|
| **数据不出域** | embedding 本地推理 | ✅ 已选本地 bge-m3——**不只是省钱，是合规优势** |
| **LLM 调用外发** | 仅发送检索到的片段，不发送全库；配置项支持切换本地 Ollama 完全离线 | ✅ 架构支持，需补开关 |
| **权限隔离** | 检索层加 ACL 过滤 | ❌ 明确不做（见 §8.4） |
| **审计日志** | 记录谁问了什么、检索到什么 | ❌ 明确不做 |
| **不可信输入写盘** | locator→路径推导先按段清洗，再由 `ensure_within` 兜底 | ✅ M1 已实现 |

**设计说明（权限隔离）**："企业场景需要按角色过滤检索结果，实现上是在检索层加 ACL 过滤条件——我的 `retrieve()` 已支持版本和时间过滤，加权限过滤是同一套机制。我两周内没做，因为判断把时间花在验证切片策略的量化收益上更有价值。"

**设计说明（不可信输入）**：`llms.txt` 是远端文件，等同不可信输入——它可以把 `../` 或 Windows 非法字符塞进 URL 路径。所有写盘与删除前都要过 `raw_relpath` 清洗 + `ensure_within` 越界兜底。**实测教训：清洗必须发生在构造 `Path` 之前。** Windows 下 `:` 是盘符分隔符，`Path("example.com") / "a:b*c"` 求值为 `a:b*c`，主机段被整个丢弃——`https://a.example.com/x:y.md` 与 `https://b.example.com/x:y.md` 于是推出相同路径，"两 host 不撞"的保证静默失效。先构造再清洗就太晚了。

---

## 7. 目录结构

```
docsentry/
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── configs/
│   ├── sources.yaml
│   └── chunking.yaml
├── src/docsentry/
│   ├── config.py
│   ├── models.py
│   ├── corpus/
│   │   ├── sources/
│   │   │   ├── base.py
│   │   │   ├── llms_txt.py
│   │   │   └── local_dir.py
│   │   ├── converters/
│   │   │   ├── base.py
│   │   │   └── markdown.py
│   │   ├── manifest.py        # 变更检测 + 先插后删
│   │   └── versioning.py
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
│   │   └── graph.py
│   └── evaluation/
│       ├── evalset.py
│       ├── judge.py
│       └── report.py
├── scripts/
│   ├── fetch_corpus.py
│   ├── build_index.py
│   ├── health.py              # 索引健康检查
│   ├── gen_questions.py
│   └── run_eval.py
├── cli.py
├── evalset/evalset.jsonl
├── reports/
├── tests/
└── docs/superpowers/specs/2026-09-18-docsentry-design.md
```

**`.gitignore`**：`data/`、`.env`、`.venv/`、`__pycache__/`。**`evalset/evalset.jsonl` 必须提交**——核心劳动成果的证明。

---

## 8. 范围与优先级

### 8.1 必做（护城河，约 12 天）

语料层（Source 抽象 + 增量更新 + 可观测性）/ 切片策略（三策略）/ 检索 / 生成 + provenance / 评测 + 跑分 / 时效性三组对比 / 失败分析

**别人抄不走——它是"实验"不是"功能"。**

### 8.2 应做（编排层，约 2 天）

LangGraph 编排层 + pipeline vs agent 消融。

### 8.3 选做（各 0.5–1 天）

| 项 | 收益 |
|---|---|
| PDF / Office 转换器 | "支持多格式"关键词；私有语料刚需 |
| 图片 VLM caption | "多模态"关键词 |
| Streamlit 对话界面 | 演示更好看 |
| `LocalDirectorySource` | 私有语料能力演示 |

### 8.4 明确不做（附理由）

| 不做 | 理由 |
|---|---|
| 完整多模态视觉检索（ColPali） | 约 5 天，本场景收益低，VLM caption 即可覆盖 |
| Web 上传 UI | 上传产生快照，与时效性主张相悖（见 §6.1.2） |
| 常驻文件监控（watchdog） | 批处理重扫目录即可，无需常驻进程 |
| 权限隔离（ACL） | 有价值但非本期重点；能讲清取舍即可 |
| 审计日志 | 同上 |
| 用户系统 / 鉴权 / 多租户 | 偏离定位 |
| 部署上线 / Docker / CI | 与核心命题无关 |
| 模型微调 | 与本项目命题无关 |
| 文档源扩张 | 先做通 MCP + LangGraph |

### 8.5 已知限制（v3 新增）

**主动声明**：

| 限制 | 说明 |
|---|---|
| `snapshot` 源无法自动同步 | 系统无从感知原件变化，只能显式标注新鲜度 |
| 权限变更不感知 | 文档权限改了，索引中的 chunk 不会自动失效，存在越权检索风险 |
| 删除依赖源可发现 | URL 源可通过 diff 感知删除；`snapshot` 源只能由用户主动删除 |
| 单文件解析质量依赖转换器 | PDF 转换可能出现乱码、表格错位，未做逐格式质量校验 |
| 评测集规模有限 | 50 题不足以覆盖所有文档类型，指标存在置信区间 |

### 8.6 工期不足时的砍功能顺序

**严格按此顺序**：

1. 选做四项（PDF / 图片 / UI / LocalDirectorySource）
2. `rerank`（降级为纯 RRF 融合）
3. `BM25`（降级为纯向量检索）
4. 时效性三组对比（保留 A/C 两组，砍掉 B 组）
5. agent 编排（降级为 pipeline 单次检索）
6. 评测集 50 → 30 题

**核心切片实验（三策略对比）最后砍。** 只要它在，项目就是完整的；它没了，项目就废了。

> **D11 中期检查点**：评估进度，落后则当场按序砍，不要拖到最后崩盘。

---

## 9. 里程碑

| 里程碑 | 截止 | 验收标准 |
|---|---|---|
| M1 语料层 | D3 | `Source` 抽象（llms_txt + local_dir）可用；两源 ≥400 篇 `.md`（实测 774）；**每源一份 manifest**，增量更新（先插后删，含崩溃测试）可运行且跨源幂等；**非 markdown 页面按 `Content-Type` 拒收并记入失败清单**；抓取报告输出含失败清单与 `dated`/`draft`/`unknown` 三分项；**被纳入索引的 MCP 页面版本标注率 ≥90%**（实测 252 篇 → 100%：198 日期 + 54 draft） |
| M2 切片策略 | D6 | 三种 Chunker 实现 + 测试通过 + 平均尺寸一致性检查通过 |
| M3 检索可用 | D7 | 索引构建完成，CLI 返回带来源的检索结果 |
| M4 生成完成 | D8 | CLI 返回带引用、版本、索引时间的答案 |
| M5 agent 编排 | D10 | LangGraph 状态图完成，两种模式均可运行 |
| M6 评测跑分 | D13 | 50 题评测集完成；三策略 × 两模式对比报告；时效性三组对比报告；失败案例分析 |
| M7 交付 | D14 | README + demo + 设计决策说明 |

**排期说明**：本排期为压缩版，**实际很可能需要 16–18 天**。若必须 14 天完成，按 §8.6 砍功能。建议 D11 做一次中期检查。

**中期检查点（D11）**：评估进度，必要时按 §8.6 砍。

---

## 10. 风险与应对

| 风险 | 概率 | 应对 |
|---|---|---|
| 某源 `.md` 不可下 | 低（已实测） | 降级：`git clone` 官方文档仓库取 `docs/` |
| bge-m3 本地推理太慢（CPU） | 中 | 降级 `bge-small-en-v1.5`；或离线批量编码 + 缓存 |
| 评测集构建超时 | **高** | 先做 30 题保底，D12-13 补足 50；报告注明题量 |
| LLM-judge 不稳定 | 中 | `temperature=0` + 每题评 2 次 + 人工抽查 20% 并公布一致率 |
| LangGraph 学习成本超预期 | 中 | D11 中期检查评估；必要时降级为手写循环（保留 agent 语义，只是不用框架） |
| MCP 历史版本语料不可得（影响 B 组） | 低 | 若旧版文档不可访问，B 组改用"人为截断语料"构造 |
| 工期不足 | **高** | 按 §8.6 顺序砍；**核心实验最后砍** |
| 本地跑不动 embedding | 低 | 切云端 embedding API，架构不变 |

---

## 11. 交付材料（D14 产出）

README 必须包含：

1. **一句话说清项目**：面向开发者的技术文档支持 Agent——研究"当语料是模型知识盲区时，检索该怎么做"
2. **架构图**（Mermaid）
3. **实验数据表**：三策略 × 两模式 × 全指标；时效性 A/B/C 三组对比
4. **失败案例分析**：至少 3 个具体例子，说清原因与改进方向
5. **已知限制**：§8.5 的内容，主动声明
6. **快速开始**：`uv sync` → 抓语料 → 建索引 → 提问，三步内跑起来
7. **设计取舍**：为什么编排用 LangGraph 而切片自研、为什么 BM25 和向量都要、为什么不做上传 UI

**常见问题与设计决策说明**：

- 为什么编排用 LangGraph，切片却自己写？
- 结构切片具体在哪一类问题上提升？为什么？
- **agent 编排比单次检索强多少？值得吗？**（用数据回答）
- 评测集怎么保证客观？LLM-judge 可信吗？
- **如果文档更新了，你的索引怎么同步？**（答案：Source 抽象 + 先插后删 + 可观测性）
- **用户上传的文件原件更新了怎么办？**（答案：上传是伪需求，应注册数据源；快照型源显式标注新鲜度）
- 模型直接问也能答，为什么还需要你的系统？（答案：时效性 + 私有语料 + 可追溯，并用 A/B/C 实验数据支撑）
- 这个方案在什么情况下会失效？（答案：§8.5 已知限制）
- 你的项目和企业知识库项目（如 ragent）区别在哪？（答案：场景不同、数据不同、难点不同，且我有量化实验）

**关键设计决策回顾**：

> 我最初设计的上传 + 哈希比对方案有个漏洞：上传产生的是快照，源更新了系统并不知道。我把它改成"注册数据源"模型——URL 源自动轮询，本地目录每次索引重扫，快照型源则显式标注新鲜度。**这个修正来自我自己推演出的反例。**
