# docsentry — M2 切片策略设计文档

- 日期：2026-09-24
- 状态：设计通过，待实现
- 上游：[`2026-09-18-docsentry-design.md`](2026-09-18-docsentry-design.md)（主设计文档）
- 里程碑：M2 切片策略（主设计文档 §9）

> 本文件展开 M2 的设计，并**修正主设计文档的五处**（§6.3.3 四处 + §6.2.1 一处）。修正原因全部来自
> 在真实语料（774 篇）上做的实测，不是推演。修正随本文件一并合入；在那之前，冲突以本文件为准。
>
> **本文件中的全部数字都是在 MDX 归一化（§3）尚未实现时测得的。** §3 落地后语料会变，
> 届时重测并把新数字填回本文件与 README。**验收断言按比值定，不写死绝对数**——语料本身也在动
> （LangChain 的索引结构 2026-09-20 → 09-22 就重组过一次）。

---

## 1. 范围

**交付**：三种 Chunker（`fixed` / `semantic` / `structural`）+ 公平性检查 + 测试 + 验收。

**不含**：建索引（M3）、检索（M3）、生成（M4）。

**但包含一项前置修订**：corpus converter 的 MDX 归一化（§3）。它是 M2 设计期间发现的
语料层缺口，影响 8.5% 的语料，且受影响的恰是 MCP 教程核心页——不修就无法做有意义的切片消融。

---

## 2. 五个设计决策

每一条都先给实测证据。**没有一条是从主设计文档的字面推演出来的**——五条全部与"照字面实现"
的结果不同。

### 决策 1：`structural` 用 flush-on-close，不用"叶子 section"

**主设计文档 §6.3.3 step 4 原文**：「每个叶子 section 合并为一个 chunk」。

**实测**：按字面实现（只发出叶子 section 的正文），774 篇语料上：

| 模型 | chunk 数 | 均值 | 丢掉的正文 |
|---|---|---|---|
| 字面：只发叶子 | 13,650 | 857 | **2,618,528 字符 = 18.0%** |
| flush-on-close | 16,695 | 857 | 0 |

丢掉的是**非叶节点自己的正文**——即"标题 A 下面先有一段话，然后才是 `### 子标题`"里的那段话。

最严重的单例：`https://modelcontextprotocol.io/docs/2026-07-28/develop/build-client.md`
全长 2,522 行，只有两个标题——第 5 行 `# Build an MCP client`、第 2516 行 `## Next steps`。
那 80,448 字符的完整教程挂在**父**节点下，按字面实现产出的 chunk 只有 "Next steps" 那 172 个字符。
**MCP 最核心的教程页整页检索不到。** 同类还有 `build-server.md`（89,755 字符 × 6 个版本）、
`deepagents/overview.md`（49,873）等；非叶节点正文超 500 字符的有 772 个。

**决定**：正文累积在标题栈顶，遇到关闭当前标题的新标题时**先发出再弹栈**。这同时覆盖叶子和非叶，
18% 自然回来。

**另两种改法被否决**，理由是它们在 `build-client.md` 上退化：
- prelude 并入第一个子 chunk → 把 80KB 贴到 172 字符的 "Next steps" 上
- prelude 复制进每个子 chunk → 同上，且重复

### 决策 2：原子单元加硬上限

**主设计文档 §6.3.3 step 6 原文**：「代码块（`fence`）与表格整体不切断」。

**实测**：照字面实现的 chunk 尺寸上界是灾难性的：

| 尺寸 | 内容 | 页面 |
|---|---|---|
| **106,728** | 表格（99% 表格内容） | `docs.langchain.com/oss/python/integrations/tools/index.md` — "All tools and toolkits" |
| **90,565 / 89,755 / 89,740** | 61–63% 围栏代码 | `build-server.md` — "Core MCP Concepts"，6 个版本各一份 |
| **80,448 / 80,426 / 79,643 / 79,129** | 53–54% 围栏代码 | `build-client.md` — "Build an MCP client"，6 个版本各一份 |

超过 `max_code_size`（3,000）的叶子 section 共 710 个，构成：`code` 293 / `mixed` 212 /
`prose` 158 / `table` 47。

**问题**：这些 chunk 会**静默失效**——embedding 按模型输入上限截断，prompt 装不下，
超出部分等于不存在。这正是本项目要消灭的那类失败（主设计文档 §6.1.5：「你以为更新了，
其实某个源抓失败了，索引缺内容是静默的」）。

