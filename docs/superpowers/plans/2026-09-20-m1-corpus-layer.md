# M1 语料层 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成 `Source` 抽象（`llms_txt` + `local_dir`）与增量更新管线，把 MCP 与 LangChain 两份公开文档抓成带版本标签的 `data/corpus.jsonl`，并产出可核验的抓取报告。

**Architecture:** 语料层分四块——`sources/` 持有**指针**（URL 或路径）而非副本，每次运行重新读取；`converters/` 把任意格式归一成 Markdown；`manifest.py` 用 `content_hash` 判变更；`pipeline.py` 按**先插后删**顺序落盘。`Source` 协议只有 `discover` / `fetch` / `refreshable` 三个方法，屏蔽数据来源差异。

**Tech Stack:** Python 3.11+ · uv · httpx · Pydantic + Pydantic Settings · PyYAML · Typer · pytest

**设计文档：** `docs/superpowers/specs/2026-09-18-docsentry-design.md`（唯一权威来源，冲突时以它为准）

---

## 开工前已实测的事实（2026-09-20，不必重查）

这些数字来自本次规划前的真实抓取，直接决定了下面的配置与测试断言：

| 事实 | 值 |
|---|---|
| `modelcontextprotocol.io/llms.txt` | **平铺**，347 个唯一 `.md` |
| └ `/docs/<日期>/` | 87（5 个日期版本） |
| └ `/specification/<日期>/` | 111（5 个日期版本） |
| └ `/docs/draft/` + `/specification/draft/` | 54 |
| └ 无版本段（`/seps/` 43、`/community/` 30、`/registry/` 11、`/extensions/` 9、`/development/` 1、`/examples.md` 1） | 95 |
| `docs.langchain.com/llms.txt` | **层级**，58 个子索引链接 |
| └ `/oss/python/llms.txt` | 369 个唯一 `.md`，**无更深嵌套**（递归 1 层即终止） |
| MCP/LangChain 页面正文 | 顶部带 `> ## Documentation Index` 样板块，**每页都有** |

**本次修正的两处设计文档内容**（用户已确认）：

1. **MCP 的 `url_include` 由 `"/docs/"` 改为 `["/docs/", "/specification/"]`**。原配置漏掉全部 198 个 `/specification/` 页面，而那正是协议规范正文——时效性命题证据链所在。
2. **M1 版本指标改为按被纳入索引的页面统计**：`/docs/` + `/specification/` 共 252 篇，198 日期 + 54 draft，**标注率 100%**。原写法「非 unknown ≥90%」在按全量 347 篇计算时最高只有 73%（含 draft），因 95 个页面本身不带版本——是语料性质，不是提取器缺陷。抓取报告必须分列 `dated` / `draft` / `unknown` 三分项，让无版本页面**显式可见**而非静默。

**LangChain 页面 URL 与正文均无版本信息**，`version` 恒为 `unknown`。这是语料本身的性质，不做人造版本号——版本感知实验以 MCP 为载体。

**已确认无需 ETag 优化**：MCP 无 ETag、`Last-Modified` 是站点构建时间，`content_hash` 是唯一可靠判据，因此每次运行全量下载比对。716 页约 14 MB，可忽略。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `pyproject.toml` | uv 项目、依赖、pytest 配置 |
| `configs/sources.yaml` | 数据源注册表 |
| `src/docsentry/models.py` | `SourceKind` / `DocRef` / `Document` |
| `src/docsentry/config.py` | `Settings`（env）+ `sources.yaml` 加载校验 |
| `src/docsentry/corpus/versioning.py` | 版本提取、分桶、`keep_all_versions` 剪枝 |
| `src/docsentry/corpus/paths.py` | locator → `data/raw` 路径，含逃逸防护 |
| `src/docsentry/corpus/sources/base.py` | `Source` 协议 + `Fetched` |
| `src/docsentry/corpus/sources/llms_txt.py` | 平铺/层级索引解析 + 递归展开 |
| `src/docsentry/corpus/sources/local_dir.py` | 本地目录扫描（不复制） |
| `src/docsentry/corpus/converters/base.py` | `Converter` 协议 + `ConvertedDoc` |
| `src/docsentry/corpus/converters/markdown.py` | 直读 + 剥样板块 + 提标题 |
| `src/docsentry/corpus/manifest.py` | 变更检测持久化（原子写） |
| `src/docsentry/corpus/report.py` | 抓取报告数据结构与序列化 |
| `src/docsentry/corpus/pipeline.py` | **先插后删**同步引擎 |
| `scripts/fetch_corpus.py` | CLI 入口 |
| `scripts/health.py` | 索引健康检查 |
| `tests/*.py` | 见各任务 |

**分层依赖方向**（单向，不得反向）：

```
scripts/ → pipeline.py → sources/ + converters/ + manifest.py + report.py
                       → versioning.py + paths.py → models.py
```

---

## Task 1: 项目脚手架

**Files:**
- Create: `pyproject.toml`
- Create: `src/docsentry/__init__.py`
- Create: `src/docsentry/corpus/__init__.py`
- Create: `src/docsentry/corpus/sources/__init__.py`
- Create: `src/docsentry/corpus/converters/__init__.py`
- Create: `scripts/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`
- Modify: `.gitignore`

- [ ] **Step 1: 写 `pyproject.toml`**

```toml
[project]
name = "docsentry"
version = "0.1.0"
description = "A developer-support agent over technical documentation"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "pyyaml>=6.0",
    "typer>=0.12",
]

[dependency-groups]
dev = ["pytest>=8.2"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/docsentry"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q -m 'not network'"
markers = [
    "network: hits the real internet; run with `uv run pytest -m network`",
]
```

`addopts` 默认排除 `network` 标记的测试——联网测试必须显式请求才跑。

- [ ] **Step 2: 建包目录与空 `__init__.py`**

`src/docsentry/__init__.py` 写一行版本号，其余三个 `__init__.py` 留空：

```python
"""docsentry -- a developer-support agent over technical documentation."""

__version__ = "0.1.0"
```

- [ ] **Step 3: 建 `scripts/__init__.py` 与 `tests/conftest.py`**

`scripts/__init__.py` 留空（让 `from scripts.fetch_corpus import app` 在测试里可导入）。

`tests/conftest.py` 保证仓库根与 `src/` 都在 `sys.path` 上——测试既 import `docsentry`（走 `src/` 布局），也 import `scripts.*`：

```python
# tests/conftest.py
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

for candidate in (ROOT, ROOT / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
```

- [ ] **Step 4: `.gitignore` — 不要排除 `uv.lock`**

**`uv.lock` 必须提交**（CLAUDE.md 约定 #7）。`data/`、`reports/*`、`.venv/`、`__pycache__/` 已在 `.gitignore` 中，本步骤不需要再追加任何东西——只需确认 `.gitignore` 里**没有** `uv.lock` 这一行：

```bash
git check-ignore -v uv.lock    # 期望：无输出（即未被忽略）
```

> `uv.lock` 是 uv 的锁文件，记录所有依赖（含间接依赖）的确切版本与哈希。本项目核心叙事是「可复现」——评测数字必须能在别人机器上跑出来，依赖版本一漂，跑出的准确率就和仓库里记录的对不上。lockfile 不是构建产物：`node_modules` 要忽略，`uv.lock` 要提交（同类：`package-lock.json` / `poetry.lock` / `Cargo.lock`）。

- [ ] **Step 5: 写冒烟测试**

```python
# tests/test_smoke.py
import docsentry


def test_package_imports():
    assert docsentry.__version__


def test_corpus_subpackages_import():
    import docsentry.corpus.converters  # noqa: F401
    import docsentry.corpus.sources  # noqa: F401
```

- [ ] **Step 6: 安装并跑测试**

Run: `uv sync && uv run pytest`
Expected: `2 passed`

- [ ] **Step 7: 提交**

```bash
git add pyproject.toml uv.lock src/docsentry scripts/__init__.py tests/
git commit -m "chore(m1): 项目脚手架 — uv + src 布局 + pytest 配置"
```

---

## Task 2: 数据模型

**Files:**
- Create: `src/docsentry/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_models.py
from datetime import datetime, timezone

from docsentry.models import Document, SourceKind, hash_bytes, make_doc_id


def test_make_doc_id_is_stable_and_16_hex():
    first = make_doc_id("mcp", "https://example.com/a.md")
    second = make_doc_id("mcp", "https://example.com/a.md")

    assert first == second
    assert len(first) == 16
    assert all(c in "0123456789abcdef" for c in first)


def test_make_doc_id_depends_on_source_and_locator():
    assert make_doc_id("mcp", "x") != make_doc_id("langgraph", "x")
    assert make_doc_id("mcp", "x") != make_doc_id("mcp", "y")


def test_hash_bytes_matches_known_sha256():
    # sha256("") -- fixed vector, so the hash function cannot silently change
    assert hash_bytes(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _document(**overrides):
    base = dict(
        doc_id="abc123",
        source="mcp",
        kind=SourceKind.LLMS_TXT,
        version="2026-07-28",
        url="https://example.com/a",
        title="A",
        path="data/raw/mcp/example.com/a.md",
        content="# A\nbody",
        content_hash="deadbeef",
        origin_format="md",
        fetched_at=datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return Document(**base)


def test_document_json_round_trip():
    original = _document()

    restored = Document.from_json(original.to_json())

    assert restored == original


def test_document_json_round_trip_with_indexed_at():
    stamp = datetime(2026, 9, 21, 4, 0, tzinfo=timezone.utc)
    original = _document(indexed_at=stamp)

    assert Document.from_json(original.to_json()).indexed_at == stamp


def test_document_kind_serializes_as_string():
    assert _document().to_json()["kind"] == "llms_txt"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docsentry.models'`

- [ ] **Step 3: 实现 `models.py`**

```python
"""Core data models.

M1 defines the corpus-layer models only (``SourceKind`` / ``DocRef`` /
``Document``). ``Chunk`` and ``Answer`` belong to the milestones that produce
them (M2 chunking, M4 generation) and are deliberately absent here so nothing
in this module is dead code.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SourceKind(str, Enum):
    """How a source stays fresh -- design spec 6.1.2.

    ``LLMS_TXT`` and ``LOCAL_DIR`` hold *pointers* and can be re-read
    automatically. ``SNAPSHOT`` holds a *copy* and cannot -- which is exactly
    why the project does not build an upload flow.
    """

    LLMS_TXT = "llms_txt"
    LOCAL_DIR = "local_dir"
    SNAPSHOT = "snapshot"


def make_doc_id(source: str, locator: str) -> str:
    """Stable 16-hex identity for a document -- sha256(source + locator)[:16].

    Deliberately content-independent: a document keeps its id across edits, so
    the index can tell "this page changed" from "this page is new".
    """
    return hashlib.sha256(f"{source}{locator}".encode("utf-8")).hexdigest()[:16]


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DocRef:
    """A pointer to one document. Cheap to produce in bulk; carries no content."""

    source: str
    kind: SourceKind
    locator: str
    version_hint: str | None = None
    title: str = ""


@dataclass
class Document:
    """One document, normalised to Markdown, ready to be chunked.

    ``indexed_at`` is ``None`` at corpus stage. It is stamped by ``build_index``
    (M3) when the document's chunks are actually upserted -- the authoritative
    value lives in the Qdrant payload, and having the corpus layer guess it
    would misreport provenance by however long the corpus sat on disk.
    """

    doc_id: str
    source: str
    kind: SourceKind
    version: str
    url: str
    title: str
    path: str
    content: str
    content_hash: str
    origin_format: str
    fetched_at: datetime
    indexed_at: datetime | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "source": self.source,
            "kind": self.kind.value,
            "version": self.version,
            "url": self.url,
            "title": self.title,
            "path": self.path,
            "content": self.content,
            "content_hash": self.content_hash,
            "origin_format": self.origin_format,
            "fetched_at": self.fetched_at.isoformat(),
            "indexed_at": self.indexed_at.isoformat() if self.indexed_at else None,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Document:
        indexed_at = raw.get("indexed_at")
        return cls(
            doc_id=raw["doc_id"],
            source=raw["source"],
            kind=SourceKind(raw["kind"]),
            version=raw["version"],
            url=raw["url"],
            title=raw["title"],
            path=raw["path"],
            content=raw["content"],
            content_hash=raw["content_hash"],
            origin_format=raw["origin_format"],
            fetched_at=datetime.fromisoformat(raw["fetched_at"]),
            indexed_at=datetime.fromisoformat(indexed_at) if indexed_at else None,
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_models.py -v`
Expected: `6 passed`

- [ ] **Step 5: 提交**

```bash
git add src/docsentry/models.py tests/test_models.py
git commit -m "feat(m1): 数据模型 DocRef/Document + 稳定 doc_id"
```

---

## Task 3: 版本提取与剪枝

**Files:**
- Create: `src/docsentry/corpus/versioning.py`
- Test: `tests/test_versioning.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_versioning.py
from docsentry.corpus.versioning import (
    UNKNOWN_VERSION,
    extract_version,
    is_dated,
    logical_key,
    prune_to_latest,
    resolve_version,
    version_bucket,
)
from docsentry.models import DocRef, SourceKind


def _ref(locator, source="mcp", version_hint=None):
    return DocRef(source=source, kind=SourceKind.LLMS_TXT, locator=locator, version_hint=version_hint)


# --- extract_version: every shape observed in the real corpus -------------

def test_extracts_dated_docs_path():
    url = "https://modelcontextprotocol.io/docs/2026-07-28/develop/build-server.md"
    assert extract_version(url) == "2026-07-28"


def test_extracts_dated_specification_path():
    url = "https://modelcontextprotocol.io/specification/2025-11-25/server/tools.md"
    assert extract_version(url) == "2025-11-25"


def test_extracts_draft_from_docs_and_specification():
    assert extract_version("https://modelcontextprotocol.io/docs/draft/learn/architecture.md") == "draft"
    assert extract_version("https://modelcontextprotocol.io/specification/draft/basic/lifecycle.md") == "draft"


def test_versionless_paths_are_unknown():
    for url in (
        "https://modelcontextprotocol.io/seps/2322-MRTR.md",
        "https://modelcontextprotocol.io/community/governance.md",
        "https://modelcontextprotocol.io/registry/about.md",
        "https://modelcontextprotocol.io/extensions/overview.md",
        "https://modelcontextprotocol.io/examples.md",
    ):
        assert extract_version(url) == UNKNOWN_VERSION, url


def test_langchain_docs_are_unknown():
    url = "https://docs.langchain.com/oss/python/langgraph/graph-api.md"
    assert extract_version(url) == UNKNOWN_VERSION


def test_page_about_versioning_is_still_a_versioned_page():
    # `versioning.md` is the page's *name*, not a version segment;
    # the version still comes from the path.
    url = "https://modelcontextprotocol.io/docs/2026-07-28/learn/versioning.md"
    assert extract_version(url) == "2026-07-28"


# --- bucketing ------------------------------------------------------------

def test_bucket_classifies_dated_draft_unknown():
    assert version_bucket("2026-07-28") == "dated"
    assert version_bucket("draft") == "draft"
    assert version_bucket("unknown") == "unknown"
    assert version_bucket("internal-2026Q3") == "unknown"


def test_is_dated():
    assert is_dated("2026-07-28")
    assert not is_dated("draft")
    assert not is_dated("unknown")


# --- resolve_version ------------------------------------------------------

def test_version_hint_wins_over_url():
    ref = _ref("https://example.com/plain.md", version_hint="internal-2026Q3")
    assert resolve_version(ref) == "internal-2026Q3"


def test_resolve_falls_back_to_url_extraction():
    ref = _ref("https://modelcontextprotocol.io/docs/2026-07-28/x.md")
    assert resolve_version(ref) == "2026-07-28"


# --- logical_key ----------------------------------------------------------

def test_logical_key_strips_version_segment():
    a = logical_key("https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture.md")
    b = logical_key("https://modelcontextprotocol.io/docs/2025-11-25/learn/architecture.md")
    c = logical_key("https://modelcontextprotocol.io/docs/draft/learn/architecture.md")

    assert a == b == c
    assert a == "https://modelcontextprotocol.io/docs/learn/architecture.md"


def test_logical_key_keeps_docs_and_specification_distinct():
    docs = logical_key("https://modelcontextprotocol.io/docs/2026-07-28/index.md")
    spec = logical_key("https://modelcontextprotocol.io/specification/2026-07-28/index.md")

    assert docs != spec


# --- prune_to_latest (keep_all_versions: false) ---------------------------

def test_prune_keeps_newest_dated_version():
    refs = [
        _ref("https://modelcontextprotocol.io/docs/2025-11-25/learn/architecture.md"),
        _ref("https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture.md"),
        _ref("https://modelcontextprotocol.io/docs/2025-06-18/learn/architecture.md"),
    ]

    kept = prune_to_latest(refs)

    assert len(kept) == 1
    assert kept[0].locator.endswith("/2026-07-28/learn/architecture.md")


def test_prune_prefers_draft_over_dated():
    refs = [
        _ref("https://modelcontextprotocol.io/docs/2026-07-28/x.md"),
        _ref("https://modelcontextprotocol.io/docs/draft/x.md"),
    ]

    assert prune_to_latest(refs)[0].locator.endswith("/draft/x.md")


def test_prune_keeps_every_versionless_page():
    refs = [
        _ref("https://modelcontextprotocol.io/seps/1-a.md"),
        _ref("https://modelcontextprotocol.io/community/governance.md"),
    ]

    assert len(prune_to_latest(refs)) == 2


def test_prune_keeps_docs_and_specification_separately():
    refs = [
        _ref("https://modelcontextprotocol.io/docs/2025-11-25/index.md"),
        _ref("https://modelcontextprotocol.io/docs/2026-07-28/index.md"),
        _ref("https://modelcontextprotocol.io/specification/2025-11-25/index.md"),
        _ref("https://modelcontextprotocol.io/specification/2026-07-28/index.md"),
    ]

    assert len(prune_to_latest(refs)) == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_versioning.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docsentry.corpus.versioning'`