**决定**：保留「不主动切断」原则，但超过 `max_atomic_size`（默认 **4,000** 字符）时**必须降级切分**：
- 表格：按行切，**每个子块重复表头**（否则子块无法解读）
- 代码块：按空行 + 顶层 `def` / `class` / `function` 边界切（§6.3.3 step 6 已有此设计，只是原本
  只给代码块、且没有触发上限）
- 标记 `split_atomic=True`，**评测报告单独统计这类 chunk 的表现**

**代价**：确实切断了，违背「绝不切断代码块」的字面承诺。**但诚实记录优于静默截断**——
这与主设计文档 §6.9「做不到全自动，就不假装能做到」是同一条原则。

### 决策 3：不合并小碎片，只丢纯噪声

**顾虑**：flush-on-close 之后，31.4% 的 chunk 小于 500 字符，10.1% 小于 200 字符（p10 = 198）。
直觉上"碎片化"会伤害检索。

**实测（抽样 18 条后推翻了这个直觉）**：那些小 chunk **大多数是精确、自洽的 API 片段**，
正是开发者提问的粒度：

```
[179] Chroma integration > Manage vector store > Delete items from vector store
[149] Ping > Message Format
[ 81] Elicitation > Protocol Messages > Creating Elicitation Requests
[112] Tools > Data Types > Tool Result > Audio Content
```

"怎么删向量库里的条目"命中的就是那条 179 字符的 chunk。合并会把它与邻座糊在一起，
同时破坏 breadcrumb 精确性——而 breadcrumb 是本项目的核心假设。均值上也不吃亏：
**fixed 792 vs structural 857，比值 1.08×**，§6.3 的公平性约束基本成立。

**决定**：一个 section 一个 chunk。仅当正文剥掉 HTML 标签与空白后为空（如
`<div id="enable-section-numbers" />`）才丢弃。**丢弃数进报告，不静默。**

### 决策 4：`semantic` / `structural` 不加 overlap，但公开披露

**主设计文档 §6.3 只给 `fixed` 规定了 `overlap=200`**，另两个策略没提。

| 策略 | 切法 | 索引的字符总量 |
|---|---|---|
| `fixed` | 窗口 1,000、步长 800 | **1.25× 语料** |
| `semantic` / `structural` | 段落 / section 边界，无重叠 | 1.00× 语料 |

**决定**：不补。overlap 本质是**硬切对边界无知的补偿**——`fixed` 看不见段落边界，
所以要在边界处重叠以防信息腰斩；看得见边界的策略不需要补偿。硬给 `structural` 加 overlap
会让相邻 section 的内容重复进索引，而它们的 breadcrumb 不同——**同一个句子以两个不同
breadcrumb 出现，反而污染核心假设**。

**但必须披露**：报告除均值与 chunk 数外，额外公布**总索引字符数**，让 1.25× vs 1.00× 这个
差异可见，而不是假装不存在。这个数字会进 README 的实验表。

### 决策 5：MDX 归一化放在 converter 层，Tab 标签进 breadcrumb

见 §3。**这条是 M2 最大的新增工作量，也是唯一一处跨回 M1 的改动。**

---

## 3. converter 的 MDX 规范化（决策 5 展开）

### 3.1 问题

MCP 文档站与 LangChain 文档站都用 Mintlify 式的 MDX 布局容器组织内容：

```markdown
<Tabs>
  <Tab title="Python">
    ## System Requirements

    Before starting, ensure your system meets these requirements:

    <CodeGroup>
      ```bash macOS/Linux theme={null}
      # Create project directory
      uv init mcp-client
```

`<Tab>` 内的正文缩进 4 空格，`<CodeGroup>` 内再缩进 2 空格。CommonMark 把缩进 4 空格的内容
**读成缩进代码块**。后果有三层：

1. **结构消失**：块内的 `## System Requirements` 等标题对解析器不可见——它只是代码块里的文本
2. **`kind` 判错**：§6.3.3 step 7 会把整块判成 `"code"`，实测 `build-client.md` 的 7 个
   `code_block` token（合计 71,221 字符）**全部**含标题语法，即全部是被误读的正文
3. **原子规则误伤**：step 6 会把整块当代码块保护起来，于是它同时撞上决策 2 的 106KB 问题

**实测影响面**：

| 指标 | 值 |
|---|---|
| 中招的语料 | **1,235,578 字符 = 8.5%** |
| 中招的文档 | 211 篇（其中 MCP 1,106,054 字符、LangChain 129,524 字符） |
| 占全部 `code_block` token 字符 | 64% |
| 单页最严重 | `build-client.md`：解析器只看到 **2 个标题**，实际正文里有上百个。**准确数目待正确实现后测定**——朴素 dedent 会虚增到 132，其中混有假标题（§3.3） |

受影响的几乎全是 MCP 教程页。**评测里 `api` 类问题大概率命中它们——而切片的收益本来最该
在这类题上体现。** 这是必须修而不能记为限制的原因。

### 3.2 修复规则

在 `corpus/converters/markdown.py` 增加第三项归一化（与已有的"剥样板块"同类）。
主设计文档 §6.2 已确立 converter 承担归一化的先例，逻辑一致。

1. **识别布局容器**：`<Tabs>` / `<Tab title="X">` / `<CodeGroup>` / `<Accordion>`。
2. **按嵌套层级 dedent**，不是固定减 4——`<CodeGroup>` 嵌在 `<Tab>` 里是两层。
3. **带 `title` 的容器重写成合成标题**，层级取**容器内最浅标题**；容器内所有标题相应 **+1**。
   于是 `<Tab title="Python">` 内的 `## System Requirements` 变成 `### System Requirements`，
   breadcrumb 得到 `Build an MCP client > Python > System Requirements`。
4. **剥语义标签留文本**（`<Note>` / `<Warning>` 等）。

**为什么第 3 条是必需的**：`build-client.md` 的教程在 **7 个语言 Tab 里重复了 7 遍**
（Python / TypeScript / Java / Kotlin / C# / Ruby / Rust）。不区分的话，top-5 会被 7 个近乎
相同的 chunk 占满。带上语言标签后它们可区分、可过滤，对开发者支持场景是**加分而不是负担**。

### 3.3 必须防的假标题

**朴素 dedent 会造出假标题。** 实测：`# Create virtual environment` 原本是 shell 注释、
位于围栏代码块内部；简单减 4 空格后它落到行首，被 CommonMark 读成 **H1**。
`build-client.md` 因此从 2 个标题"暴涨"到 132 个——其中混着大量这类假标题。

**这是 §6.3.3 修正里最需要测试钉住的一条**：原本在 fence 内的内容，dedent 后**必须仍在 fence 内**。
实现要点：dedent 时跟踪围栏状态，围栏内部的内容与围栏本身一起按层级平移，不单独处理。

### 3.4 重建语料