- [ ] **Step 3: 实现 `versioning.py`**

```python
"""Version extraction, bucketing, and version-set pruning.

The version segment lives in the URL path for MCP: ``/docs/2026-07-28/...``
and ``/specification/2026-07-28/...``. ``draft`` is a real version channel --
the next, unreleased spec -- and is kept distinct from a dated release so
retrieval can refuse to serve draft text as if it were stable.

LangChain pages carry no version in URL or body, so they resolve to
``unknown``. That is a property of the corpus, not a gap in extraction.
"""

from __future__ import annotations

import re
from collections import defaultdict

from docsentry.models import DocRef

UNKNOWN_VERSION = "unknown"
DRAFT_VERSION = "draft"

# /docs/2026-07-28/...  |  /specification/draft/...
_VERSION_RE = re.compile(r"/(?:docs|specification)/(\d{4}-\d{2}-\d{2}|draft)(?:/|$)")
# Same, but anchored to the version segment so it can be *replaced*.
_VERSION_SEGMENT_RE = re.compile(r"/(docs|specification)/(?:\d{4}-\d{2}-\d{2}|draft)(?=/)")
_DATED_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def extract_version(locator: str) -> str:
    """Pull a version out of a locator, or ``UNKNOWN_VERSION``."""
    match = _VERSION_RE.search(locator)
    return match.group(1) if match else UNKNOWN_VERSION


def is_dated(version: str) -> bool:
    return bool(_DATED_RE.fullmatch(version))


def version_bucket(version: str) -> str:
    """Reporting bucket: ``"dated"`` | ``"draft"`` | ``"unknown"``.

    The fetch report must break these out separately so that versionless pages
    are visible rather than silently averaged into a coverage number.
    """
    if is_dated(version):
        return "dated"
    if version == DRAFT_VERSION:
        return "draft"
    return "unknown"


def resolve_version(ref: DocRef) -> str:
    """Decide a document's version: an explicit hint wins, else URL extraction.

    ``version_hint`` is how a ``local_dir`` source stamps its
    ``default_version`` onto files that have no version in their path.
    """
    if ref.version_hint:
        return ref.version_hint
    return extract_version(ref.locator)


def logical_key(locator: str) -> str:
    """Strip the version segment so all versions of one page share a key.

    ``/docs/2026-07-28/learn/architecture.md`` and
    ``/docs/draft/learn/architecture.md`` both map to
    ``/docs/learn/architecture.md``. ``/docs/`` and ``/specification/`` stay
    distinct -- they are different documents that happen to share a version.
    """
    return _VERSION_SEGMENT_RE.sub(r"/\1", locator, count=1)


def _version_sort_key(version: str) -> tuple[int, str]:
    # draft outranks every dated release (it is the newest channel);
    # ISO date strings compare lexicographically == chronologically.
    if version == DRAFT_VERSION:
        return (1, "")
    return (0, version)


def prune_to_latest(refs: list[DocRef]) -> list[DocRef]:
    """Keep only the newest version of each page -- ``keep_all_versions: false``.

    Versionless pages pass through untouched: they have no newer alternative,
    and dropping them would delete SEPs and community docs entirely.
    """
    groups: dict[str, list[DocRef]] = defaultdict(list)
    passthrough: list[DocRef] = []

    for ref in refs:
        if resolve_version(ref) == UNKNOWN_VERSION:
            passthrough.append(ref)
        else:
            groups[logical_key(ref.locator)].append(ref)

    kept = list(passthrough)
    for group in groups.values():
        kept.append(max(group, key=lambda r: _version_sort_key(resolve_version(r))))
    return kept
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_versioning.py -v`
Expected: `16 passed`

- [ ] **Step 5: 提交**

```bash
git add src/docsentry/corpus/versioning.py tests/test_versioning.py
git commit -m "feat(m1): 版本提取 — URL 段解析 + dated/draft/unknown 分桶"
```

---

## Task 4: 配置加载

**Files:**
- Create: `src/docsentry/config.py`
- Create: `configs/sources.yaml`
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_config.py
from pathlib import Path

import pytest
from pydantic import ValidationError

from docsentry.config import Settings, load_sources_config


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "sources.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_two_sources(tmp_path):
    path = _write(
        tmp_path,
        """
sources:
  - name: mcp
    kind: llms_txt
    llms_txt: https://modelcontextprotocol.io/llms.txt
    url_include:
      - /docs/
      - /specification/
  - name: local
    kind: local_dir
    path: ./data/internal_docs
    default_version: internal-2026Q3
""",
    )

    config = load_sources_config(path)

    assert [s.name for s in config.sources] == ["mcp", "local"]
    assert config.sources[0].url_include == ["/docs/", "/specification/"]
    assert config.sources[0].keep_all_versions is True
    assert config.sources[1].default_version == "internal-2026Q3"


def test_bare_string_url_include_is_wrapped(tmp_path):
    path = _write(
        tmp_path,
        """
sources:
  - name: mcp
    kind: llms_txt
    llms_txt: https://example.com/llms.txt
    url_include: /docs/
""",
    )

    assert load_sources_config(path).sources[0].url_include == ["/docs/"]


def test_missing_url_include_means_no_filter(tmp_path):
    path = _write(
        tmp_path,
        """
sources:
  - name: mcp
    kind: llms_txt
    llms_txt: https://example.com/llms.txt
""",
    )

    assert load_sources_config(path).sources[0].url_include == []


def test_llms_txt_kind_requires_url(tmp_path):
    path = _write(tmp_path, "sources:\n  - name: mcp\n    kind: llms_txt\n")

    with pytest.raises(ValidationError, match="requires 'llms_txt'"):
        load_sources_config(path)