改 converter 后需要重建 `corpus.jsonl`。**不需要任何失效机制**：
`pipeline._absorb` 里 `content_hash` 是**原始字节**的哈希，而 `converter.convert(raw_path)`
每次运行都会重跑（[pipeline.py:187](../../src/docsentry/corpus/pipeline.py#L187)），
所以重跑 `uv run scripts/fetch_corpus.py --update` 就会重建。

**代价**：`--update` 是全量重抓（约 2,370 次请求、实测 4 分 57 秒）。
M2 期间可加一个 `--rebuild`（跳过抓取，只对本地 raw 重跑 converter）。规模小、**可选**——
不加就用 `--update`，只是迭代慢。

---

## 4. 三个 Chunker

```
chunking/
  base.py        Chunker Protocol + SizeStats + 共享的段落累积器
  fixed.py       窗口 1,000 / 步长 800
  semantic.py    段落边界累积
  structural.py  核心：markdown-it token 流
```

### 4.1 公平性做成结构性的，不是约定性的

三个策略从**同一处**取 `target_size`，各自产出 `SizeStats`（均值 / 中位数 / chunk 总数 /
总索引字符数）。检查脚本汇总成一张表，**是一个真的会跑的产物，不是测试里的断言**。

理由来自 M1 的教训：**"各自绿"不等于"组合起来对"**（M1 的 Task 15 冒烟暴露过一处
跨任务缝隙：两个各自评审通过的决策组合后整次运行中止，三个任务各自绿，缝没人测）。
公平性约束如果只写在测试里，就容易变成"每个策略的测试都断言自己的尺寸，但没人断言三者之间的关系"。

### 4.2 `structural` 的规则

| 规则 | 决策来源 |
|---|---|
| flush-on-close 发出 section 正文 | 决策 1（救回 18%） |
| 超 `max_atomic_size`（4,000）强制降级切分，标记 `split_atomic=True` | 决策 2 |
| 不合并小 section；正文剥标签后为空则丢弃，**丢弃数进报告** | 决策 3 |
| 无 overlap | 决策 4 |
| 解析失败退回 `semantic` 并记警告 | §6.3.3 已有 |

`kind` 判定沿用 §6.3.3 step 7：代码块占比 > 70% → `"code"`；表格 > 70% → `"table"`；
皆有 → `"mixed"`；否则 `"prose"`。

### 4.3 实现依赖

`markdown-it-py` 已在环境中可 import，**但没写进 `pyproject.toml`**——它是传递依赖。
M2 直接 import 它，必须显式声明，否则上游换依赖就会断。这属于"依赖要用就得声明"，
不能靠 `uv.lock` 碰巧锁住。

---

## 5. 数据模型与配置

### 5.1 `Chunk` 进 `models.py`

`models.py` 的 docstring 已声明 M1 只放语料层模型、`Chunk` 归 M2。M2 兑现它。

相对主设计文档 §5 的调整：
- 新增 `split_atomic: bool` —— 决策 2 的产物，评测要单独统计
- `indexed_at: datetime | None` —— 语料阶段为 `None`，M3 建索引时盖章。
  与 `Document.indexed_at` 同一约定（权威值在 Qdrant payload，语料层猜会误报 provenance）

### 5.2 `configs/chunking.yaml`

```yaml
target_size: 1000        # 三策略共享——公平性约束的载体
overlap: 200             # 仅 fixed 使用，理由见决策 4
max_atomic_size: 4000    # 决策 2
max_code_size: 3000      # §6.3.3 step 6
strategies: [fixed, semantic, structural]
```

### 5.3 `corpus/loader.py`

`load_corpus(path) -> Iterator[Document]`。M2 的验收测试与 M3 都要读 `corpus.jsonl`。

---

## 6. 测试与验收

### 6.1 单元测试

每策略各自的契约测试 + 边界测试：
- 代码块不被切断
- 超长原子单元按上限切，且**表格子块重复表头**
- breadcrumb 深度正确、内容正确
- **不出现假标题**（原 fence 内的内容 dedent 后仍是代码）—— 对应 §3.3
- 解析失败退回 `semantic` 并记警告

### 6.2 公平性检查

- 三策略均值**两两比值 ≤ 1.30**
- 报告公布：均值 / 中位数 / chunk 总数 / **总索引字符数**（决策 4 的披露要求）

**按比值定，不写死绝对数**——语料会动（LangChain 索引 2026-09-20 → 09-22 重组过一次，
369 → 539 篇）。这与 M1 验收的既有做法一致。

### 6.3 真实语料验收

沿用 M1 的做法，用独立标记隔离（M1 用 `-m network`）。

**特别要钉的一条**：`build-client.md` 的标题数从 2 恢复成"上百个"，**且其中不含假标题**。
这是 §3 修复是否真正成立的判据。**断言问的是性质（恢复出了结构、且没有假标题），不是某个具体数目**
——数目取决于层级算术的细节，会在实现时定死。

### 6.4 M2 验收标准（主设计文档 §9）

> 三种 Chunker 实现 + 测试通过 + 平均尺寸一致性检查通过

---

## 7. 风险

| 风险 | 应对 |
|---|---|
| MDX 规范化引入假标题 | 专门的测试：原 fence 内的内容 dedent 后仍是代码（§3.3） |
| 合成标题的层级算术出错 | 用 `build-client.md` 做断言的真实语料测试（§6.3） |
| 全量重抓 5 分钟拖慢迭代 | 可选的 `--rebuild`（跳过抓取，只重跑 converter） |
| 本文件数字在 MDX 修复后失效 | 修复后立即重测并更新本文件与 README，**不把旧数字留在文档里** |
| converter 改动影响 M1 已验收的结论 | MDX 修复作为**独立的 `fix(corpus)` 提交**，PR 里可单独 review |

---

## 8. 与主设计文档的关系

本文件落地后，主设计文档需要同步修正五处：

| 决策 | 主设计文档位置 |
|---|---|
| 1 flush-on-close | §6.3.3 step 3 / 4 |
| 2 原子单元硬上限 | §6.3 公平性约束段 + §6.3.3 step 6 |
| 3 不合并小碎片 | §6.3.3 新增 step 8 |
| 4 overlap 披露 | §6.3 公平性约束段 |
| 5 MDX 归一化 | **§6.2.1**（converter 层，不是 §6.3.3） |

修正方式：在原文处就地改正，并注明"2026-09-24 实测修正"与本文档的链接——
与 M1 期间修正 §6.1.2 / §6.1.4 的做法一致。

**修正前的主设计文档仍然是 M1 的历史记录**，不回改 M1 的验收结论。