def test_local_dir_kind_requires_path(tmp_path):
    path = _write(tmp_path, "sources:\n  - name: local\n    kind: local_dir\n")

    with pytest.raises(ValidationError, match="requires 'path'"):
        load_sources_config(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_sources_config(tmp_path / "nope.yaml")


def test_settings_derives_paths(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", reports_dir=tmp_path / "reports")

    assert settings.raw_dir == tmp_path / "data" / "raw"
    assert settings.manifest_path == tmp_path / "data" / "manifest.json"
    assert settings.corpus_path == tmp_path / "data" / "corpus.jsonl"


def test_settings_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSENTRY_DATA_DIR", str(tmp_path / "elsewhere"))

    assert Settings().data_dir == tmp_path / "elsewhere"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docsentry.config'`

- [ ] **Step 3: 实现 `config.py`**

```python
"""Configuration: declarative sources + environment-driven paths.

Sources are declared in ``configs/sources.yaml`` rather than code so that
adding a corpus is a config change, not a code change -- which is the point of
the ``Source`` abstraction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SourceConfig(BaseModel):
    """One registered source. Validated so a typo fails at load, not at fetch."""

    name: str
    kind: Literal["llms_txt", "local_dir", "snapshot"]
    enabled: bool = True

    # llms_txt
    llms_txt: str | None = None
    url_include: list[str] = Field(default_factory=list)
    keep_all_versions: bool = True

    # local_dir
    path: Path | None = None
    default_version: str | None = None

    @field_validator("url_include", mode="before")
    @classmethod
    def _wrap_bare_string(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value

    @model_validator(mode="after")
    def _require_kind_specific_fields(self):
        if self.kind == "llms_txt" and not self.llms_txt:
            raise ValueError(f"source {self.name!r}: kind=llms_txt requires 'llms_txt'")
        if self.kind == "local_dir" and not self.path:
            raise ValueError(f"source {self.name!r}: kind=local_dir requires 'path'")
        return self


class SourcesConfig(BaseModel):
    sources: list[SourceConfig]

    def enabled(self) -> list[SourceConfig]:
        return [s for s in self.sources if s.enabled]

    def by_name(self, name: str) -> SourceConfig:
        for source in self.sources:
            if source.name == name:
                return source
        raise KeyError(f"no source named {name!r} in config")


class Settings(BaseSettings):
    """Environment-driven settings. Prefix: ``DOCSENTRY_``, or a ``.env`` file."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="DOCSENTRY_", extra="ignore")

    data_dir: Path = Path("data")
    reports_dir: Path = Path("reports")
    sources_config: Path = Path("configs/sources.yaml")
    http_timeout_s: float = 30.0
    http_retries: int = 3
    fetch_workers: int = 8

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def manifest_path(self) -> Path:
        return self.data_dir / "manifest.json"

    @property
    def corpus_path(self) -> Path:
        return self.data_dir / "corpus.jsonl"


def load_sources_config(path: Path) -> SourcesConfig:
    if not path.exists():
        raise FileNotFoundError(f"sources config not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return SourcesConfig.model_validate(raw)
```

- [ ] **Step 4: 写 `configs/sources.yaml`**

```yaml
# 数据源注册表。
#
# 这里注册的是**指针**，不是副本 —— 系统每次运行重新读取，源变了自然被发现。
# 这正是本项目不做"上传文档"的原因：上传产生快照，快照会过期且无人察觉。

sources:
  # MCP 官方文档站。index 是平铺列表，链接直达 .md，URL 路径自带版本。
  #
  # url_include 必须同时包含 /docs/ 与 /specification/：
  #   /docs/          -> 87 个日期版 + 23 个 draft 的教程与指南
  #   /specification/ -> 111 个日期版 + 31 个 draft 的协议规范正文
  # 只写 /docs/ 会漏掉全部规范正文，而那正是时效性命题的核心语料（2026-07-28
  # 协议有实质变更，证据就在 /specification/2026-07-28/ 下）。
  #
  # 故意**不**收录 /seps/ 与 /community/：这两类页面本身不带版本（SEP 是独立
  # 编号的提案），收进来会让版本标注率虚降，且对"查 API 用法"帮助有限。
  - name: mcp
    kind: llms_txt
    llms_txt: https://modelcontextprotocol.io/llms.txt
    url_include:
      - /docs/
      - /specification/
    keep_all_versions: true

  # LangChain 官方文档站。index 是**层级**索引，指向子 llms.txt，需递归展开。
  # /oss/python/llms.txt 展开出 369 篇，无更深嵌套。
  #
  # 注意：LangChain 页面 URL 与正文均不含版本信息，version 恒为 unknown。
  # 这不是提取器缺陷，是语料性质，不要伪造版本号。
  - name: langgraph
    kind: llms_txt
    llms_txt: https://docs.langchain.com/llms.txt
    url_include:
      - /oss/python/
    keep_all_versions: true

  # 私有语料示例。默认关闭 —— 目录不存在时开启会让每次抓取都报一堆失败。
  # 演示私有语料接入时：把文档丢进 data/internal_docs/，把 enabled 改 true。
  - name: internal
    kind: local_dir
    path: ./data/internal_docs
    default_version: "internal-2026Q3"
    enabled: false
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_config.py -v`
Expected: `8 passed`

- [ ] **Step 6: 验证真实配置能被解析**

Run: `uv run python -c "from docsentry.config import load_sources_config; c = load_sources_config(__import__('pathlib').Path('configs/sources.yaml')); print([(s.name, s.enabled, s.url_include) for s in c.sources])"`
Expected: `[('mcp', True, ['/docs/', '/specification/']), ('langgraph', True, ['/oss/python/']), ('internal', False, [])]`

- [ ] **Step 7: 提交**

```bash
git add src/docsentry/config.py configs/sources.yaml tests/test_config.py
git commit -m "feat(m1): 数据源配置 + Pydantic Settings"
```

---

## Task 5: raw 路径推导与逃逸防护

**Files:**
- Create: `src/docsentry/corpus/paths.py`
- Test: `tests/test_paths.py`

> **为什么单独一个模块**：`llms.txt` 是**远端文件**，是不可信输入。URL 路径里出现 `..` 段、或含 Windows 非法字符，都可能让我们写到 `data/raw` 之外或直接崩溃。写盘和删除前都必须过这道闸。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_paths.py
from pathlib import Path

import pytest

from docsentry.corpus.paths import ensure_within, raw_relpath


def test_maps_https_url_to_host_and_path():
    rel = raw_relpath("https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture.md")

    assert rel == Path("modelcontextprotocol.io/docs/2026-07-28/learn/architecture.md")


def test_two_hosts_never_collide():
    a = raw_relpath("https://a.example.com/x.md")
    b = raw_relpath("https://b.example.com/x.md")

    assert a != b


def test_drops_traversal_segments():
    rel = raw_relpath("https://example.com/../../etc/passwd.md")

    assert ".." not in rel.parts


def test_sanitizes_windows_illegal_characters():
    rel = raw_relpath("https://example.com/a:b*c?.md")

    assert rel.name == "a_b_c_.md"


def test_rejects_locator_with_no_usable_path():
    with pytest.raises(ValueError, match="cannot derive a path"):
        raw_relpath("https://example.com/")


def test_query_string_is_dropped():
    rel = raw_relpath("https://example.com/a.md?v=2")

    assert rel.name == "a.md"


def test_ensure_within_accepts_child(tmp_path):
    root = tmp_path / "raw"
    root.mkdir()

    assert ensure_within(root / "mcp" / "a.md", root) == (root / "mcp" / "a.md").resolve()


def test_ensure_within_rejects_escape(tmp_path):
    root = tmp_path / "raw"
    root.mkdir()

    with pytest.raises(ValueError, match="refusing to touch"):
        ensure_within(tmp_path / "outside.md", root)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docsentry.corpus.paths'`

- [ ] **Step 3: 实现 `paths.py`**

```python
"""Locator -> on-disk path, with the guard rails that implies.

An ``llms.txt`` is remote, untrusted input: nothing stops it from listing
``https://host/../../etc/passwd.md`` or a path full of Windows-illegal
characters. Every write and every unlink goes through here first.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

# Characters Windows refuses in a filename, plus control characters.
_ILLEGAL = re.compile(r'[<>:"|?*\x00-\x1f]')


def _sanitize(part: str) -> str:
    cleaned = _ILLEGAL.sub("_", part).strip().rstrip(".")
    return cleaned or "_"


def raw_relpath(locator: str) -> Path:
    """``<host>/<url path>`` for a locator -- callers join it under their own
    source directory, so a source can never address another's subtree.

    The host is part of the path so two hosts never collide. ``..`` segments
    are dropped rather than resolved -- a document URL never legitimately
    contains one, and dropping is safer than guessing.
    """
    parts = urlparse(locator)
    if parts.scheme in ("http", "https"):
        candidate = Path(parts.netloc) / parts.path.lstrip("/")
    else:
        candidate = Path(parts.path.lstrip("/"))

    clean = [_sanitize(p) for p in candidate.parts if p not in ("", ".", "..")]
    clean = [p for p in clean if p != "_"]
    if not clean:
        raise ValueError(f"cannot derive a path from locator {locator!r}")
    return Path(*clean)


def ensure_within(path: Path, root: Path) -> Path:
    """Return ``path`` resolved, or raise if it escapes ``root``.

    A backstop for the sanitising above: called immediately before every write
    and unlink, so a bug in path derivation cannot turn into a write outside
    the corpus tree.
    """
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError(f"refusing to touch {resolved}: outside {root_resolved}")
    return resolved
```

> **⚠️ 上面 Step 3 的代码有缺陷，不要照抄（2026-09-21 修正）。**
>
> | 断言（Windows） | Step 3 原实现 | 修正后 |
> |---|---|---|
> | `raw_relpath("https://example.com/a:b.md").name` | `b.md` | `a_b.md` |
> | 两个不同 host 的 `x:y.md` 路径 | **相同（撞了）** | 不同 |
> | `raw_relpath("https://example.com/")` | 返回 `example.com` | `ValueError` |
>
> 根因：清洗发生在 `Path()` 构造**之后**，而 Windows 下 `:` 是**盘符分隔符**，于是
> `Path("example.com") / "a:b*c"` 求值为 `a:b*c`——主机段被整个丢弃，本模块"两 host
> 不撞"的保证随之失效。修法：**先按段清洗，再构造 `Path`**；另，除主机外无路径段时
> 抛 `ValueError`。原测试还有一条期望在任何实现下都不可达（且与
> `test_query_string_is_dropped` 的 `?` 语义互斥），已替换为良定义用例 + 一条回归测试。
> 完整证据见 commit `0a5a9b7` 的 message。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_paths.py -v`
Expected: `9 passed`（原计划记 8，修正后为 9）

- [ ] **Step 5: 提交**

```bash
git add src/docsentry/corpus/paths.py tests/test_paths.py
git commit -m "feat(m1): raw 路径推导 + 目录逃逸防护"
```

---

## Task 6: `Source` 协议

**Files:**
- Create: `src/docsentry/corpus/sources/base.py`
- Test: `tests/test_source_protocol.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_source_protocol.py
from docsentry.corpus.sources.base import Fetched, Source
from docsentry.models import DocRef, SourceKind


def test_fetched_holds_ref_bytes_and_timestamp():
    ref = DocRef(source="s", kind=SourceKind.LLMS_TXT, locator="https://x/a.md")
    from docsentry.models import utcnow

    fetched = Fetched(ref=ref, data=b"# hi", fetched_at=utcnow())

    assert fetched.ref is ref
    assert fetched.data == b"# hi"


def test_a_conforming_class_satisfies_the_protocol():
    class FakeSource:
        name = "fake"
        kind = SourceKind.LLMS_TXT

        def discover(self):
            return []

        def fetch(self, ref):
            raise NotImplementedError

        def refreshable(self):
            return True

    assert isinstance(FakeSource(), Source)


def test_a_partial_class_does_not_satisfy_the_protocol():
    class MissingFetch:
        name = "broken"
        kind = SourceKind.LLMS_TXT

        def discover(self):
            return []

        def refreshable(self):
            return True

    assert not isinstance(MissingFetch(), Source)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_source_protocol.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docsentry.corpus.sources.base'`

- [ ] **Step 3: 实现 `sources/base.py`**

```python
"""The ``Source`` abstraction -- design spec 4.3 and 6.1.2.

A source holds a **pointer**, never a copy. That is the whole corpus-layer
argument: uploads create snapshots, and a snapshot goes stale with no way for
the system to notice. Re-reading a pointer on every run removes the staleness
problem instead of managing it.

Three methods, each earning its place:

* ``discover`` -- what does this source currently expose?
* ``fetch``    -- read one of those things, now.
* ``refreshable`` -- can that happen without a human? (``snapshot`` sources: no,
  which is precisely why the project does not build an upload flow.)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from docsentry.models import DocRef, SourceKind


@dataclass
class Fetched:
    """Raw bytes for one reference, plus when they were retrieved."""

    ref: DocRef
    data: bytes
    fetched_at: datetime


@runtime_checkable
class Source(Protocol):
    name: str
    kind: SourceKind

    def discover(self) -> list[DocRef]:
        """Every document reference this source currently exposes, sorted."""
        ...

    def fetch(self, ref: DocRef) -> Fetched:
        """Read one reference's current bytes. Raises on failure."""
        ...

    def refreshable(self) -> bool:
        """True when the source can be re-polled with no human in the loop."""
        ...
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_source_protocol.py -v`
Expected: `3 passed`

- [ ] **Step 5: 提交**

```bash
git add src/docsentry/corpus/sources/base.py tests/test_source_protocol.py
git commit -m "feat(m1): Source 协议 — 数据源可替换点"
```

---

## Task 7: LlmsTxtSource — 索引解析与递归展开

**Files:**
- Create: `src/docsentry/corpus/sources/llms_txt.py`
- Test: `tests/test_llms_txt_discover.py`

> **两种索引形态都必须支持**（design spec 6.1.3）：
> - **平铺** — `modelcontextprotocol.io/llms.txt` 直接列出 `.md`
> - **层级** — `docs.langchain.com/llms.txt` 列出的是**子索引**（`.../llms.txt`），必须递归展开
>
> 递归上限 `MAX_INDEX_DEPTH = 2`，用已访问集合防环。实测 LangChain 只需 1 层，上限是安全网。
>
> **⚠️ 上面这个分法是简化，2026-09-21 复核发现反例**：LangChain 顶层 `llms.txt`
> **同一个文件里两种形态并存**——58 个 `llms.txt` 子索引在 `### Section indexes` 下，
> 另有 **119 条直连 `.md`** 分散在 `## Docs` / `## Open source` / `## LangSmith Fleet` /
> `## Agent Server API` 四段。所以 `discover()` **不能按文件二选一**，必须同时走两条路。
>
> 复核的其他数字**全部无误**：MCP 347 条唯一 `.md`（过滤后 252）、LangChain
> `/oss/python/llms.txt` 369 条唯一 `.md`；两边均 0 个 URL 含 `?` / `#` / `:` 或端口。
> 一处新增：MCP 的 `llms.txt` 有 **352 条链接但仅 347 唯一**——文件内 5 条重复，
> **解析必须去重**（注：`test_discover_deduplicates_repeated_entries` 已覆盖此点）。
>
> **⚠️ 一处测试缺口，实现本任务时补上（2026-09-21 发现）**：Step 3 的实现里有
> `sorted(found.values(), key=lambda ref: ref.locator)`，但 Step 1 的 18 个测试
> **没有一条断言顺序**。Task 9 有对应的
> `test_discover_finds_markdown_recursively_and_sorted`，Task 7 缺——而 Task 7
> 要遍历子索引树与 `dict`，顺序**恰恰不是天然确定的**（Task 9 反倒已钉住）。
> 请补一条 `test_discover_is_sorted`，钉住 `Source.discover()` docstring 里
> "sorted" 这个契约。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_llms_txt_discover.py
import httpx
import pytest

from docsentry.corpus.sources.llms_txt import LlmsTxtSource, parse_llms_txt

ROOT = "https://docs.example.com/llms.txt"


def _client(pages: dict[str, str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in pages:
            return httpx.Response(200, text=pages[url])
        return httpx.Response(404, text=f"not found: {url}")

    return httpx.Client(transport=httpx.MockTransport(handler))


def _source(pages: dict[str, str], **kwargs) -> LlmsTxtSource:
    return LlmsTxtSource(
        name="example",
        llms_txt=ROOT,
        client=_client(pages),
        max_depth=kwargs.pop("max_depth", 2),
        **kwargs,
    )


# --- parse_llms_txt -------------------------------------------------------

def test_parses_title_url_and_description():
    text = "- [Title A](https://docs.example.com/a.md): the description\n"

    assert parse_llms_txt(text) == [("Title A", "https://docs.example.com/a.md", "the description")]


def test_description_is_optional():
    text = "- [Title A](https://docs.example.com/a.md)\n"

    assert parse_llms_txt(text)[0][2] == ""


def test_titles_with_brackets_and_punctuation_survive():
    text = "- [What is the Model Context Protocol (MCP)?](https://docs.example.com/a.md)\n"

    assert parse_llms_txt(text)[0][0] == "What is the Model Context Protocol (MCP)?"


def test_headings_prose_and_blockquotes_are_ignored():
    text = (
        "# Docs by Example\n"
        "> Some prose about the docs.\n"
        "## Section indexes\n"
        "\n"
        "- [Real](https://docs.example.com/a.md)\n"
    )

    assert parse_llms_txt(text) == [("Real", "https://docs.example.com/a.md", "")]


def test_relative_urls_resolve_against_base():
    text = "- [A](/a.md)\n"

    assert parse_llms_txt(text, base=ROOT)[0][1] == "https://docs.example.com/a.md"


# --- discover: flat -------------------------------------------------------

def test_discover_flat_index():
    source = _source({ROOT: "- [A](https://docs.example.com/a.md)\n- [B](https://docs.example.com/b.md)\n"})

    refs = source.discover()

    assert [r.locator for r in refs] == [
        "https://docs.example.com/a.md",
        "https://docs.example.com/b.md",
    ]
    assert refs[0].source == "example"
    assert refs[0].title == "A"


def test_discover_skips_directory_entries_and_non_md():
    source = _source(
        {
            ROOT: (
                "- [Dir](https://docs.example.com/sub/)\n"
                "- [Page](https://docs.example.com/page)\n"
                "- [Real](https://docs.example.com/a.md)\n"
            )
        }
    )

    assert [r.locator for r in source.discover()] == ["https://docs.example.com/a.md"]


def test_discover_deduplicates_repeated_entries():
    source = _source(
        {
            ROOT: (
                "- [A](https://docs.example.com/a.md)\n"
                "- [A again](https://docs.example.com/a.md)\n"
            )
        }
    )

    assert len(source.discover()) == 1


# --- discover: hierarchical -----------------------------------------------

def test_discover_expands_sub_indexes():
    source = _source(
        {
            ROOT: "- [Python](https://docs.example.com/oss/python/llms.txt)\n",
            "https://docs.example.com/oss/python/llms.txt": (
                "- [A](https://docs.example.com/oss/python/a.md)\n"
                "- [B](https://docs.example.com/oss/python/b.md)\n"
            ),
        }
    )

    assert [r.locator for r in source.discover()] == [
        "https://docs.example.com/oss/python/a.md",
        "https://docs.example.com/oss/python/b.md",
    ]


def test_depth_limit_stops_recursion():
    pages = {
        ROOT: "- [L1](https://docs.example.com/l1/llms.txt)\n",
        "https://docs.example.com/l1/llms.txt": "- [L2](https://docs.example.com/l2/llms.txt)\n",
        "https://docs.example.com/l2/llms.txt": "- [L3](https://docs.example.com/l3/llms.txt)\n",
        "https://docs.example.com/l3/llms.txt": "- [Deep](https://docs.example.com/deep.md)\n",
    }

    # depth 0 = root, 1 = l1, 2 = l2 -> l3 is refused, so deep.md is unreachable
    assert _source(pages, max_depth=2).discover() == []


def test_cycle_between_indexes_terminates():
    pages = {
        ROOT: "- [A](https://docs.example.com/a/llms.txt)\n",
        "https://docs.example.com/a/llms.txt": "- [Back](https://docs.example.com/llms.txt)\n",
    }

    assert _source(pages).discover() == []


def test_self_referencing_index_terminates():
    pages = {
        ROOT: "- [Self](https://docs.example.com/llms.txt)\n- [Real](https://docs.example.com/a.md)\n",
    }

    assert [r.locator for r in _source(pages).discover()] == ["https://docs.example.com/a.md"]


# --- discover: url_include ------------------------------------------------

def test_url_include_filters_pages_and_sub_indexes():
    pages = {
        ROOT: (
            "- [Py](https://docs.example.com/oss/python/llms.txt)\n"
            "- [JS](https://docs.example.com/oss/javascript/llms.txt)\n"
        ),
        "https://docs.example.com/oss/python/llms.txt": "- [A](https://docs.example.com/oss/python/a.md)\n",
        "https://docs.example.com/oss/javascript/llms.txt": "- [B](https://docs.example.com/oss/javascript/b.md)\n",
    }

    refs = _source(pages, url_include=["/oss/python/"]).discover()

    assert [r.locator for r in refs] == ["https://docs.example.com/oss/python/a.md"]


def test_multiple_url_include_needles_union():
    pages = {
        ROOT: (
            "- [A](https://docs.example.com/docs/a.md)\n"
            "- [B](https://docs.example.com/specification/b.md)\n"
            "- [C](https://docs.example.com/seps/c.md)\n"
        )
    }

    refs = _source(pages, url_include=["/docs/", "/specification/"]).discover()

    assert [r.locator for r in refs] == [
        "https://docs.example.com/docs/a.md",
        "https://docs.example.com/specification/b.md",
    ]


def test_no_url_include_means_keep_everything():
    source = _source({ROOT: "- [A](https://docs.example.com/anything/a.md)\n"})

    assert len(source.discover()) == 1


# --- version hints --------------------------------------------------------

def test_discover_leaves_version_hint_unset():
    source = _source({ROOT: "- [A](https://docs.example.com/docs/2026-07-28/a.md)\n"})

    assert source.discover()[0].version_hint is None


def test_discover_raises_on_unreachable_root():
    with pytest.raises(httpx.HTTPStatusError):
        _source({}).discover()


# --- keep_all_versions ----------------------------------------------------

def test_keep_all_versions_true_returns_every_version():
    pages = {
        ROOT: (
            "- [A old](https://docs.example.com/docs/2025-11-25/a.md)\n"
            "- [A new](https://docs.example.com/docs/2026-07-28/a.md)\n"
        )
    }

    assert len(_source(pages, keep_all_versions=True).discover()) == 2


def test_keep_all_versions_false_prunes_to_the_newest():
    pages = {
        ROOT: (
            "- [A old](https://docs.example.com/docs/2025-11-25/a.md)\n"
            "- [A new](https://docs.example.com/docs/2026-07-28/a.md)\n"
            "- [B](https://docs.example.com/community/b.md)\n"
        )
    }

    refs = _source(pages, keep_all_versions=False).discover()

    assert [r.locator for r in refs] == [
        "https://docs.example.com/community/b.md",
        "https://docs.example.com/docs/2026-07-28/a.md",
    ]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_llms_txt_discover.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docsentry.corpus.sources.llms_txt'`

- [ ] **Step 3: 实现 `llms_txt.py` 的解析与展开部分**

```python
"""``llms_txt`` source: a docs site that publishes an index of its own pages.

Two index shapes exist in the wild and both must work -- design spec 6.1.3:

* **flat** -- ``modelcontextprotocol.io/llms.txt`` lists ``.md`` pages directly.
* **hierarchical** -- ``docs.langchain.com/llms.txt`` lists *sub-indexes*
  (other ``llms.txt`` files), which are expanded recursively.

Recursion is capped at ``max_depth`` and guarded by a visited set, so a site
that links back to its own root cannot loop. Measured on the real corpora,
LangChain needs exactly one level; the cap is a safety net, not a working
constraint.

Note there is no ETag / conditional-GET path. MCP serves no ETag and its
``Last-Modified`` is the site *build* time rather than the page's, so a full
body hash is the only trustworthy change signal -- every run re-downloads.
At ~700 pages that is a few seconds and ~14 MB.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from docsentry.corpus.sources.base import Fetched
from docsentry.corpus.versioning import prune_to_latest
from docsentry.models import DocRef, SourceKind, utcnow

# ``- [Title](url): description`` -- the description is optional.
_ENTRY_RE = re.compile(
    r"^\s*[-*]\s*\[(?P<title>[^\]]*)\]\((?P<url>[^)\s]+)\)\s*(?::\s*(?P<desc>.*))?$"
)

# Root index is depth 0; sub-indexes may nest two levels below it.
MAX_INDEX_DEPTH = 2


def parse_llms_txt(text: str, base: str = "") -> list[tuple[str, str, str]]:
    """Parse an ``llms.txt`` into ``(title, url, description)`` triples.

    Headings, prose and blockquotes are skipped: only list entries that carry a
    markdown link count. Relative URLs resolve against ``base``.
    """
    entries: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        match = _ENTRY_RE.match(line)
        if not match:
            continue
        url = match.group("url").strip()
        if not url:
            continue
        entries.append(
            (
                match.group("title").strip(),
                urljoin(base, url) if base else url,
                (match.group("desc") or "").strip(),
            )
        )
    return entries


def _normalize(url: str) -> str:
    """Key for the visited set: scheme/host case- and fragment-insensitive."""
    parts = urlparse(url)
    return urlunparse((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.params, "", ""))


class LlmsTxtSource:
    """Holds the URL of an index, not a copy of the pages it lists."""

    def __init__(
        self,
        *,
        name: str,
        llms_txt: str,
        url_include: tuple[str, ...] | list[str] = (),
        keep_all_versions: bool = True,
        max_depth: int = MAX_INDEX_DEPTH,
        client: httpx.Client | None = None,
        timeout_s: float = 30.0,
        retries: int = 3,
    ) -> None:
        self.name = name
        self.kind = SourceKind.LLMS_TXT
        self.llms_txt = llms_txt
        self.url_include = tuple(url_include)
        self.keep_all_versions = keep_all_versions
        self.max_depth = max_depth
        self._client = client
        self._timeout_s = timeout_s
        self._retries = retries

    @property
    def client(self) -> httpx.Client:
        """Lazily built so tests can inject a ``MockTransport`` client."""
        if self._client is None:
            self._client = httpx.Client(
                timeout=self._timeout_s,
                follow_redirects=True,
                transport=httpx.HTTPTransport(retries=self._retries),
            )
        return self._client

    def refreshable(self) -> bool:
        return True

    def discover(self) -> list[DocRef]:
        """Walk the index tree and return every reachable ``.md`` page, sorted.

        With ``keep_all_versions: false`` the result is pruned to the newest
        version per page *here*, at discovery time -- so the older versions
        simply vanish from the discovered set and flow into the pipeline's
        normal delete phase, rather than needing a separate purge path.
        """
        found: dict[str, DocRef] = {}
        self._expand(self.llms_txt, depth=0, visited=set(), out=found)
        refs = sorted(found.values(), key=lambda ref: ref.locator)
        return refs if self.keep_all_versions else prune_to_latest(refs)

    def included(self, url: str) -> bool:
        """Does ``url`` pass the configured include filter?

        Applied to sub-index URLs too, so an unrelated branch of a site is
        never fetched at all -- worth ~50 requests on ``docs.langchain.com``.
        """
        if not self.url_include:
            return True
        return any(needle in url for needle in self.url_include)

    def _expand(self, index_url: str, *, depth: int, visited: set[str], out: dict[str, DocRef]) -> None:
        key = _normalize(index_url)
        if key in visited or depth > self.max_depth:
            return
        visited.add(key)

        for title, url, _description in parse_llms_txt(self._get_text(index_url), base=index_url):
            if not self.included(url):
                continue
            if url.endswith("llms.txt"):
                self._expand(url, depth=depth + 1, visited=visited, out=out)
            elif url.endswith(".md"):
                out.setdefault(
                    url,
                    DocRef(
                        source=self.name,
                        kind=self.kind,
                        locator=url,
                        version_hint=None,  # version comes from the URL path, in versioning.py
                        title=title,
                    ),
                )
            # anything else -- directory entries ending in "/", extensionless
            # pages -- is not a markdown document and is skipped

    def _get_text(self, url: str) -> str:
        response = self.client.get(url)
        response.raise_for_status()
        return response.text

    def fetch(self, ref: DocRef) -> Fetched:
        raise NotImplementedError  # implemented in Task 8
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_llms_txt_discover.py -v`
Expected: `19 passed`

- [ ] **Step 5: 提交**

```bash
git add src/docsentry/corpus/sources/llms_txt.py tests/test_llms_txt_discover.py
git commit -m "feat(m1): llms.txt 解析 — 平铺/层级双形态 + 递归展开防环"
```

---

## Task 8: LlmsTxtSource — 抓取

**Files:**
- Modify: `src/docsentry/corpus/sources/llms_txt.py`
- Test: `tests/test_llms_txt_fetch.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_llms_txt_fetch.py
import httpx
import pytest

from docsentry.corpus.sources.llms_txt import LlmsTxtSource
from docsentry.models import DocRef, SourceKind

ROOT = "https://docs.example.com/llms.txt"


def _source(pages: dict[str, str], binary: dict[str, bytes] | None = None) -> LlmsTxtSource:
    binary = binary or {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in binary:
            return httpx.Response(200, content=binary[url])
        if url in pages:
            return httpx.Response(200, text=pages[url])
        return httpx.Response(404)

    return LlmsTxtSource(name="example", llms_txt=ROOT, client=httpx.Client(transport=httpx.MockTransport(handler)))


def _ref(locator: str) -> DocRef:
    return DocRef(source="example", kind=SourceKind.LLMS_TXT, locator=locator)


def test_fetch_returns_raw_bytes():
    source = _source({}, binary={"https://docs.example.com/a.md": "# A\nbody\n".encode("utf-8")})

    fetched = source.fetch(_ref("https://docs.example.com/a.md"))

    assert fetched.data == "# A\nbody\n".encode("utf-8")
    assert fetched.ref.locator == "https://docs.example.com/a.md"


def test_fetch_records_a_timestamp():
    source = _source({}, binary={"https://docs.example.com/a.md": b"# A\n"})

    fetched = source.fetch(_ref("https://docs.example.com/a.md"))

    assert fetched.fetched_at.tzinfo is not None


def test_fetch_encodes_non_ascii_as_utf8():
    body = "# 中文标题\n内容\n".encode("utf-8")
    source = _source({}, binary={"https://docs.example.com/a.md": body})

    assert source.fetch(_ref("https://docs.example.com/a.md")).data.decode("utf-8") == "# 中文标题\n内容\n"


def test_fetch_raises_on_404():
    source = _source({})

    with pytest.raises(httpx.HTTPStatusError):
        source.fetch(_ref("https://docs.example.com/missing.md"))


def test_refreshable_is_true():
    assert _source({}).refreshable() is True


def test_discover_then_fetch_round_trip():
    source = _source(
        {ROOT: "- [A](https://docs.example.com/a.md)\n"},
        binary={"https://docs.example.com/a.md": b"# A\n"},
    )

    ref = source.discover()[0]

    assert source.fetch(ref).data == b"# A\n"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_llms_txt_fetch.py -v`
Expected: FAIL — `NotImplementedError` on every fetch test

- [ ] **Step 3: 替换 `fetch` 桩实现**

把 `llms_txt.py` 末尾的：

```python
    def fetch(self, ref: DocRef) -> Fetched:
        raise NotImplementedError  # implemented in Task 8
```

替换为：

```python
    def fetch(self, ref: DocRef) -> Fetched:
        """Download one page's raw bytes.

        Returns bytes rather than text so the content hash is computed over
        exactly what the server sent, and so a future non-UTF-8 format is not
        silently mangled on the way in.
        """
        response = self.client.get(ref.locator)
        response.raise_for_status()
        return Fetched(ref=ref, data=response.content, fetched_at=utcnow())
```

`utcnow` 在 Task 7 已随 import 引入，无需改动 import 区。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_llms_txt_fetch.py tests/test_llms_txt_discover.py -v`
Expected: `25 passed`

- [ ] **Step 5: 提交**

```bash
git add src/docsentry/corpus/sources/llms_txt.py tests/test_llms_txt_fetch.py
git commit -m "feat(m1): llms.txt 抓取 — 返回原始字节，异常向上抛"
```

---

## Task 9: LocalDirectorySource

**Files:**
- Create: `src/docsentry/corpus/sources/local_dir.py`
- Test: `tests/test_local_dir_source.py`

> **不复制文件**。design spec 6.1.2 的核心主张：注册的是**指针**。索引每次重扫目录，文件改了自然被 hash 发现——因此**不需要 watchdog 常驻监控**，索引本来就是定期/手动触发的批处理。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_local_dir_source.py
from pathlib import Path

import pytest

from docsentry.corpus.sources.local_dir import LocalDirectorySource
from docsentry.models import SourceKind


def _make_source(tmp_path: Path, **kwargs) -> LocalDirectorySource:
    return LocalDirectorySource(name="internal", path=tmp_path, **kwargs)


def test_discover_finds_markdown_recursively_and_sorted(tmp_path):
    (tmp_path / "b.md").write_text("# B\n", encoding="utf-8")
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "c.md").write_text("# C\n", encoding="utf-8")

    refs = _make_source(tmp_path).discover()

    assert [Path(r.locator).name for r in refs] == ["a.md", "b.md", "c.md"]


def test_discover_ignores_non_markdown(tmp_path):
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("nope\n", encoding="utf-8")
    (tmp_path / "c.pdf").write_bytes(b"%PDF-")

    assert len(_make_source(tmp_path).discover()) == 1


def test_discover_carries_kind_and_source(tmp_path):
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")

    ref = _make_source(tmp_path).discover()[0]

    assert ref.kind is SourceKind.LOCAL_DIR
    assert ref.source == "internal"


def test_default_version_becomes_the_version_hint(tmp_path):
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")

    refs = _make_source(tmp_path, default_version="internal-2026Q3").discover()

    assert refs[0].version_hint == "internal-2026Q3"


def test_no_default_version_leaves_hint_unset(tmp_path):
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")

    assert _make_source(tmp_path).discover()[0].version_hint is None


def test_locator_is_an_absolute_path(tmp_path):
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")

    assert Path(_make_source(tmp_path).discover()[0].locator).is_absolute()


def test_missing_directory_discoveres_nothing(tmp_path):
    assert _make_source(tmp_path / "does-not-exist").discover() == []


def test_empty_directory_discoveres_nothing(tmp_path):
    assert _make_source(tmp_path).discover() == []


def test_fetch_reads_current_bytes(tmp_path):
    target = tmp_path / "a.md"
    target.write_text("# A\n", encoding="utf-8")
    source = _make_source(tmp_path)

    fetched = source.fetch(source.discover()[0])

    assert fetched.data == b"# A\n"


def test_fetch_sees_an_edit(tmp_path):
    target = tmp_path / "a.md"
    target.write_text("# A\n", encoding="utf-8")
    source = _make_source(tmp_path)
    ref = source.discover()[0]

    target.write_text("# A edited\n", encoding="utf-8")

    assert source.fetch(ref).data == b"# A edited\n"


def test_fetch_raises_when_file_vanished(tmp_path):
    target = tmp_path / "a.md"
    target.write_text("# A\n", encoding="utf-8")
    source = _make_source(tmp_path)
    ref = source.discover()[0]

    target.unlink()

    with pytest.raises(FileNotFoundError):
        source.fetch(ref)


def test_refreshable_is_true(tmp_path):
    assert _make_source(tmp_path).refreshable() is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_local_dir_source.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docsentry.corpus.sources.local_dir'`

- [ ] **Step 3: 实现 `local_dir.py`**

```python
"""``local_dir`` source: a directory of documents already on disk.

Nothing is copied. The design's rule -- register a pointer, never upload a
copy -- means the directory *is* the corpus: every run re-scans it and
hash-compares, so an edit is noticed without a watcher process. That is why
there is no ``watchdog`` dependency anywhere in this project (design spec
6.1.2): indexing is a batch job, and re-scanning is simpler and sufficient.

This is the path a private corpus takes -- an internal wiki export, a
handbook, a vendor SDK dump. No ``llms.txt`` required.
"""

from __future__ import annotations

from pathlib import Path

from docsentry.corpus.sources.base import Fetched
from docsentry.models import DocRef, SourceKind, utcnow


class LocalDirectorySource:
    def __init__(
        self,
        *,
        name: str,
        path: Path | str,
        default_version: str | None = None,
        patterns: tuple[str, ...] = ("*.md",),
    ) -> None:
        self.name = name
        self.kind = SourceKind.LOCAL_DIR
        self.path = Path(path)
        self.default_version = default_version
        self.patterns = tuple(patterns)

    def refreshable(self) -> bool:
        return True

    def discover(self) -> list[DocRef]:
        """Every matching file under the directory, absolute paths, sorted.

        A missing directory yields nothing rather than raising: the source may
        legitimately be empty (the shipped config disables it for that reason),
        and a hard failure here would abort the whole fetch run.
        """
        if not self.path.is_dir():
            return []

        refs: list[DocRef] = []
        for pattern in self.patterns:
            for file in self.path.rglob(pattern):
                if not file.is_file():
                    continue
                refs.append(
                    DocRef(
                        source=self.name,
                        kind=self.kind,
                        locator=str(file.resolve()),
                        version_hint=self.default_version,
                        title="",  # derived from the document's first heading
                    )
                )
        refs.sort(key=lambda ref: ref.locator)
        return refs

    def fetch(self, ref: DocRef) -> Fetched:
        """Read current bytes. Sees edits immediately -- there is no cache."""
        return Fetched(
            ref=ref,
            data=Path(ref.locator).read_bytes(),
            fetched_at=utcnow(),
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_local_dir_source.py -v`
Expected: `12 passed`

- [ ] **Step 5: 提交**

```bash
git add src/docsentry/corpus/sources/local_dir.py tests/test_local_dir_source.py
git commit -m "feat(m1): local_dir 源 — 指针式重扫，不复制不做 watchdog"
```

---

## Task 10: 转换器

**Files:**
- Create: `src/docsentry/corpus/converters/base.py`
- Create: `src/docsentry/corpus/converters/markdown.py`
- Test: `tests/test_converters.py`

> **两处对设计文档字面的偏离，理由在此**：
>
> 1. 设计写 `Converter.convert(path) -> Document`。但转换器不知道 `source` / `version` / `fetched_at`，让 `Document` 由 pipeline 组装、转换器只产出「文本 + 标题 + 原格式」，职责才干净。
> 2. 设计写 `MarkdownConverter`「直接读取」。这里额外剥掉页首的 `> ## Documentation Index` 样板块 —— MCP 与 LangChain 的**每一页**都有它，约 60 token，内容跨 700 篇完全相同。它是指南性导航文字，不是文档内容：留着会进每个文档的第一个 chunk，对 embedding 是纯噪声，对 BM25 是高频干扰项。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_converters.py
from pathlib import Path

from docsentry.corpus.converters.base import ConvertedDoc, Converter
from docsentry.corpus.converters.markdown import MarkdownConverter, first_heading, strip_index_banner

BANNER = (
    "> ## Documentation Index\n"
    "> Fetch the complete documentation index at: https://example.com/llms.txt\n"
    "> Use this file to discover all available pages before exploring further.\n"
    "\n"
)


# --- strip_index_banner ---------------------------------------------------

def test_strips_the_real_banner():
    assert strip_index_banner(BANNER + "# Build a server\n") == "# Build a server\n"


def test_leaves_text_without_a_banner_alone():
    assert strip_index_banner("# Title\nbody\n") == "# Title\nbody\n"


def test_keeps_a_genuine_leading_blockquote():
    text = "> **Note:** this is real content.\n\n# Title\n"

    assert strip_index_banner(text) == text


def test_strips_banner_before_a_leading_blockquote_of_real_content():
    text = BANNER + "> **Note:** real content.\n\n# Title\n"

    assert strip_index_banner(text).startswith("> **Note:**")


def test_banner_in_the_middle_is_untouched():
    text = "# Title\n\n" + BANNER

    assert strip_index_banner(text) == text


def test_handles_file_that_is_only_a_banner():
    assert strip_index_banner(BANNER) == ""


# --- first_heading --------------------------------------------------------

def test_first_heading_finds_atx_heading():
    assert first_heading("# Build an MCP server\n\nbody\n") == "Build an MCP server"


def test_first_heading_returns_empty_when_absent():
    assert first_heading("just prose\n") == ""


def test_first_heading_skips_headings_inside_code_fences():
    text = "```\n# not a title\n```\n\n# Real Title\n"

    assert first_heading(text) == "Real Title"


def test_first_heading_handles_tilde_fences():
    text = "~~~\n# not a title\n~~~\n\n# Real Title\n"

    assert first_heading(text) == "Real Title"


# --- MarkdownConverter ----------------------------------------------------

def test_converter_reports_supported_extensions():
    assert MarkdownConverter().supported == {".md", ".markdown"}


def test_converter_reads_and_normalizes(tmp_path):
    path = tmp_path / "a.md"
    path.write_text(BANNER + "# Build a server\n\nbody\n", encoding="utf-8")

    result = MarkdownConverter().convert(path)

    assert result == ConvertedDoc(
        text="# Build a server\n\nbody\n",
        title="Build a server",
        origin_format="md",
    )


def test_converter_sets_origin_format_from_suffix(tmp_path):
    path = tmp_path / "a.markdown"
    path.write_text("# A\n", encoding="utf-8")

    assert MarkdownConverter().convert(path).origin_format == "md"


def test_converter_survives_undecodable_bytes(tmp_path):
    path = tmp_path / "a.md"
    path.write_bytes(b"# A\n\xff\xfe broken\n")

    assert MarkdownConverter().convert(path).title == "A"


def test_markdown_converter_satisfies_protocol():
    assert isinstance(MarkdownConverter(), Converter)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_converters.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docsentry.corpus.converters.base'`

- [ ] **Step 3: 实现 `converters/base.py`**

```python
"""The ``Converter`` abstraction -- design spec 4.3 and 6.2.

A converter takes a file on disk and returns normalised Markdown plus the few
facts the pipeline cannot derive itself. It deliberately does *not* build a
``Document``: source, version, doc id and timestamps are the pipeline's to
assemble, and a converter that guessed them would be wrong in the same way for
every format.

M1 ships the one mandatory converter (Markdown). PDF / Office / image
converters are optional per the design's priority table and land only if the
schedule allows.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class ConvertedDoc:
    text: str
    title: str
    origin_format: str


@runtime_checkable
class Converter(Protocol):
    supported: set[str]

    def convert(self, path: Path) -> ConvertedDoc:
        """Read ``path`` and return normalised Markdown."""
        ...
```

- [ ] **Step 4: 实现 `converters/markdown.py`**

```python
"""``MarkdownConverter`` -- the only mandatory converter (design spec 6.2).

Beyond reading the file it does two small normalisations, both of which exist
because of what the real corpora look like:

* **Strips the page-top ``> ## Documentation Index`` banner.** Every MCP and
  LangChain page carries one. It is navigation boilerplate, byte-identical
  across ~700 documents -- pure noise for both the embedding and the BM25
  index, and it would otherwise occupy the head of every document's first
  chunk. Only a *leading* blockquote is considered, and only when it actually
  says "Documentation Index", so genuine blockquote content is never eaten.
* **Derives a title from the first heading**, skipping fenced code so a ``#``
  comment inside a shell snippet is not mistaken for a title. ``llms_txt``
  sources supply titles already; this is what makes a bare ``local_dir`` usable.
"""

from __future__ import annotations

import re
from pathlib import Path

from docsentry.corpus.converters.base import ConvertedDoc

_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_BANNER_MARKER = "Documentation Index"


def strip_index_banner(text: str) -> str:
    """Drop a leading ``> ## Documentation Index`` blockquote, if present."""
    lines = text.splitlines(keepends=True)

    end = 0
    while end < len(lines) and lines[end].lstrip().startswith(">"):
        end += 1
    if end == 0:
        return text
    if _BANNER_MARKER not in "".join(lines[:end]):
        return text  # a real blockquote at the top -- leave it alone

    while end < len(lines) and not lines[end].strip():
        end += 1
    return "".join(lines[end:])


def first_heading(text: str) -> str:
    """First ATX heading outside a fenced code block, or ``""``."""
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING_RE.match(line)
        if match:
            return match.group(1).strip()
    return ""


class MarkdownConverter:
    supported = {".md", ".markdown"}

    def convert(self, path: Path) -> ConvertedDoc:
        raw = path.read_text(encoding="utf-8", errors="replace")
        text = strip_index_banner(raw)
        return ConvertedDoc(text=text, title=first_heading(text), origin_format="md")
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_converters.py -v`
Expected: `15 passed`

- [ ] **Step 6: 提交**

```bash
git add src/docsentry/corpus/converters tests/test_converters.py
git commit -m "feat(m1): Markdown 转换器 — 剥样板块 + 提标题"
```

---

## Task 11: 变更检测 manifest

**Files:**
- Create: `src/docsentry/corpus/manifest.py`
- Test: `tests/test_manifest.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_manifest.py
import json
from datetime import datetime, timezone

from docsentry.corpus.manifest import Manifest, ManifestEntry


def _entry(content_hash="abc", version="2026-07-28", fetched_at=None):
    return ManifestEntry(
        content_hash=content_hash,
        version=version,
        fetched_at=fetched_at or datetime(2026, 9, 20, tzinfo=timezone.utc),
    )


def test_new_manifest_is_empty():
    assert len(Manifest()) == 0
    assert Manifest().locators() == set()


def test_set_then_get():
    manifest = Manifest()
    manifest.set("https://x/a.md", _entry())

    assert manifest.get("https://x/a.md").content_hash == "abc"
    assert "https://x/a.md" in manifest
    assert manifest.get("https://x/nope.md") is None


def test_remove():
    manifest = Manifest()
    manifest.set("https://x/a.md", _entry())

    manifest.remove("https://x/a.md")

    assert "https://x/a.md" not in manifest
    assert manifest.locators() == set()


def test_remove_of_unknown_locator_is_a_noop():
    manifest = Manifest()

    manifest.remove("https://x/nope.md")  # must not raise

    assert len(manifest) == 0


def test_save_then_load_round_trip(tmp_path):
    manifest = Manifest()
    manifest.set("https://x/a.md", _entry(content_hash="h1", version="2026-07-28"))
    manifest.set("https://x/b.md", _entry(content_hash="h2", version="draft"))
    path = tmp_path / "manifest.json"

    manifest.save(path)
    restored = Manifest.load(path)

    assert restored.locators() == manifest.locators()
    assert restored.get("https://x/a.md").content_hash == "h1"
    assert restored.get("https://x/b.md").version == "draft"


def test_load_missing_file_returns_empty(tmp_path):
    assert len(Manifest.load(tmp_path / "nope.json")) == 0


def test_load_corrupt_file_returns_empty(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{not json", encoding="utf-8")

    assert len(Manifest.load(path)) == 0


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "manifest.json"

    Manifest().save(path)

    assert path.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_creates_parent_directory(tmp_path):
    path = tmp_path / "deep" / "nested" / "manifest.json"

    Manifest().save(path)

    assert path.exists()


def test_saved_json_is_sorted_and_human_readable(tmp_path):
    manifest = Manifest()
    manifest.set("https://x/b.md", _entry())
    manifest.set("https://x/a.md", _entry())
    path = tmp_path / "manifest.json"

    manifest.save(path)

    text = path.read_text(encoding="utf-8")
    assert text.index("https://x/a.md") < text.index("https://x/b.md")
    assert json.loads(text)["https://x/a.md"]["version"] == "2026-07-28"


def test_manifest_does_not_store_paths():
    # Paths are derived from the locator; storing them would be a second
    # source of truth that can drift.
    keys = set(ManifestEntry(content_hash="h", version="v", fetched_at=datetime.now(timezone.utc)).to_json())

    assert keys == {"content_hash", "version", "fetched_at"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docsentry.corpus.manifest'`

- [ ] **Step 3: 实现 `manifest.py`**

```python
"""Change detection -- design spec 6.1.4.

The manifest is the only durable record of what we already have. It stores
just enough to detect change (``content_hash``) and to explain provenance
(``version``, ``fetched_at``); everything else about a document is re-derived
on every run so the manifest cannot drift away from reality.

Note the deliberate absence of file paths: a locator maps to a path
deterministically via ``paths.raw_relpath``, so storing it would create a
second source of truth that can go stale. There is a test asserting this.

``fetched_at`` means "last time we confirmed this content from the source" --
it is refreshed on every run, including runs where the content was unchanged
but was re-downloaded and re-hashed. That is what makes the health check's
"not verified in N days" warning meaningful.

Writes are atomic (temp file + rename), so a crash mid-write leaves the
previous manifest intact rather than a truncated one.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class ManifestEntry:
    content_hash: str
    version: str
    fetched_at: datetime

    def to_json(self) -> dict[str, Any]:
        return {
            "content_hash": self.content_hash,
            "version": self.version,
            "fetched_at": self.fetched_at.isoformat(),
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> ManifestEntry:
        return cls(
            content_hash=raw["content_hash"],
            version=raw["version"],
            fetched_at=datetime.fromisoformat(raw["fetched_at"]),
        )


class Manifest:
    """``locator -> ManifestEntry``, persisted as a single JSON object."""

    def __init__(self, entries: dict[str, ManifestEntry] | None = None) -> None:
        self._entries: dict[str, ManifestEntry] = dict(entries or {})

    def __contains__(self, locator: str) -> bool:
        return locator in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, locator: str) -> ManifestEntry | None:
        return self._entries.get(locator)

    def locators(self) -> set[str]:
        return set(self._entries)

    def items(self):
        return self._entries.items()

    def set(self, locator: str, entry: ManifestEntry) -> None:
        self._entries[locator] = entry

    def remove(self, locator: str) -> None:
        """Idempotent -- removing an unknown locator is not an error."""
        self._entries.pop(locator, None)

    def to_json(self) -> dict[str, Any]:
        return {locator: entry.to_json() for locator, entry in self._entries.items()}

    @classmethod
    def load(cls, path: Path) -> Manifest:
        """Load the manifest; a missing or unreadable file means "start over".

        Rebuilding from an unreadable manifest costs one full re-fetch, which
        is the safe direction to fail: it re-detects everything rather than
        assuming content is present when it may not be.
        """
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return cls()
        return cls({locator: ManifestEntry.from_json(entry) for locator, entry in raw.items()})

    def save(self, path: Path) -> None:
        """Atomic write: temp file in the same directory, then ``os.replace``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_json(), indent=2, sort_keys=True, ensure_ascii=False)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_manifest.py -v`
Expected: `11 passed`

- [ ] **Step 5: 提交**

```bash
git add src/docsentry/corpus/manifest.py tests/test_manifest.py
git commit -m "feat(m1): manifest 变更检测 — 只存 hash/版本/校验时间，原子写"
```

---

## Task 12: 抓取报告

**Files:**
- Create: `src/docsentry/corpus/report.py`
- Test: `tests/test_report.py`

> 设计文档 §6.1.5 的话值得引在这里：**最大的风险不是「更新慢」，而是「你以为更新了，其实某个源抓失败了，索引缺内容是静默的」。** 报告的存在就是为了让失败和缺口可见。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report.py
from datetime import datetime, timezone

from docsentry.corpus.report import FetchReport, SourceReport


def test_source_report_counts_versions_into_buckets():
    report = SourceReport(name="mcp", kind="llms_txt")

    report.count_version("2026-07-28")
    report.count_version("2025-11-25")
    report.count_version("draft")
    report.count_version("unknown")

    assert report.versions == {"dated": 2, "draft": 1, "unknown": 1}


def test_unknown_version_bucket_starts_at_zero():
    assert SourceReport(name="x", kind="llms_txt").versions == {"dated": 0, "draft": 0, "unknown": 0}


def test_labelled_ratio_excludes_unknown():
    report = SourceReport(name="mcp", kind="llms_txt")
    for _ in range(9):
        report.count_version("2026-07-28")
    report.count_version("unknown")

    assert report.labelled_ratio == 0.9


def test_labelled_ratio_of_empty_report_is_zero():
    assert SourceReport(name="x", kind="llms_txt").labelled_ratio == 0.0


def test_failed_is_a_list_of_locator_and_error():
    report = SourceReport(name="mcp", kind="llms_txt")

    report.fail("https://x/broken.md", "HTTPStatusError: 404")

    assert report.failed == [{"locator": "https://x/broken.md", "error": "HTTPStatusError: 404"}]


def _report() -> FetchReport:
    started = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)
    source = SourceReport(name="mcp", kind="llms_txt", discovered=10, added=3, updated=1, skipped=6)
    return FetchReport(started_at=started, duration_s=12.5, sources=[source])


def test_report_totals_sum_across_sources():
    report = _report()
    report.sources.append(SourceReport(name="langgraph", kind="llms_txt", discovered=5, added=5))

    totals = report.totals

    assert totals["discovered"] == 15
    assert totals["added"] == 8
    assert totals["updated"] == 1
    assert totals["skipped"] == 6


def test_report_json_includes_failures_and_version_breakdown():
    report = _report()
    report.sources[0].fail("https://x/broken.md", "boom")

    payload = report.to_json()

    assert payload["sources"][0]["failed"] == [{"locator": "https://x/broken.md", "error": "boom"}]
    assert payload["sources"][0]["versions"] == {"dated": 0, "draft": 0, "unknown": 0}
    assert payload["started_at"] == "2026-09-20T03:00:00+00:00"
    assert payload["duration_s"] == 12.5


def test_report_json_is_json_serialisable():
    import json

    json.dumps(_report().to_json())  # must not raise


def test_summary_mentions_failures_when_present():
    report = _report()
    report.sources[0].fail("https://x/broken.md", "boom")

    text = report.summary()

    assert "1 failed" in text
    assert "https://x/broken.md" in text


def test_summary_is_quiet_when_nothing_failed():
    assert "failed" not in _report().summary().lower()


def test_summary_reports_version_coverage():
    report = _report()
    report.sources[0].count_version("2026-07-28")

    assert "1 dated" in report.summary()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docsentry.corpus.report'`

- [ ] **Step 3: 实现 `report.py`**

```python
"""Fetch reporting -- design spec 6.1.5.

The risk this module exists for is not "updates are slow", it is "you think an
update happened, but one source failed and the index is quietly missing
content". So failures are collected per locator with their error text, and the
version breakdown is reported in three buckets rather than one coverage
number, so that genuinely versionless pages stay visible instead of being
averaged into a figure that looks like an extraction bug.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from docsentry.corpus.versioning import version_bucket

_BUCKETS = ("dated", "draft", "unknown")


@dataclass
class SourceReport:
    name: str
    kind: str
    discovered: int = 0
    added: int = 0
    updated: int = 0
    skipped: int = 0
    deleted: int = 0
    failed: list[dict[str, str]] = field(default_factory=list)
    versions: dict[str, int] = field(default_factory=lambda: {b: 0 for b in _BUCKETS})

    def count_version(self, version: str) -> None:
        bucket = version_bucket(version)
        self.versions[bucket] = self.versions.get(bucket, 0) + 1

    def fail(self, locator: str, error: str) -> None:
        self.failed.append({"locator": locator, "error": error})

    @property
    def labelled_ratio(self) -> float:
        """Share of documents carrying any version label (dated or draft)."""
        total = sum(self.versions.values())
        if total == 0:
            return 0.0
        return (self.versions["dated"] + self.versions["draft"]) / total

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "discovered": self.discovered,
            "added": self.added,
            "updated": self.updated,
            "skipped": self.skipped,
            "deleted": self.deleted,
            "failed": sorted(self.failed, key=lambda item: item["locator"]),
            "versions": dict(self.versions),
            "labelled_ratio": round(self.labelled_ratio, 4),
        }


@dataclass
class FetchReport:
    started_at: datetime
    duration_s: float
    sources: list[SourceReport] = field(default_factory=list)

    @property
    def totals(self) -> dict[str, int]:
        return {
            key: sum(getattr(source, key) for source in self.sources)
            for key in ("discovered", "added", "updated", "skipped", "deleted")
        }

    def to_json(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "duration_s": round(self.duration_s, 3),
            "totals": self.totals,
            "sources": [source.to_json() for source in self.sources],
        }

    def summary(self) -> str:
        """Human-readable block for the console, failures first."""
        lines = [
            f"fetch report  ({self.duration_s:.1f}s)",
            "",
        ]
        for source in self.sources:
            lines.append(
                f"  {source.name:<10} discovered={source.discovered:<5} "
                f"added={source.added:<5} updated={source.updated:<5} "
                f"skipped={source.skipped:<5} deleted={source.deleted}"
            )
            versions = source.versions
            lines.append(
                f"  {'':<10} versions: {versions['dated']} dated, "
                f"{versions['draft']} draft, {versions['unknown']} unknown "
                f"({source.labelled_ratio:.0%} labelled)"
            )
            if source.failed:
                lines.append(f"  {'':<10} {len(source.failed)} failed:")
                for item in sorted(source.failed, key=lambda i: i["locator"]):
                    lines.append(f"  {'':<12} - {item['locator']}: {item['error']}")

        totals = self.totals
        lines.append("")
        lines.append(
            f"  total      discovered={totals['discovered']} added={totals['added']} "
            f"updated={totals['updated']} skipped={totals['skipped']} deleted={totals['deleted']}"
        )
        return "\n".join(lines)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_report.py -v`
Expected: `11 passed`

- [ ] **Step 5: 提交**

```bash
git add src/docsentry/corpus/report.py tests/test_report.py
git commit -m "feat(m1): 抓取报告 — 失败清单 + 版本三分项"
```

---

## Task 13: 同步管线 — 插入阶段

**Files:**
- Create: `src/docsentry/corpus/pipeline.py`
- Test: `tests/test_pipeline_insert.py`

> 本任务只做**插入阶段**，删除阶段在 Task 14。分开是因为 Task 14 要验证的「先插后删」顺序是本里程碑的核心主张，值得独立测试。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_pipeline_insert.py
from pathlib import Path

from docsentry.corpus.converters.markdown import MarkdownConverter
from docsentry.corpus.manifest import Manifest
from docsentry.corpus.pipeline import sync_source
from docsentry.corpus.report import SourceReport
from docsentry.corpus.sources.base import Fetched
from docsentry.models import DocRef, SourceKind, hash_bytes, utcnow


class FakeSource:
    """In-memory source: locator -> bytes. Lets the pipeline be tested with no HTTP."""

    def __init__(self, name="fake", pages=None, fail_on=()):
        self.name = name
        self.kind = SourceKind.LLMS_TXT
        self.pages = dict(pages or {})
        self.fail_on = set(fail_on)

    def discover(self):
        return [
            DocRef(source=self.name, kind=self.kind, locator=locator, title=Path(locator).stem)
            for locator in sorted(self.pages)
        ]

    def fetch(self, ref):
        if ref.locator in self.fail_on:
            raise RuntimeError(f"boom: {ref.locator}")
        return Fetched(ref=ref, data=self.pages[ref.locator], fetched_at=utcnow())

    def refreshable(self):
        return True


def _sync(tmp_path, source, manifest=None, report=None):
    return sync_source(
        source=source,
        converter=MarkdownConverter(),
        raw_root=tmp_path / "raw",
        manifest=manifest or Manifest(),
        report=report or SourceReport(name=source.name, kind="llms_txt"),
        workers=1,
    )


def test_first_sync_adds_every_page(tmp_path):
    source = FakeSource(pages={"https://x/a.md": b"# A\nbody a\n", "https://x/b.md": b"# B\nbody b\n"})
    report = SourceReport(name="fake", kind="llms_txt")

    documents = _sync(tmp_path, source, report=report)

    assert report.discovered == 2
    assert report.added == 2
    assert report.updated == 0
    assert report.skipped == 0
    assert len(documents) == 2


def test_documents_carry_content_and_metadata(tmp_path):
    source = FakeSource(pages={"https://x/docs/2026-07-28/a.md": b"# A\nbody\n"})
    manifest = Manifest()

    documents = _sync(tmp_path, source, manifest=manifest)

    document = documents[0]
    assert document.content == "# A\nbody\n"
    assert document.title == "A"
    assert document.version == "2026-07-28"
    assert document.kind is SourceKind.LLMS_TXT
    assert document.origin_format == "md"
    assert document.url == "https://x/docs/2026-07-28/a.md"
    assert document.content_hash == hash_bytes(b"# A\nbody\n")


def test_raw_files_are_written_under_raw_root(tmp_path):
    source = FakeSource(pages={"https://x/docs/2026-07-28/a.md": b"# A\n"})

    _sync(tmp_path, source)

    assert (tmp_path / "raw" / "fake" / "x" / "docs" / "2026-07-28" / "a.md").read_bytes() == b"# A\n"


def test_manifest_records_hash_and_version(tmp_path):
    source = FakeSource(pages={"https://x/docs/2026-07-28/a.md": b"# A\n"})
    manifest = Manifest()

    _sync(tmp_path, source, manifest=manifest)

    entry = manifest.get("https://x/docs/2026-07-28/a.md")
    assert entry.content_hash == hash_bytes(b"# A\n")
    assert entry.version == "2026-07-28"


def test_second_sync_skips_unchanged_pages(tmp_path):
    source = FakeSource(pages={"https://x/a.md": b"# A\n"})
    manifest = Manifest()
    _sync(tmp_path, source, manifest=manifest)

    report = SourceReport(name="fake", kind="llms_txt")
    _sync(tmp_path, source, manifest=manifest, report=report)

    assert report.added == 0
    assert report.updated == 0
    assert report.skipped == 1


def test_second_sync_refreshes_fetched_at(tmp_path):
    """fetched_at means "last confirmed from source", so a skip still refreshes it."""
    source = FakeSource(pages={"https://x/a.md": b"# A\n"})
    manifest = Manifest()
    _sync(tmp_path, source, manifest=manifest)
    first_stamp = manifest.get("https://x/a.md").fetched_at

    report = SourceReport(name="fake", kind="llms_txt")
    _sync(tmp_path, source, manifest=manifest, report=report)

    assert report.skipped == 1
    assert manifest.get("https://x/a.md").fetched_at >= first_stamp


def test_missing_raw_file_is_rewritten_without_counting_as_a_change(tmp_path):
    """Self-healing: a cleared data/raw must not silently break the corpus."""
    source = FakeSource(pages={"https://x/a.md": b"# A\n"})
    manifest = Manifest()
    _sync(tmp_path, source, manifest=manifest)
    (tmp_path / "raw" / "fake" / "x" / "a.md").unlink()

    report = SourceReport(name="fake", kind="llms_txt")
    documents = _sync(tmp_path, source, manifest=manifest, report=report)

    assert (tmp_path / "raw" / "fake" / "x" / "a.md").read_bytes() == b"# A\n"
    assert report.added == 0
    assert report.updated == 0
    assert report.skipped == 1
    assert documents[0].content == "# A\n"


def test_changed_page_is_reported_as_updated(tmp_path):
    source = FakeSource(pages={"https://x/a.md": b"# A\n"})
    manifest = Manifest()
    _sync(tmp_path, source, manifest=manifest)

    source.pages["https://x/a.md"] = b"# A\nnew body\n"
    report = SourceReport(name="fake", kind="llms_txt")
    _sync(tmp_path, source, manifest=manifest, report=report)

    assert report.updated == 1
    assert report.added == 0
    assert manifest.get("https://x/a.md").content_hash == hash_bytes(b"# A\nnew body\n")


def test_changed_page_overwrites_raw_file(tmp_path):
    source = FakeSource(pages={"https://x/a.md": b"# A\n"})
    manifest = Manifest()
    _sync(tmp_path, source, manifest=manifest)

    source.pages["https://x/a.md"] = b"# A\nnew\n"
    _sync(tmp_path, source, manifest=manifest)

    assert (tmp_path / "raw" / "fake" / "x" / "a.md").read_bytes() == b"# A\nnew\n"


def test_failed_fetch_is_recorded_and_does_not_abort_the_run(tmp_path):
    source = FakeSource(
        pages={"https://x/a.md": b"# A\n", "https://x/broken.md": b"# B\n"},
        fail_on={"https://x/broken.md"},
    )
    report = SourceReport(name="fake", kind="llms_txt")

    documents = _sync(tmp_path, source, report=report)

    assert len(documents) == 1
    assert report.added == 1
    assert len(report.failed) == 1
    assert report.failed[0]["locator"] == "https://x/broken.md"
    assert "RuntimeError" in report.failed[0]["error"]


def test_failed_page_is_not_written_to_manifest(tmp_path):
    source = FakeSource(pages={"https://x/broken.md": b"# B\n"}, fail_on={"https://x/broken.md"})
    manifest = Manifest()

    _sync(tmp_path, source, manifest=manifest)

    assert "https://x/broken.md" not in manifest


def test_version_breakdown_is_counted(tmp_path):
    source = FakeSource(
        pages={
            "https://x/docs/2026-07-28/a.md": b"# A\n",
            "https://x/docs/draft/b.md": b"# B\n",
            "https://x/seps/c.md": b"# C\n",
        }
    )
    report = SourceReport(name="fake", kind="llms_txt")

    _sync(tmp_path, source, report=report)

    assert report.versions == {"dated": 1, "draft": 1, "unknown": 1}


def test_locator_with_unknown_version_still_becomes_a_document(tmp_path):
    source = FakeSource(pages={"https://x/seps/2322-MRTR.md": b"# MRTR\n"})

    documents = _sync(tmp_path, source)

    assert documents[0].version == "unknown"


def test_doc_id_is_derived_from_source_and_locator(tmp_path):
    from docsentry.models import make_doc_id

    source = FakeSource(pages={"https://x/a.md": b"# A\n"})

    documents = _sync(tmp_path, source)

    assert documents[0].doc_id == make_doc_id("fake", "https://x/a.md")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_pipeline_insert.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docsentry.corpus.pipeline'`

- [ ] **Step 3: 实现 `pipeline.py` 的插入阶段**

```python
"""Corpus sync: discover -> fetch -> hash-compare -> write, then delete.

The ordering is the point (design spec 6.1.4):

    insert phase  ->  delete phase

New and changed content is written **before** anything is removed. A crash
inside the delete phase therefore leaves extra files, never a hole. The
reverse order -- delete first, then insert -- can delete successfully and then
fail to insert, producing an index gap that nothing notices. There is a test
for the ordering (Task 14) and a test that a failure during deletion still
leaves the new content on disk.

The manifest is saved last and atomically. A crash before that save means the
next run simply re-detects the same changes, so the whole operation is
idempotent in the direction that matters: it never under-reports what it has.

Fetching is concurrent (bounded thread pool) because a full pass is ~700 HTTP
requests. Failures are collected rather than raised -- one 404 must not cost us
the other 699 pages, and the report makes the loss visible.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from docsentry.corpus.converters.base import Converter
from docsentry.corpus.manifest import Manifest, ManifestEntry
from docsentry.corpus.paths import ensure_within, raw_relpath
from docsentry.corpus.report import SourceReport
from docsentry.corpus.sources.base import Fetched, Source
from docsentry.corpus.versioning import resolve_version
from docsentry.models import DocRef, Document, hash_bytes, make_doc_id


def sync_source(
    *,
    source: Source,
    converter: Converter,
    raw_root: Path,
    manifest: Manifest,
    report: SourceReport,
    workers: int = 8,
) -> list[Document]:
    """Bring the raw store in line with one source. Returns its documents."""
    refs = source.discover()
    report.discovered = len(refs)
    docs_root = raw_root / source.name

    # ---- insert phase: new and changed content lands on disk first --------
    documents: list[Document] = []
    for fetched in _fetch_all(source, refs, workers, report):
        documents.append(_absorb(source, converter, fetched, docs_root, manifest, report))

    return documents


def _absorb(
    source: Source,
    converter: Converter,
    fetched: Fetched,
    docs_root: Path,
    manifest: Manifest,
    report: SourceReport,
) -> Document:
    """Hash-compare one fetched page, write it if needed, and build its Document."""
    ref = fetched.ref
    digest = hash_bytes(fetched.data)
    known = manifest.get(ref.locator)
    unchanged = known is not None and known.content_hash == digest

    version = resolve_version(ref)
    raw_path = ensure_within(docs_root / raw_relpath(ref.locator), docs_root)

    if unchanged and raw_path.exists():
        report.skipped += 1
    else:
        # New, changed, or unchanged-but-missing (someone cleared data/raw).
        # All three need the bytes on disk; only the first two are real changes.
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(raw_path, fetched.data)
        if unchanged:
            report.skipped += 1  # content was already current; only the file was gone
        elif known is None:
            report.added += 1
        else:
            report.updated += 1

    # Refreshed on every run, including unchanged ones: fetched_at means "last
    # confirmed from source", which is what the health check warns on.
    manifest.set(ref.locator, ManifestEntry(digest, version, fetched.fetched_at))
    report.count_version(version)

    converted = converter.convert(raw_path)
    return Document(
        doc_id=make_doc_id(source.name, ref.locator),
        source=source.name,
        kind=source.kind,
        version=version,
        url=ref.locator,
        title=ref.title or converted.title,
        path=str(raw_path),
        content=converted.text,
        content_hash=digest,
        origin_format=converted.origin_format,
        fetched_at=fetched.fetched_at,
    )


def _atomic_write(path: Path, data: bytes) -> None:
    """Write via a temp file, then rename -- never leave a half-written page."""
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _fetch_all(source: Source, refs: list[DocRef], workers: int, report: SourceReport) -> list[Fetched]:
    """Fetch every ref concurrently, recording failures, ordered by locator.

    Failures are recorded on the **main** thread after the pool drains, so the
    report never depends on completion order and two runs produce identical
    reports. Ordering the result by locator gives the same determinism to the
    rest of the pipeline.
    """
    if workers <= 1:
        outcomes = [_try_fetch(source, ref) for ref in refs]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            outcomes = list(pool.map(lambda ref: _try_fetch(source, ref), refs))

    fetched: list[Fetched] = []
    for ref, result, error in sorted(outcomes, key=lambda outcome: outcome[0].locator):
        if error is not None:
            report.fail(ref.locator, error)
            continue
        fetched.append(result)
    return fetched


def _try_fetch(source: Source, ref: DocRef) -> tuple[DocRef, Fetched | None, str | None]:
    try:
        return ref, source.fetch(ref), None
    except Exception as exc:  # noqa: BLE001 -- any per-page failure is reportable, not fatal
        return ref, None, f"{type(exc).__name__}: {exc}"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_pipeline_insert.py -v`
Expected: `14 passed`

- [ ] **Step 5: 提交**

```bash
git add src/docsentry/corpus/pipeline.py tests/test_pipeline_insert.py
git commit -m "feat(m1): 同步管线插入阶段 — 并发抓取 + 失败收集不中断"
```

---

## Task 14: 先插后删 —— 核心保证

**Files:**
- Modify: `src/docsentry/corpus/pipeline.py`
- Test: `tests/test_pipeline_ordering.py`

> **这是 M1 最重要的一条**。设计文档 §6.1.4 写得很清楚：先删后插的缺陷是「删除完成、插入失败时，索引出现空洞且无人知晓」。下面两个测试是这条主张的**可执行证据**，不是形式化的断言。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_pipeline_ordering.py
from pathlib import Path

import pytest

from docsentry.corpus.converters.markdown import MarkdownConverter
from docsentry.corpus.manifest import Manifest
from docsentry.corpus.pipeline import sync_source
from docsentry.corpus.report import SourceReport
from docsentry.corpus.sources.base import Fetched
from docsentry.models import DocRef, SourceKind, utcnow


class FakeSource:
    def __init__(self, name="fake", pages=None):
        self.name = name
        self.kind = SourceKind.LLMS_TXT
        self.pages = dict(pages or {})

    def discover(self):
        return [
            DocRef(source=self.name, kind=self.kind, locator=locator, title=locator)
            for locator in sorted(self.pages)
        ]

    def fetch(self, ref):
        return Fetched(ref=ref, data=self.pages[ref.locator], fetched_at=utcnow())

    def refreshable(self):
        return True


class RecordingManifest(Manifest):
    """Records the order of mutating operations, so ordering can be asserted."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ops = []

    def set(self, locator, entry):
        self.ops.append(("set", locator))
        super().set(locator, entry)

    def remove(self, locator):
        self.ops.append(("remove", locator))
        super().remove(locator)


class ExplodingOnRemoveManifest(RecordingManifest):
    """A crash partway through the delete phase."""

    def remove(self, locator):
        super().remove(locator)
        raise RuntimeError("crash during delete phase")


def _sync(tmp_path, source, manifest, report=None):
    return sync_source(
        source=source,
        converter=MarkdownConverter(),
        raw_root=tmp_path / "raw",
        manifest=manifest,
        report=report or SourceReport(name=source.name, kind="llms_txt"),
        workers=1,
    )


def _seed(tmp_path, pages, *, name="fake"):
    """One full sync with the manifest persisted -- mirrors fetch_corpus.py."""
    path = tmp_path / f"manifest-{name}.json"
    source = FakeSource(name=name, pages=pages)
    manifest = Manifest.load(path)
    _sync(tmp_path, source, manifest)
    manifest.save(path)
    return source, path


def _rerun(tmp_path, source, manifest_path, report=None):
    """A subsequent run: load the manifest, sync, save. No crash simulation."""
    manifest = Manifest.load(manifest_path)
    documents = _sync(tmp_path, source, manifest, report)
    manifest.save(manifest_path)
    return documents


def _raw(tmp_path, *parts):
    return tmp_path / "raw" / Path(*parts)


# --- the delete phase -----------------------------------------------------

def test_removed_page_is_deleted(tmp_path):
    source, manifest_path = _seed(
        tmp_path, {"https://x/keep.md": b"# Keep\n", "https://x/gone.md": b"# Gone\n"}
    )
    assert _raw(tmp_path, "fake", "x", "gone.md").exists()

    source.pages = {"https://x/keep.md": b"# Keep\n"}
    report = SourceReport(name="fake", kind="llms_txt")
    _rerun(tmp_path, source, manifest_path, report=report)

    assert not _raw(tmp_path, "fake", "x", "gone.md").exists()
    assert "https://x/keep.md" in Manifest.load(manifest_path)
    assert "https://x/gone.md" not in Manifest.load(manifest_path)
    assert report.deleted == 1
    assert report.skipped == 1


def test_insert_happens_before_delete(tmp_path):
    """The whole claim: new content is on disk before anything is removed."""
    source, manifest_path = _seed(tmp_path, {"https://x/old.md": b"# Old\n"})
    recording = RecordingManifest(dict(Manifest.load(manifest_path).items()))

    # one page vanishes, one page appears -- both phases have work to do
    source.pages = {"https://x/new.md": b"# New\n"}
    _sync(tmp_path, source, recording)

    ops = [kind for kind, _ in recording.ops]
    assert "set" in ops and "remove" in ops
    assert ops.index("set") < ops.index("remove"), f"delete ran before insert: {ops}"


def test_crash_during_delete_still_leaves_new_content(tmp_path):
    """A failure in the delete phase must not cost us the newly fetched page."""
    source, manifest_path = _seed(tmp_path, {"https://x/old.md": b"# Old\n"})
    exploding = ExplodingOnRemoveManifest(dict(Manifest.load(manifest_path).items()))

    source.pages = {"https://x/new.md": b"# New\n"}
    with pytest.raises(RuntimeError, match="crash during delete phase"):
        _sync(tmp_path, source, exploding)

    # the new page reached disk and the in-memory manifest before the crash
    assert _raw(tmp_path, "fake", "x", "new.md").read_bytes() == b"# New\n"
    assert "https://x/new.md" in exploding


def test_crash_during_delete_is_recovered_by_the_next_run(tmp_path):
    """Whatever the crashed run left behind, the retry converges -- no holes."""
    source, manifest_path = _seed(tmp_path, {"https://x/old.md": b"# Old\n"})
    exploding = ExplodingOnRemoveManifest(dict(Manifest.load(manifest_path).items()))

    source.pages = {"https://x/new.md": b"# New\n"}
    with pytest.raises(RuntimeError):
        _sync(tmp_path, source, exploding)

    # The crash happened before the manifest was saved, so the retry reads the
    # pre-crash manifest -- exactly what a fresh process would see.
    report = SourceReport(name="fake", kind="llms_txt")
    _rerun(tmp_path, source, manifest_path, report=report)

    assert not _raw(tmp_path, "fake", "x", "old.md").exists()
    assert _raw(tmp_path, "fake", "x", "new.md").read_bytes() == b"# New\n"
    assert "https://x/old.md" not in Manifest.load(manifest_path)
    assert "https://x/new.md" in Manifest.load(manifest_path)
    assert report.added == 1
    assert report.deleted == 1


def test_delete_phase_removes_only_this_sources_files(tmp_path):
    """A source must never delete another source's raw files."""
    _seed(tmp_path, {"https://x/x.md": b"# Other\n"}, name="other")
    assert _raw(tmp_path, "other", "x", "x.md").exists()

    source, manifest_path = _seed(tmp_path, {"https://x/a.md": b"# A\n"})
    source.pages = {}
    _rerun(tmp_path, source, manifest_path)

    assert not _raw(tmp_path, "fake", "x", "a.md").exists()
    assert _raw(tmp_path, "other", "x", "x.md").exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_pipeline_ordering.py -v`
Expected: FAIL — `test_removed_page_is_deleted` fails because nothing deletes yet

- [ ] **Step 3: 给 `sync_source` 加上删除阶段**

在 `pipeline.py` 中，把 `sync_source` 的函数体补成下面这样（新增 `vanished` 计算与删除循环）：

```python
    refs = source.discover()
    report.discovered = len(refs)
    docs_root = raw_root / source.name

    discovered = {ref.locator for ref in refs}
    vanished = sorted(manifest.locators() - discovered)

    # ---- insert phase: new and changed content lands on disk first --------
    documents: list[Document] = []
    for fetched in _fetch_all(source, refs, workers, report):
        documents.append(_absorb(source, converter, fetched, docs_root, manifest, report))

    # ---- delete phase: only once the new content is safely in place -------
    for locator in vanished:
        _forget(source, locator, docs_root, manifest)
        report.deleted += 1

    return documents
```

并在 `sync_source` 之后新增 `_forget`：

```python
def _forget(source: Source, locator: str, docs_root: Path, manifest: Manifest) -> None:
    """Drop one vanished document: its raw file first, then its manifest entry.

    Scoped to ``docs_root`` -- this source's own subtree -- so a source can
    never delete another source's files, even if two sources list the same URL.

    The order inside this function does not matter for correctness, because the
    durable artifact (``manifest.json``) is only written at the very end of the
    run by the caller. A crash here is recovered by the next run, which sees the
    pre-crash manifest and simply retries the delete.
    """
    try:
        path = ensure_within(docs_root / raw_relpath(locator), docs_root)
        path.unlink(missing_ok=True)
    except (ValueError, OSError):
        pass  # an un-derivable or already-gone path is not worth failing the run
    manifest.remove(locator)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_pipeline_ordering.py tests/test_pipeline_insert.py -v`
Expected: `19 passed`

- [ ] **Step 5: 全量跑一遍**

Run: `uv run pytest`
Expected: 全绿（`148 passed, 6 deselected` —— 6 个联网验收测试被 `addopts` 排除）

- [ ] **Step 6: 提交**

```bash
git add src/docsentry/corpus/pipeline.py tests/test_pipeline_ordering.py
git commit -m "feat(m1): 先插后删 — 崩溃时留下冗余而非索引空洞"
```

---

## Task 15: `fetch_corpus.py` 入口

**Files:**
- Create: `scripts/fetch_corpus.py`
- Test: `tests/test_fetch_corpus_cli.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_fetch_corpus_cli.py
import json

from typer.testing import CliRunner

from scripts.fetch_corpus import app

runner = CliRunner()

CONFIG = """
sources:
  - name: one
    kind: llms_txt
    llms_txt: https://x/llms.txt
"""


def _write_config(tmp_path, body=CONFIG):
    path = tmp_path / "sources.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_run_writes_corpus_and_report(tmp_path, monkeypatch):
    import scripts.fetch_corpus as cli
    from docsentry.models import DocRef, SourceKind, hash_bytes, utcnow
    from docsentry.corpus.sources.base import Fetched

    class StubSource:
        name = "one"
        kind = SourceKind.LLMS_TXT

        def discover(self):
            return [DocRef(source="one", kind=self.kind, locator="https://x/docs/2026-07-28/a.md", title="A")]

        def fetch(self, ref):
            return Fetched(ref=ref, data=b"# A\nbody\n", fetched_at=utcnow())

        def refreshable(self):
            return True

    monkeypatch.setattr(cli, "build_source", lambda config, settings: StubSource())

    result = runner.invoke(
        app,
        [
            "--config", str(_write_config(tmp_path)),
            "--data-dir", str(tmp_path / "data"),
            "--reports-dir", str(tmp_path / "reports"),
        ],
    )

    assert result.exit_code == 0, result.output

    corpus = (tmp_path / "data" / "corpus.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(corpus) == 1
    assert json.loads(corpus[0])["title"] == "A"
    assert json.loads(corpus[0])["version"] == "2026-07-28"

    reports = list((tmp_path / "reports").glob("fetch-*.json"))
    assert len(reports) == 1


def test_report_is_also_copied_to_latest(tmp_path, monkeypatch):
    import scripts.fetch_corpus as cli
    from docsentry.corpus.sources.base import Fetched
    from docsentry.models import DocRef, SourceKind, utcnow

    class StubSource:
        name = "one"
        kind = SourceKind.LLMS_TXT

        def discover(self):
            return [DocRef(source="one", kind=self.kind, locator="https://x/a.md", title="A")]

        def fetch(self, ref):
            return Fetched(ref=ref, data=b"# A\n", fetched_at=utcnow())

        def refreshable(self):
            return True

    monkeypatch.setattr(cli, "build_source", lambda config, settings: StubSource())

    runner.invoke(
        app,
        [
            "--config", str(_write_config(tmp_path)),
            "--data-dir", str(tmp_path / "data"),
            "--reports-dir", str(tmp_path / "reports"),
        ],
    )

    assert (tmp_path / "reports" / "latest" / "fetch.json").exists()


def test_disabled_source_is_not_run(tmp_path, monkeypatch):
    import scripts.fetch_corpus as cli

    calls = []
    monkeypatch.setattr(cli, "build_source", lambda config, settings: calls.append(config.name))

    runner.invoke(
        app,
        [
            "--config", str(
                _write_config(
                    tmp_path,
                    "sources:\n"
                    "  - name: off\n    kind: llms_txt\n    llms_txt: https://x/llms.txt\n    enabled: false\n",
                )
            ),
            "--data-dir", str(tmp_path / "data"),
            "--reports-dir", str(tmp_path / "reports"),
        ],
    )

    assert calls == []


def test_unknown_source_name_exits_nonzero(tmp_path):
    result = runner.invoke(
        app,
        [
            "--config", str(_write_config(tmp_path)),
            "--source", "nope",
            "--data-dir", str(tmp_path / "data"),
            "--reports-dir", str(tmp_path / "reports"),
        ],
    )

    assert result.exit_code != 0
    assert "nope" in result.output


def test_missing_config_exits_nonzero(tmp_path):
    result = runner.invoke(app, ["--config", str(tmp_path / "nope.yaml"), "--data-dir", str(tmp_path / "data")])

    assert result.exit_code != 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_fetch_corpus_cli.py -v`
Expected: FAIL — `ImportError: cannot import name 'app' from 'scripts.fetch_corpus'`

- [ ] **Step 3: 实现 `scripts/fetch_corpus.py`**

```python
#!/usr/bin/env python
"""Fetch or incrementally update the corpus.

    uv run scripts/fetch_corpus.py --update               # 增量（默认）
    uv run scripts/fetch_corpus.py --update --source mcp  # 只跑一个源
    uv run scripts/fetch_corpus.py --full                 # 忽略 manifest 全量重抓

Idempotent: running it twice in a row is a no-op the second time. That is the
property the health check and the scheduled task both depend on.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import typer

from docsentry.config import Settings, SourceConfig, load_sources_config
from docsentry.corpus.converters.markdown import MarkdownConverter
from docsentry.corpus.manifest import Manifest
from docsentry.corpus.pipeline import sync_source
from docsentry.corpus.report import FetchReport, SourceReport
from docsentry.corpus.sources.llms_txt import LlmsTxtSource
from docsentry.corpus.sources.local_dir import LocalDirectorySource
from docsentry.models import utcnow

app = typer.Typer(add_completion=False, help="Fetch or incrementally update the corpus.")


def build_source(config: SourceConfig, settings: Settings):
    """Turn a validated config entry into a live Source."""
    if config.kind == "llms_txt":
        return LlmsTxtSource(
            name=config.name,
            llms_txt=config.llms_txt,
            url_include=config.url_include,
            keep_all_versions=config.keep_all_versions,
            timeout_s=settings.http_timeout_s,
            retries=settings.http_retries,
        )
    if config.kind == "local_dir":
        return LocalDirectorySource(
            name=config.name,
            path=config.path,
            default_version=config.default_version,
        )
    raise typer.BadParameter(f"unsupported source kind: {config.kind}")


def write_corpus(path: Path, documents) -> None:
    """Write corpus.jsonl atomically, sorted by doc_id for reproducibility."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for document in sorted(documents, key=lambda d: d.doc_id):
            handle.write(json.dumps(document.to_json(), ensure_ascii=False))
            handle.write("\n")
    tmp.replace(path)


@app.command()
def main(
    config: Path = typer.Option(None, "--config", help="Path to sources.yaml"),
    data_dir: Path = typer.Option(None, "--data-dir"),
    reports_dir: Path = typer.Option(None, "--reports-dir"),
    source: list[str] = typer.Option(None, "--source", help="Only run these sources (repeatable)"),
    update: bool = typer.Option(False, "--update", help="Incremental update (the default)"),
    full: bool = typer.Option(False, "--full", help="Ignore the manifest and re-fetch everything"),
) -> None:
    # `--update` is the spelling documented in CLAUDE.md; it names the default
    # behaviour, and `--full` is its only override. Both are accepted so the
    # documented command works verbatim.
    if update and full:
        typer.secho("error: --update and --full are mutually exclusive", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    settings = Settings()
    if config is not None:
        settings.sources_config = config
    if data_dir is not None:
        settings.data_dir = data_dir
    if reports_dir is not None:
        settings.reports_dir = reports_dir

    try:
        sources_config = load_sources_config(settings.sources_config)
    except FileNotFoundError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    selected = sources_config.enabled()
    if source:
        try:
            selected = [sources_config.by_name(name) for name in source]
        except KeyError as exc:
            typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)

    if full:
        manifest = Manifest()  # empty manifest == everything looks new
    else:
        manifest = Manifest.load(settings.manifest_path)

    started = utcnow()
    clock = time.perf_counter()
    reports: list[SourceReport] = []
    documents = []

    for source_config in selected:
        live = build_source(source_config, settings)
        typer.echo(f"fetching {source_config.name} ...")
        source_report = SourceReport(name=source_config.name, kind=source_config.kind)

        documents.extend(
            sync_source(
                source=live,
                converter=MarkdownConverter(),
                raw_root=settings.raw_dir,
                manifest=manifest,
                report=source_report,
                workers=settings.fetch_workers,
            )
        )
        reports.append(source_report)

    manifest.save(settings.manifest_path)
    write_corpus(settings.corpus_path, documents)

    report = FetchReport(started_at=started, duration_s=time.perf_counter() - clock, sources=reports)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    destination = settings.reports_dir / f"fetch-{stamp}.json"
    destination.write_text(json.dumps(report.to_json(), indent=2, ensure_ascii=False), encoding="utf-8")

    latest = settings.reports_dir / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(destination, latest / "fetch.json")

    typer.echo(report.summary())
    typer.echo(f"\ncorpus: {settings.corpus_path}  ({len(documents)} documents)")
    typer.echo(f"report: {destination}")

    if any(item.failed for item in reports):
        raise typer.Exit(code=1)  # non-zero so a scheduled task can notice


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_fetch_corpus_cli.py -v`
Expected: `5 passed`

- [ ] **Step 5: 提交**

```bash
git add scripts/fetch_corpus.py tests/test_fetch_corpus_cli.py
git commit -m "feat(m1): fetch_corpus CLI — 增量更新 + 报告落盘"
```

---

## Task 16: `health.py` 索引健康检查

**Files:**
- Create: `scripts/health.py`
- Test: `tests/test_health.py`

> 设计文档 §6.1.5 的第三条风险：**「超过 N 天未校验的文档告警」**。`fetched_at` 每次运行都刷新（Task 13 有测试），所以这个告警是真的在衡量「多久没跟源站核对过」。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_health.py
import json
from datetime import datetime, timedelta, timezone

from typer.testing import CliRunner

from scripts.health import app, stale_documents

runner = CliRunner()

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _manifest(tmp_path, entries):
    path = tmp_path / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def _entry(version="2026-07-28", days_old=0):
    return {
        "content_hash": "h",
        "version": version,
        "fetched_at": (NOW - timedelta(days=days_old)).isoformat(),
    }


def test_stale_documents_flags_old_entries():
    entries = {
        "https://x/fresh.md": _entry(days_old=1),
        "https://x/old.md": _entry(days_old=30),
    }

    stale = stale_documents(entries, max_age_days=7, now=NOW)

    assert [locator for locator, _, _ in stale] == ["https://x/old.md"]


def test_stale_documents_reports_days_since_check():
    entries = {"https://x/old.md": _entry(days_old=30)}

    stale = stale_documents(entries, max_age_days=7, now=NOW)

    assert stale[0][1] == 30


def test_stale_documents_is_empty_when_all_fresh():
    entries = {"https://x/a.md": _entry(days_old=0)}

    assert stale_documents(entries, max_age_days=7, now=NOW) == []


def test_cli_summarises_versions(tmp_path):
    path = _manifest(
        tmp_path,
        {
            "https://x/a.md": _entry("2026-07-28"),
            "https://x/b.md": _entry("draft"),
            "https://x/c.md": _entry("unknown"),
        },
    )

    result = runner.invoke(app, ["--manifest", str(path), "--now", NOW.isoformat()])

    assert result.exit_code == 0, result.output
    assert "1 dated" in result.output
    assert "1 draft" in result.output
    assert "1 unknown" in result.output


def test_cli_warns_about_stale_documents(tmp_path):
    path = _manifest(tmp_path, {"https://x/old.md": _entry(days_old=30)})

    result = runner.invoke(app, ["--manifest", str(path), "--max-age-days", "7", "--now", NOW.isoformat()])

    assert "stale" in result.output.lower()
    assert "https://x/old.md" in result.output


def test_cli_is_quiet_when_everything_is_fresh(tmp_path):
    path = _manifest(tmp_path, {"https://x/a.md": _entry(days_old=1)})

    result = runner.invoke(app, ["--manifest", str(path), "--now", NOW.isoformat()])

    assert "stale" not in result.output.lower()


def test_cli_handles_missing_manifest(tmp_path):
    result = runner.invoke(app, ["--manifest", str(tmp_path / "nope.json"), "--now", NOW.isoformat()])

    assert result.exit_code == 0
    assert "no manifest" in result.output.lower()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.health'`

- [ ] **Step 3: 实现 `scripts/health.py`**

```python
#!/usr/bin/env python
"""Index health check -- design spec 6.1.5.

Reports what the corpus believes it has, and warns about anything that has not
been verified against its source recently. The failure this guards against is
silent: a source that failed months ago leaves an index that looks complete.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import typer

from docsentry.config import Settings
from docsentry.corpus.versioning import version_bucket

app = typer.Typer(add_completion=False, help="Report corpus health and staleness.")


def load_manifest_entries(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def stale_documents(entries: dict, *, max_age_days: int, now: datetime):
    """``[(locator, days_since_check, version)]`` for entries older than the limit."""
    stale = []
    for locator, entry in entries.items():
        fetched_at = datetime.fromisoformat(entry["fetched_at"])
        age_days = (now - fetched_at).days
        if age_days > max_age_days:
            stale.append((locator, age_days, entry.get("version", "unknown")))
    return sorted(stale, key=lambda item: item[1], reverse=True)


@app.command()
def main(
    manifest: Path = typer.Option(None, "--manifest"),
    max_age_days: int = typer.Option(7, "--max-age-days", help="Warn beyond this many days unverified"),
    now: str = typer.Option(None, "--now", help="Override the current time (for tests)"),
) -> None:
    settings = Settings()
    path = manifest or settings.manifest_path
    entries = load_manifest_entries(path)

    if not entries:
        typer.echo(f"no manifest at {path} -- run fetch_corpus.py first")
        raise typer.Exit(code=0)

    buckets = {"dated": 0, "draft": 0, "unknown": 0}
    for entry in entries.values():
        buckets[version_bucket(entry.get("version", "unknown"))] += 1

    typer.echo(f"manifest: {path}")
    typer.echo(f"documents: {len(entries)}")
    typer.echo(f"versions: {buckets['dated']} dated, {buckets['draft']} draft, {buckets['unknown']} unknown")

    current = datetime.fromisoformat(now) if now else datetime.now(timezone.utc)
    stale = stale_documents(entries, max_age_days=max_age_days, now=current)
    if stale:
        typer.secho(f"\nstale: {len(stale)} documents unverified for over {max_age_days} days", fg=typer.colors.YELLOW)
        for locator, age_days, version in stale[:20]:
            typer.echo(f"  {age_days:>4}d  [{version}]  {locator}")
        if len(stale) > 20:
            typer.echo(f"  ... and {len(stale) - 20} more")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_health.py -v`
Expected: `7 passed`

- [ ] **Step 5: 提交**

```bash
git add scripts/health.py tests/test_health.py
git commit -m "feat(m1): health 脚本 — 版本分布 + 陈旧告警"
```

---

## Task 17: M1 验收 —— 真实语料跑通

**Files:**
- Create: `tests/test_m1_acceptance.py`

> 这是**唯一的联网测试**，默认被 `addopts` 排除。它是 M1 验收标准的可执行形式。

- [ ] **Step 1: 写验收测试**

```python
# tests/test_m1_acceptance.py
"""M1 acceptance against the real corpora.

Excluded by default (see pyproject `addopts`). Run with:

    uv run pytest -m network -v

Slow by design: it downloads both corpora end to end.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docsentry.config import Settings, load_sources_config
from docsentry.corpus.converters.markdown import MarkdownConverter
from docsentry.corpus.manifest import Manifest
from docsentry.corpus.pipeline import sync_source
from docsentry.corpus.report import SourceReport
from docsentry.corpus.sources.llms_txt import LlmsTxtSource

pytestmark = pytest.mark.network

CONFIG = Path("configs/sources.yaml")


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings()


@pytest.fixture(scope="module")
def sources():
    return {s.name: s for s in load_sources_config(CONFIG).sources}


def _sync(name, config, settings, tmp_path, manifest):
    live = LlmsTxtSource(
        name=config.name,
        llms_txt=config.llms_txt,
        url_include=config.url_include,
        timeout_s=settings.http_timeout_s,
        retries=settings.http_retries,
    )
    report = SourceReport(name=config.name, kind=config.kind)
    documents = sync_source(
        source=live,
        converter=MarkdownConverter(),
        raw_root=tmp_path / "raw",
        manifest=manifest,
        report=report,
        workers=settings.fetch_workers,
    )
    return documents, report


def test_two_sources_yield_at_least_400_documents(tmp_path, settings, sources):
    manifest = Manifest()
    total = 0
    for config in sources.values():
        if not config.enabled:
            continue
        documents, report = _sync(config.name, config, settings, tmp_path, manifest)
        assert not report.failed, f"{config.name} had fetch failures: {report.failed[:5]}"
        total += len(documents)

    assert total >= 400, f"only {total} documents"


def test_mcp_version_labelling_is_at_least_90_percent(tmp_path, settings, sources):
    """The M1 criterion, measured over the pages actually indexed.

    `/docs/` + `/specification/` are 252 pages: 198 dated + 54 draft. The 95
    versionless pages (`/seps/`, `/community/`, `/registry/`, `/extensions/`)
    are deliberately not part of this source (see configs/sources.yaml), so
    they cannot dilute the figure. `draft` is a real version channel and counts
    as labelled.
    """
    _, report = _sync("mcp", sources["mcp"], settings, tmp_path, Manifest())

    assert report.versions["dated"] + report.versions["draft"] >= 0.9 * report.discovered
    assert report.discovered >= 240


def test_mcp_covers_every_published_spec_version(tmp_path, settings, sources):
    """Version-aware retrieval is only meaningful if the versions are all there."""
    documents, _ = _sync("mcp", sources["mcp"], settings, tmp_path, Manifest())

    versions = {document.version for document in documents}

    assert {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"} <= versions
    assert "draft" in versions


def test_second_run_skips_everything(tmp_path, settings, sources):
    """Idempotence -- the property the scheduled task depends on."""
    manifest = Manifest()
    _sync("mcp", sources["mcp"], settings, tmp_path, manifest)

    _, second = _sync("mcp", sources["mcp"], settings, tmp_path, manifest)

    assert second.added == 0
    assert second.updated == 0
    assert second.deleted == 0
    assert second.skipped == second.discovered


def test_langchain_recursion_expands_the_python_index(tmp_path, settings, sources):
    documents, report = _sync("langgraph", sources["langgraph"], settings, tmp_path, Manifest())

    assert len(documents) >= 350
    assert not report.failed


def test_documents_are_real_markdown_with_titles(tmp_path, settings, sources):
    documents, _ = _sync("mcp", sources["mcp"], settings, tmp_path, Manifest())
    sample = [d for d in documents if "/specification/2026-07-28/" in d.url]

    assert sample, "no 2026-07-28 specification pages retrieved"

    for document in sample:
        assert document.title, f"no title extracted from {document.url}"
        assert len(document.content) > 500, f"suspiciously short: {document.url}"
        # the per-page navigation banner must be gone from every page
        assert "Documentation Index" not in document.content, document.url
```

- [ ] **Step 2: 跑验收测试**

Run: `uv run pytest -m network -v`
Expected: `6 passed`（首次约 1–3 分钟，取决于网络）

- [ ] **Step 3: 真实抓取一回，留下证据**

Run: `uv run scripts/fetch_corpus.py --update`
Expected 输出形态：

```
fetching mcp ...
fetching langgraph ...

fetch report  (NN.Ns)

  mcp        discovered=252   added=252   updated=0     skipped=0     deleted=0
             versions: 198 dated, 54 draft, 0 unknown (100% labelled)
  langgraph  discovered=369   added=369   updated=0     skipped=0     deleted=0
             versions: 0 dated, 0 draft, 369 unknown (0% labelled)

  total      discovered=621 added=621 updated=0 skipped=0 deleted=0

corpus: data\corpus.jsonl  (621 documents)
report: reports\fetch-<ts>.json
```

- [ ] **Step 4: 再跑一次，确认幂等**

Run: `uv run scripts/fetch_corpus.py --update`
Expected: `added=0 updated=0 deleted=0`，两个源 `skipped` 等于各自 `discovered`

- [ ] **Step 5: 跑健康检查**

Run: `uv run scripts/health.py`
Expected: `documents: 621`，`versions: 198 dated, 54 draft, 369 unknown`，无 stale 告警

- [ ] **Step 6: 全量测试 + 提交**

Run: `uv run pytest && uv run pytest -m network -q`
Expected: 全绿

```bash
git add tests/test_m1_acceptance.py
git commit -m "test(m1): 真实语料验收 — ≥400 篇 + 版本标注率 + 幂等性"
```

---

## Task 18: 更新设计文档与 README 进度

**Files:**
- Modify: `docs/superpowers/specs/2026-09-18-docsentry-design.md` (§6.1.1 配置示例、§9 里程碑 M1 行)
- Modify: `README.md` (Progress 清单)

- [ ] **Step 1: 改设计文档 §6.1.1 的 MCP 配置示例**

把 `mcp` 源的 `url_include: "/docs/"` 改为：

```yaml
  - name: mcp
    kind: llms_txt
    llms_txt: https://modelcontextprotocol.io/llms.txt
    url_include:
      - /docs/
      - /specification/
    keep_all_versions: true
```

并在配置块下方加一段说明：

```markdown
> **`url_include` 必须同时包含 `/specification/`**（2026-09-20 实测修正）：MCP 站点把
> 教程放在 `/docs/`，把协议规范正文放在 `/specification/`，两者各自带日期版本段。
> 只写 `/docs/` 会拿到 110 篇而漏掉全部 111 篇规范正文——而 2026-07-28 协议变更的
> 证据链正在那里。
>
> `/seps/` 与 `/community/` 故意不收录：这两类页面本身不带版本段，收进来只会让版本
> 标注率虚降，且对"查 API 用法"帮助有限。
```

- [ ] **Step 2: 改设计文档 §9 里程碑表的 M1 行**

把 M1 行的验收标准替换为：

```markdown
| M1 语料层 | D3 | `Source` 抽象（llms_txt + local_dir）可用；两源 ≥400 篇 `.md`；增量更新（先插后删，含崩溃测试）可运行；抓取报告输出含失败清单与 `dated`/`draft`/`unknown` 三分项；**被纳入索引的 MCP 页面版本标注率 ≥90%**（实测 252 篇 → 100%：198 日期 + 54 draft） |
```

- [ ] **Step 3: README 增加 Progress 小节**

在 README 的 `## Approach` 之前插入：

```markdown
## Progress

- [x] **M1 语料层** — `Source` 抽象（`llms_txt` + `local_dir`）、`content_hash` 增量更新（先插后删）、抓取报告
- [ ] M2 切片策略 — 三策略 + 公平性检查
- [ ] M3 检索可用 — 索引构建 + CLI 检索
- [ ] M4 生成完成 — 带引用/版本/索引时间的答案
- [ ] M5 agent 编排 — LangGraph 状态图
- [ ] M6 评测跑分 — 三策略 × 两模式 + 时效性三组
- [ ] M7 交付 — README + demo

语料现状：MCP 252 篇（198 日期版 + 54 draft，**版本标注率 100%**）、
LangChain Python 369 篇，合计 621 篇。
```

- [ ] **Step 4: 跑全量测试并提交**

Run: `uv run pytest`

```bash
git add README.md docs/superpowers/specs/2026-09-18-docsentry-design.md
git commit -m "docs(m1): 修正 MCP 语料范围与版本验收标准 + README 进度"
```

---

## 附：本计划对设计文档的三处偏离，及理由

| # | 设计文档原文 | 计划做法 | 理由 |
|---|---|---|---|
| 1 | `Converter.convert(path) -> Document` | `convert(path) -> ConvertedDoc` | 转换器不知道 `source`/`version`/`fetched_at`；`Document` 由 pipeline 组装，职责更干净 |
| 2 | `MarkdownConverter`「直接读取」 | 额外剥掉页首 `> ## Documentation Index` 样板块 | MCP 与 LangChain **每页**都有，跨 700 篇字节相同。它是指南导航文字不是文档内容，留着会进每个文档的首个 chunk，对 embedding 是纯噪声、对 BM25 是高频干扰。只处理**页首**且必须含 "Documentation Index" 字样，正文里的引用块不受影响 |
| 3 | MCP `url_include: "/docs/"` | `["/docs/", "/specification/"]` | 已获用户确认；见文首「开工前已实测的事实」 |

另有两条**实现细节**未在设计中规定，此处定下：`Source.fetch()` 返回**原始字节**（保证 hash 算在服务器发来的字节上，且为将来非 UTF-8 格式留路）；`ManifestEntry.fetched_at` 语义是「最后一次跟源站核对通过的时间」，每次运行都刷新（含未变更的页面），Health 检查的「N 天未校验」告警才成立。

## 附：M1 不做的（避免范围蔓延）

- `snapshot` 源类型 —— 协议里有、设计里反对，不实现
- PDF / Office / 图片转换器 —— 选做项，按 §8.6 砍功能顺序排在最先
- `keep_all_versions` 的 CLI 开关 —— 配置项已实现并测试，但两个源都是 `true`，不加多余的 flag
- 常驻文件监控（watchdog）—— 设计明确不做，每次重扫目录即可
- `cli.py` / 索引 / 切片 —— M2 及以后
