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
    """Raw bytes for one reference, plus when they were retrieved.

    ``content_type`` is the server's own claim about those bytes -- the HTTP
    ``Content-Type`` header, or ``None`` for a source with no server to ask
    (``local_dir`` reads files). It is carried because a source can be told to
    expect Markdown and be handed an HTML page with a 200; the pipeline decides
    what it will ingest, and it needs the claim to decide with.
    """

    ref: DocRef
    data: bytes
    fetched_at: datetime
    content_type: str | None = None


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

> **⚠️ 实现时发现第二处顺序缺陷，Step 3 的代码不能照抄（2026-09-21，已修）**：
> `return refs if self.keep_all_versions else prune_to_latest(refs)` 在
> `keep_all_versions: false` 分支上**返回的不是有序结果**——`prune_to_latest` 的
> 输出是「无版本页在前，每组各一条在后」，只在本任务那条测试的样本里碰巧有序。实测反例：
>
> | 表达式 | 返回顺序 |
> |---|---|
> | `prune_to_latest([docs/2025-11-25/a.md, docs/2026-07-28/a.md, seps/1-a.md])` | `[seps/1-a.md, docs/2026-07-28/a.md]` |
> | 按 locator 排序后 | `[docs/2026-07-28/a.md, seps/1-a.md]` |
>
> 语料越大越明显：MCP 的 `/seps/`、`/community/`、`/registry/`、`/extensions/`
> **全是无版本页**，会整体排到 `/docs/`、`/specification/` 之前——而字典序是
> `docs < extensions < registry < seps < specification`。当前两份源都写着
> `keep_all_versions: true`，线上跑不到这条分支；但契约写的是 sorted，就得两条路径都排。
> **修法**：取 `found.values()` → 需要剪枝时剪枝 → **最后统一 sort**（改动 3 行）。
> 新增回归测试 `test_discover_is_sorted_when_pruning`。
>
> **另补一条 `test_discover_handles_a_mixed_index`**：上面第一条 ⚠️ 说 LangChain
> 顶层两种形态并存，但 Step 1 的层级测试**全是纯子索引文件**，没有一条覆盖「一个文件里
> 两种链接混排」。实测复核顶层：177 条唯一链接 = **58 子索引 + 119 直连 `.md`**，
> 与警告里的数字一致；MCP 侧 352 条 → 347 唯一，`/docs/` + `/specification/` = 110 + 142 = **252**。

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
Expected: `22 passed`（原计划记 19；补 3 条顺序 / 混排测试后为 22）

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
        return Fetched(
            ref=ref,
            data=response.content,
            fetched_at=utcnow(),
            content_type=response.headers.get("content-type"),
        )
```

`utcnow` 在 Task 7 已随 import 引入，无需改动 import 区。

> **2026-09-22 追补：`content_type` 是抓取层新增的一条契约**（触发点见 Task 17 的 ⚠️ C）。
> 站点可以对一条 `.md` URL 回 200 却给 HTML；把服务器的原话带上去，管线才裁得动。
> 配套测试两条（`tests/test_llms_txt_fetch.py`）：有 header 时如实带上、没有时是 `None`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_llms_txt_fetch.py tests/test_llms_txt_discover.py -v`
Expected: `28 passed`（原计划记 25 = 6 + 19；Task 7 补了 3 条，实为 6 + 22）

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

> **⚠️ 本任务与本任务之后的一个决定组合不起来：绝对路径 locator 在 Windows 上打不通管线（2026-09-21 实测，已修）**
> 起因是 Task 15 的真源冒烟：`local_dir` 源跑 CLI 时**整次运行中止**，
> `ValueError: refusing to touch C:\...\docs\a.md: outside C:\...\data\raw\internal`。
> 单元层面复现（不用起 CLI）：
>
> | 步骤 | 值 |
> |---|---|
> | `LocalDirectorySource.discover()[0].locator` | `C:\Users\…\docs\a.md` |
> | `paths.raw_relpath(locator)` | `'\Users\…\docs\a.md'` |
> | `ensure_within(docs_root / 上面那个, docs_root)` | **ValueError（拒绝）** |
>
> 根因是一条**缝**：Step 3 决定「locator 是绝对路径」（`test_locator_is_an_absolute_path` 钉着），
> 而 Task 5 的 `raw_relpath` 是按 URL 设计的（`urlparse` 取 scheme/netloc、按 `/` 分段）——
> `C:` 被当成 URL scheme 吃掉，剩下整串成为一个含反斜杠的段，构造出的 `Path` 带盘符锚点。
> **POSIX 上恰好能跑**（`/home/u/docs/a.md` 会被切成正常段），所以这是一个 **Windows-only** 缺陷，
> 而本项目跑在 Windows 上。设计文档 §205 写的是 `locator: str # URL 或本地路径`——允许本地路径，
> 但没说它长什么样，两个实现各挑了一种形状，**没有任何测试跨过这条缝**
> （Task 9 测 discover/fetch，Task 13 用 URL locator 测管线；Task 17 的验收只跑两个联网源）。
>
> **修法**：locator 改成**相对源目录的 POSIX 路径**（`a.md`、`sub/b.md`），`fetch` 改成
> `(self.path / ref.locator).read_bytes()`。理由不只是"能跑通"：
> `doc_id = sha256(source + locator)[:16]`，**绝对路径会把机器布局烧进每一个 id**——搬目录或换机器
> 读同一份语料，全部本地文档换 id、索引整体重建。相对 locator 让私有语料与公开语料一样可复现
> （这是 C 与 Task 9 之外、项目命题本身的要求）。绝对位置仍然可查：源配置里有，`Document.path` 也有。
>
> **测试 13 → 15**：`test_locator_is_an_absolute_path` 换成
> `test_locator_is_relative_to_the_source_directory`（断言 POSIX 分隔符、无盘符），另补两条跨模块的
> **缝测试**：`test_local_document_survives_the_pipeline`（真源走完 `sync_source` → raw 文件落盘 →
> `Document.url == "a.md"`）与 `test_doc_id_does_not_depend_on_where_the_directory_lives`
> （同一份内容放两个不同绝对目录，`doc_id` 相同）。实测：这三条打回未修补的实现全红，其余 12 条全过。
>
> 附带印证：写缝测试时我自己又踩了一次上面那条 Windows 陷阱（`write_text` 造样本 + 断言 `bytes`），
> 证明这类夹具缺陷会反复出现——**断言 bytes 就用 `write_bytes`**。

> **⚠️ Step 1 的两条 fetch 测试在 Windows 上不可满足，Step 3 的实现本身无误（2026-09-21 实测，已修）**：
> `test_fetch_reads_current_bytes` 与 `test_fetch_sees_an_edit` 用
> `target.write_text("# A\n", encoding="utf-8")` 造样本，却断言
> `fetched.data == b"# A\n"`。Windows 下 `write_text` 以文本模式打开、
> `newline=None`，会把 `\n` 翻译成 `\r\n` 落盘——磁盘上实际是 `b"# A\r\n"`，
> **这两条断言在任何正确实现下都不成立**（本平台实测 FAILED，而 `read_bytes`
> 的行为是对的：content_hash 必须看到磁盘上真实的那串字节）。
> **修法**：fixture 改用 `write_bytes`，写成它断言的那串字节，跨平台都成立。
>
> 另补一条 `test_fetch_returns_bytes_verbatim`，钉住 `read_bytes` 的原样返回。
> 它同时记录一处**合法差异**：本地文件在 Windows 上带 `\r\n`，这个 `\r\n` 会进
> `content_hash`；而转换器用 `read_text` 读回（universal newlines）时 CRLF 已归一成
> LF，所以换行符不会渗进 chunk 文本。实测：`write_bytes(b'# A\r\n')` 之后
> `read_text` 得到 `'# A\n'`。两条路径各司其职，不是缺陷。

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
Expected: `15 passed`（原计划记 12；补 1 条 verbatim 回归后为 13，再换 1 条 / 补 2 条缝测试后为 15）

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

> **⚠️ Step 3 的 `load` 没有兑现自己 docstring 里的契约；而且 docstring 的成本核算本身不完整（2026-09-21 实测 + 复核，已修）**
>
> **第一层：实现只挡了非法 JSON。** docstring 写「a missing or **unreadable** file means 'start over'」，
> 实现却只 catch `(FileNotFoundError, json.JSONDecodeError, OSError)` —— 这是**枚举**而不是**推理**
> 异常层级（`FileNotFoundError` ⊂ `OSError`，本身就是冗余项），于是两类「读不出来」逃了出去。
> 实测（离线脚本，8 个样本）：
>
> | `manifest.json` 内容 | 原 `load` 的行为 |
> |---|---|
> | `{not json`（**Step 1 唯一测的场景**） | 返回空 ✓ |
> | 非法 UTF-8 字节 | `UnicodeDecodeError` —— ⊂ `ValueError`，**不是** `OSError` |
> | `[]` / `null` / `"hello"` | `AttributeError: 'list' object has no attribute 'items'` |
> | `{"…": null}` | `TypeError: 'NoneType' object is not subscriptable` |
> | `{"…": "nope"}` | `TypeError: string indices must be integers` |
> | `{"…": {"content_hash": "h"}}` | `KeyError: 'version'` |
>
> **第二层：真正该修的不是「崩」，是「静默重来」的成本被算错了。** 「崩」只发生在畸形文件上，
> 且 fail-fast（`load` 在整次运行**开头**调用，见 Task 13 的 `_rerun`），恢复靠删文件——这一半确实轻。
> 但计划里那条**已通过的** `test_load_corrupt_file_returns_empty`（非法 JSON → 返回空，不崩）走的
> 恰恰是更坏的一条路，而 docstring 的成本核算漏了一半：
>
> > "Rebuilding from an unreadable manifest costs one full re-fetch"
>
> 实际不止。manifest 不只是「我们有什么」的缓存，它同时是**删除检测的基线**（Task 14）：
>
> ```python
> vanished = sorted(manifest.locators() - discovered)   # 空 manifest → vanished = ∅
> ```
>
> 于是：① 该删的页面**一个都不删**——`_forget` 是全模块唯一 unlink raw 文件的地方；
> ② `report.deleted=0`，而这一格分不清「没有页面消失」和「基线丢了」，它正是 §6.1.5 为「静默缺口」建的；
> ③ **永久的**：本次结束 `save()` 按内存状态重写 manifest，而内存里只剩本次 discover 到的 locator，
> 消失的 locator 从此既不在 manifest 也不在源——下次运行同样检测不到，**追不回来**。
>
> （`except OSError` 那一支——`PermissionError`，Windows 上被杀毒/索引器/云同步客户端锁住文件——
> 给的是进同一状态的**第二条**路，但窗口窄得多：要「读失败、写成功」才永久丢；锁通常两边都锁，
> 于是崩在 `save`，旧 manifest 完好无损。记录在案，不作主要论据。）
>
> **修法：把「没有记录」与「读不出来」分开。**
> - `FileNotFoundError` → 返回空。首次运行本来就没有基线，无损失——这才是 docstring 说的 start over。
> - 其余（`OSError` / `UnicodeDecodeError` / `JSONDecodeError` / 顶层不是对象 / entry 不是对象或字段缺失）
>   → 抛 `ManifestUnreadable`，带路径与原因。人要删文件才能重建，**但删之前他知道了「基线丢了」**。
> - `ManifestUnreadable` **不继承 `OSError`**——有一条测试钉死这点。否则将来某个 `except OSError`
>   会把它静默吞掉，等于把这次修的东西原样再挖一遍。
> - 形状不对时**整份作废**（抛错），不做部分加载：与 docstring 同一理由，宁可全量重检，
>   也不要「一半信旧的、一半当新的」。
>
> 连带 Task 15：`fetch_corpus.py` 要 catch `ManifestUnreadable` 打一句可操作的话（路径 + 原因 + 怎么重建），
> 否则用户看到的是一条 traceback。测试 11 → 15（改 1 条、补 4 条）。
> **根治不在这里**——见 Task 14 开头的 ⚠️：让删除判据不再依赖 manifest 的记忆，manifest 丢失才真正只值一次重抓。
>
> **2026-09-22 追补**：`ManifestEntry.from_json` 现在**拒收无时区时间戳**（抛 `ValueError` → 被 `load`
> 已有的 `except (KeyError, TypeError, ValueError)` 转成 `ManifestUnreadable`，补 1 条测试）。
> 触发点在 Task 16：naive 值 parse 得出来，然后一路活到**第一个做日期算术的读方**才炸成 traceback。
> 详见 Task 16 开头的 ⚠️ ②。

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
Expected: `15 passed`（原计划记 11；改 1 条 + 补 4 条后为 15）

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

> **⚠️ Step 3 的 `summary()` 没兑现自己 docstring 那句 "failures first"，Step 1 的测试碰不到（2026-09-21 实测，已修）**：
> docstring 承诺 "Human-readable block for the console, **failures first**"，但实现把失败行放在**每个源自己那一块里**——计数行与版本行之后。实测（2 个源 / mcp 内 1 条 404）：`failed` 首次出现在第 4 行（共 10 行），即 60% 处；源越多埋得越深，而末行 `total` 永不含失败数。计划的
> `test_summary_mentions_failures_when_present` 只断言 `"1 failed" in text`（子串存在），**没有一条测试管顺序**——又是一处「测试通过 ≠ 契约成立」。
>
> 为什么值得修（不是排版洁癖）：§6.1.5 说头号风险是「你以为更新了，其实某个源抓失败了，索引缺内容是静默的」，控制台是这个风险的**人眼通道**，「失败优先」是它的设计意图而不是修辞。
>
> **修法**：失败行从各源块里提到 header 之后、第一个 `discovered=` 之前，汇成一块；每行**前置源名**（移出各源块后，源名不能再靠位置隐含）；`FetchReport` 新增 `failures` 属性（`(source, locator, error)` 展平，源顺序、源内按 locator 排序）。**0 失败时输出逐字节不变**（实测）——计划那条 quiet 测试与 Task 17 的验收控制台断言都不受影响。测试 11 → 13（补 `test_summary_puts_failures_before_the_counts`、`test_summary_groups_failures_from_every_source_with_their_source_name`）。
>
> 顺带查掉、**确认不是缺陷**：`failed` / `versions` 的可变默认值不跨实例共享；源名长于 10 字符时列会错位（`{name:<10}`，纯观感，不修）。
>
> **明确不动的决定**：`totals` 不加失败计数——JSON 的 `sources[i]["failed"]` 已带全量信息，而把 `failed=0` 追加到末行会与 `test_summary_is_quiet_when_nothing_failed`（quiet 时整份输出不含 "failed"）自相矛盾。

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
Expected: `13 passed`（原计划记 11；补 2 条顺序测试后为 13）

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

> **2026-09-22 追补：`_try_fetch` 多了一道格式闸门，`FakeSource` 跟着多一个 `content_types` 参数。**
> 触发点是 Task 17 第一次联网实测（见那里 ⚠️ C）：站点会对 `.md` URL 回 `200 text/html`。
> 闸门本身的完整来龙去脉写在 Task 17 的 ⚠️ 里；这里只记「本任务的代码块已经变了」这件事，
> 以及配套的 3 条测试（`test_page_that_is_not_markdown_is_recorded_as_failed`、
> `test_page_that_is_not_markdown_is_not_written_or_remembered`、
> `test_only_markdown_content_types_are_accepted`，其中第三条同时钉住「`None` 放行、`text/plain` 不放行」）。
> **测试计数 17 → 20**。

> **⚠️ Step 1 的夹具有两处缺陷，Step 3 的实现本身无误；另有 3 条契约没被任何测试钉住（2026-09-21 实测，已修）**
> 实测：计划 14 条在 scratch 里**只过 8 条**。逐条定位后，两条根因都在夹具，修完夹具 14/14 全绿。
>
> **A. 真值陷阱（5 条挂在这里）**：夹具 `_sync` 写的是
>
> ```python
> manifest=manifest or Manifest(),   report=report or SourceReport(...)
> ```
>
> `Manifest` 实现了 `__len__`，于是**空 manifest 是 falsy**，调用者传进来的空 manifest 被替换成一个临时对象，
> `sync_source` 的写入全落在马上被丢弃的那个上。所有「第一次同步之后再检查 manifest」的测试因此必挂
> （`test_manifest_records_hash_and_version`、`test_second_sync_skips_unchanged_pages`、
> `test_second_sync_refreshes_fetched_at`、`test_missing_raw_file_is_rewritten...`、
> `test_changed_page_is_reported_as_updated`）。
>
> **反证比正面证据更值得记**：`test_changed_page_overwrites_raw_file` **通过了，但通过的原因是错的**——
> manifest 又被丢掉，第二次同步走的是 added 分支而不是 updated，文件照样被覆写。`SourceReport` 没有
> `__len__`，所以 `report or ...` 那半边无害，只有 manifest 这半边坏。
> **修法**：`manifest if manifest is not None else Manifest()`（report 同改，保持一致）。
> **同一行代码在 Task 14 的测试文件里也抄了一份**——但**实读后确认它没有这个缺陷**（2026-09-21 更正：
> Task 14 的 `_sync(tmp_path, source, manifest, report=None)` 把 manifest 作**必填参数**传下去，没有 `or`
> 回落，不存在真值陷阱。上一版这条笔记写错了，在此更正）；仍要留意 Task 15 的 `--full` 分支会构造
> `Manifest()`（空）——凡是 `Manifest` 参与 `or` / `if not` 的地方都按这个坑审一遍。
>
> **B. 夹具伪造了一个真源不会有的标题（1 条）**：`FakeSource` 给 `title=Path(locator).stem`（即 `"a"`），
> 而断言要 `"A"`（H1）。实现是 `title = ref.title or converted.title`，`"a"` 非空所以压过 H1。查证契约：
>
> | 证据 | 内容 |
> |---|---|
> | `sources/local_dir.py` | `title=""`，注释 "derived from the document's first heading" |
> | 设计文档 §6.2 | 「`llms_txt` 源已自带标题，这一步是让裸 `local_dir` 也能用」 |
>
> 即**源标题优先、空标题回落 H1**——实现是对的，夹具的 stub 标题把回落分支堵死了。
> **修法**：夹具改成带 `title` 参数、默认 `""`（对齐 `LocalDirectorySource`）。
>
> **C. 夹具的 `discover()` 自己先排了序**（`sorted(self.pages)`），于是 `_fetch_all` 里那句
> 「Ordering the result by locator」永远测不到。改成按插入顺序返回——源本来就允许返回索引顺序，
> `sync_source` 承诺的是**它自己**的输出有序。
>
> **补 3 条测试**（都是实现 docstring 已经声明、而计划一条都没钉的契约）：
> - `test_source_title_wins_over_the_heading`：钉住 B 那个方向（llms_txt 标题优先）。缺了它，
>   将来把实现改成 `converted.title or ref.title` 不会有任何测试报警。
> - `test_documents_come_back_sorted_by_locator`：钉住 `_fetch_all` docstring 的排序承诺
>   （Task 7 已有同样先例：契约写了 sorted，就得有测试）。
> - `test_raw_write_is_atomic_and_leaves_no_part_file`：`_atomic_write` 承诺 "never leave a
>   half-written page"，而 manifest 有对应的 `*.tmp` 测试、raw 写入器没有。
>
> 测试 14 → 17。
>
> **顺带记一条待办（不在本任务）**：`Converter.supported` 至今**没有调用方按扩展名派发**——
> M1 只有 `MarkdownConverter` 一个实现、源也只产 `.md`，所以现在无害；等选做的 `PdfConverter`
> 落地时，pipeline 需要一个「按扩展名选转换器」的分派点，别到时候才想起来。

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
        fetched = source.fetch(ref)
    except Exception as exc:  # noqa: BLE001 -- any per-page failure is reportable, not fatal
        return ref, None, f"{type(exc).__name__}: {exc}"
    unexpected = _unexpected_format(fetched)
    if unexpected is not None:
        return ref, None, unexpected
    return ref, fetched, None


# Every ``.md`` URL in both corpora answers with one of these. docs.langchain.com
# serves ``200 text/html`` for sixteen of the URLs its index still lists
# (reference dumps, changelogs, the academy landing page) -- pages it does not
# publish as Markdown at all. ``text/plain`` is deliberately absent: it is not a
# markdown claim, and a corpus that serves .md that way should show up in the
# failure list rather than be guessed at.
_MARKDOWN_TYPES = frozenset({"text/markdown", "text/x-markdown"})


def _unexpected_format(fetched: Fetched) -> str | None:
    """The reason these bytes are not what the source asked for, or ``None``.

    A page rejected here is never written and never remembered, so it cannot
    become a phantom document -- and it is reported like any other failure, which
    is where a loss belongs. ``content_type`` of ``None`` (a source with no
    server to ask) means no claim to check against.
    """
    if fetched.content_type is None:
        return None
    media_type = fetched.content_type.split(";", 1)[0].strip().lower()
    if media_type in _MARKDOWN_TYPES:
        return None
    return f"unexpected content type: {fetched.content_type}"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_pipeline_insert.py -v`
Expected: `17 passed`（原计划记 14；补 3 条契约测试后为 17）

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

> **⚠️ 已落地（2026-09-21，本任务本体之后一个独立 docs+feat 提交）：`vanished` 的判据不再只依赖 manifest 的记忆。**
> 起因见 Task 11 的 ⚠️ 第二层：manifest 读不出来时「静默重来」会让 `vanished` 变成空集，而
> `save()` 随后按内存状态重写 manifest，消失的 locator 就永久失去了记录——**这一条对「用户手删
> manifest.json」「非法 JSON」「I/O 读失败」三种起因都成立**。Task 11 的修法只让人**知道**基线丢了，
> 没有让「丢基线」这件事变得无害。根治在这里：
>
> **判据换成两条取并集**——manifest 的记忆（管 manifest 条目清理）+ raw 目录的现存文件（管磁盘自愈）：
>
> ```python
> protected = {ensure_within(docs_root / raw_relpath(ref.locator), docs_root) for ref in refs}
> stragglers = {p for p in docs_root.rglob("*") if p.is_file()} - protected
> ```
>
> 这样 manifest 全丢也只值一次重抓，删除判定照样能从文件树恢复——docstring 那句
> 「start over 是安全的失败方向」**才真正成立**（现在是不成立的，因为基线不在 raw 树里）。
>
> **三条必须钉住的性质**（否则这个改法比原方案更危险）：
> 1. `protected` 必须由 **`discover()` 的全部结果**算，**不是**由「抓取成功的那些」算——
>    否则一个临时 404 就会让 `_forget` 删掉 raw 文件，把「抓取失败」升级成「静默删数据」。
> 2. 作用域仍限 `docs_root = raw_root / source.name`，且路径一律过 `ensure_within`——
>    两个源列同一个 URL 时不能互删（现有 `_forget` 已有此保证，改判据不能丢）。
> 3. `raw_relpath` 的清洗**不可逆**（`a:b.md` 与 `a_b.md` 落同一路径），所以**不能**用 raw 路径反推
>    locator。此改法只需要「这个文件不该在」这个结论，不需要知道它是谁——**别顺手写反推**。
>
> 影响面：Task 14 的 `test_removed_page_is_deleted` / `test_insert_happens_before_delete` 需各补一条
> 「manifest 缺失时仍能删掉消失的页面」的用例；Task 17 的验收数字不变。
>
> **Task 15 的 `--full` 走的是同一条路**（`manifest = Manifest()` 是空 manifest → `vanished=∅` → 那一轮
> 不做删除，随后 `save()` 覆写）。判据改造后这条**已被兜住**：空 manifest 只剩 raw 树判断，
> 该删的照样删。CLI 帮助里仍值得写明 `--full` 的语义（忽略 manifest 记忆，不忽略文件系统）。
>
> **已落地的形态**：两个独立判断，都在插入之前算好，删除阶段分开计数。
>
> | 判断 | 来源 | 管什么 |
> |---|---|---|
> | `vanished = manifest.locators() - discovered` | manifest 的记忆 | 删 raw 文件 + 清 manifest 条目 |
> | `stragglers = raw 树现存文件 − 被认领的路径` | raw 树（**durable**） | 删 raw 文件（没有 locator 可清） |
>
> 两者不相交（`stragglers` 排除了 `vanished` 的路径），所以一个文档只计一次数。新增
> `_raw_path`（推导失败返回 `None`）/ `_discard`（容忍被锁文件）/ `_stragglers`；`_forget` 改为返回
> bool，`report.deleted` 现在只统计**真的删掉了**的。
>
> **证据（三个变体实测，不是推理）**：
> - **计划原实现（pre-C）**：`test_vanished_page_is_deleted_even_when_the_manifest_is_lost` 与
>   `test_unclaimed_file_in_the_raw_tree_is_cleaned_up` 两条红 —— 新能力真实存在。
> - **C**：26 条全绿（17 插入 + 9 顺序）。
> - **naive 变体一**（两侧不 `resolve`，直接比路径）：只挂 `test_straggler_check_compares_resolved_paths`
>   一条，现场是 `a.md` **被删掉了**。机制：数据目录写成 `data/raw/../raw` 这种形态时，`rglob`
>   回显它收到的那个根，而 `_absorb` 写的是 resolve 后的路径，两者不重叠 ⇒ 整棵 raw 树被当成无主
>   文件清空。**这是本次改动里唯一能造成数据丢失的实现方式，所以必须有测试钉住。**
> - **naive 变体二**（`claimed` 只用抓取成功的 refs 算）：只挂 `test_page_whose_fetch_failed_is_not_deleted`
>   一条，现场是 `b.md` 被删 —— 临时 404 升级成静默删数据。
>
> 两个 naive 变体都**只挂对应那一条**，说明这两条守卫测的正是它们声称的事，不是恒真。
>
> **一处刻意引入的语义变化**：`data/raw/<source>/` 下**未被认领的文件会被删除**——包括手工放进去的、
> 以及 `_atomic_write` 崩溃留下的 `.part`。理由：这个目录是我们抓下来的副本，不是用户放东西的地方，
> 而"树是权威"正是 C 成立的前提。已用 `test_unclaimed_file_in_the_raw_tree_is_cleaned_up` 钉住；
> 若将来要改成"只清理我们能识别的"，那条测试就是改动的入口。

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
Expected: `26 passed`（原计划记 19 = 5 + 14；Task 13 实为 17、C 给顺序文件补 4 条，故 9 + 17 = 26）

- [ ] **Step 5: 全量跑一遍**

Run: `uv run pytest`
Expected: 全绿 `154 passed`（原计划记 `148 passed, 6 deselected`——那 6 个联网验收测试要等 Task 17 才存在，
在此之前 `deselected` 为 0。）

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

> **⚠️ 计划 Step 3 欠了 Task 11 那笔账，另有两条自家承诺无人看守；Step 2 的红色预期也写错了（2026-09-21 实测，已修）**
>
> **① `ManifestUnreadable` 没有被 catch（Task 11 的 ⚠️ 里明确写过「连带 Task 15：`fetch_corpus.py` 要 catch
> `ManifestUnreadable` 打一句可操作的话」）。** 实测：把 `data/manifest.json` 写成 `{not json` 后跑 CLI →
> `exit_code=1`、**输出 0 行**（CliRunner 把 traceback 收进 `result.exception`），路径与恢复办法都不出现。
> 用户拿到的是 traceback。**修法**：`Manifest.load` 包 try/except，`exit 2` + 打印 `{exc}`（含路径与原因）
> + 一行 `delete <path> to rebuild it from scratch: every page is then re-fetched.`
> 实测这条修法是**唯一**会造成行为变化的改动：把 3 条新测试打回未修补的计划实现，**只挂这一条**。
>
> **② 幂等**（模块 docstring 的头号承诺：「running it twice in a row is a no-op the second time. That is the
> property the health check and the scheduled task both depend on」）：实测**行为是对的**（第二次
> `added=0 updated=0 skipped=1`），但**非联网测试一条都没覆盖**——只有 Task 17 那条联网验收在管它。
> 补 `test_second_run_is_a_no_op`（守卫，实现不动）。
>
> **③ `write_corpus` docstring 声称 "atomically, sorted by doc_id for reproducibility"**：实测**行为也是对的**
> （倒序喂进去 → 输出按 doc_id 有序、无 `.tmp` 残留），同样没有测试。补
> `test_corpus_jsonl_is_sorted_and_leaves_no_temp_file`（守卫，实现不动）。
>
> **Step 2 的红色预期写错**：`scripts/` 已是包（有空 `__init__.py`）但没有 `fetch_corpus.py`，
> 所以实际是 `ModuleNotFoundError: No module named 'scripts.fetch_corpus'`，不是
> `ImportError: cannot import name 'app' from 'scripts.fetch_corpus'`。
>
> **Task 14 那条提醒已无需改动**：`--full` 的帮助文本 `Ignore the manifest and re-fetch everything` 在 C 落地后
> 是准确的（它重抓每个页面；删除判定已不依赖 manifest，所以不受影响）。
>
> 测试 5 → 8（补 1 条修法测试 + 2 条守卫）。

> **⚠️ 一个源会删掉另一个源的文档：manifest 被当成「属于单个源」，而 CLI 让它跨源共享（2026-09-22 实测，已修）**
>
> **根因**：`sync_source` 里 `vanished = sorted(manifest.locators() - discovered)` 拿到的是**整个** manifest，
> 不是本源的子集；而 CLI 只 load 一份、传给每个源。于是第二个源跑的时候，第一个源的全部 locator 都落进
> `vanished`。`_forget` 用 `docs_root / raw_relpath(locator)` 推路径——**这个路径按构造必然在 `docs_root` 内**
> （`docs_root` 是拼在前面的），所以 `ensure_within` 不会拒绝；那儿没有文件，`unlink(missing_ok=True)`
> 于是「成功」，`gone=True`，**manifest 条目被删掉**。
>
> **实测（最小复现：两个源、一份 manifest、一个 raw_root，正是 CLI 的形状）**
>
> | 断言 | 结果 |
> |---|---|
> | 第二个源不删第一个源的文档 | **失败** —— `deleted` 计了对方的 |
> | 两源跨两次运行保持幂等 | **失败** —— `added=1, skipped=0`，重新「新增」了一遍 |
> | 第一个源的 **raw 文件**存活 | 通过 ✓ |
>
> **raw 文件是安全的**（对方源的子树下什么都没有），被毁的是 manifest。所以严重性不是数据丢失，而是：
> ① **幂等性完全失效**（只要 ≥2 个源，每次运行两个源都报全量 churn —— 实测第二次运行
> `mcp added=252 deleted=538` / `langgraph added=538 deleted=252`）；② **manifest 永远只剩最后一个源的
> 条目**，而 `health.py` 读的就是它，于是健康检查只能看到一半语料；③ `report.deleted` 在**说谎**
> （实测 langgraph 报 `deleted=252`，实际删掉 0 个字节）。
>
> **为什么 177 条测试一条都没抓到**：所有 `sync_source` 测试都只同步**一个**源（跨运行共享 manifest，
> 从不跨源共享），本任务的 CLI 测试配置里也只有一个源。**Task 17 是第一个让两个源共用一个 manifest 的
> 测试**——又一次「各自绿 ≠ 组合起来对」，与 Task 9/13 的 local_dir locator 同一形状。
>
> **修法**：**每个源一份 manifest**，`data/manifest.json` → `data/manifests/<source>.json`。
> `pipeline.py` 一行不改（`vanished` 天然正确），key 空间也天然按源隔离（两个源都有 `notes/a.md` 也不会撞）。
> `Settings.manifest_path` → `manifests_dir` + `manifest_path_for(name)`；`health.py` 默认合并整个目录
> （见 Task 16）；设计文档 §4.2 / §6.1.4 已同步。Step 3 的代码见下。
>
> **顺带**：源名现在同时是目录名（`raw/<name>/`）和文件名（`manifests/<name>.json`），所以在 `SourceConfig`
> 里加了路径段校验（`^[A-Za-z0-9][A-Za-z0-9._-]*`，拒 `../x`、`a/b`、空串），与 `paths.py` 的盘符逃逸同一类
> 防护，只是提前到 load 期。`tests/test_config.py` 有 5 条参数化用例钉它。
>
> **测试计数 8 → 10**（补 `test_one_source_never_deletes_another_sources_documents`、
> `test_two_sources_are_idempotent_across_runs`）；`test_damaged_manifest_exits_with_an_actionable_message`
> 的路径改为 `data/manifests/one.json`，断言的文件名随之改为 `one.json`。

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

TWO_SOURCE_CONFIG = """
sources:
  - name: alpha
    kind: llms_txt
    llms_txt: https://alpha.example.com/llms.txt
  - name: beta
    kind: llms_txt
    llms_txt: https://beta.example.com/llms.txt
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


# --- the CLI's own promises, and Task 11's debt to it ----------------------
#
# One stub factory for the three tests below: they each need a *working* source
# (the five tests above carry their own copy, since each one stubs a different
# shape of answer).


def _stub(locators=("https://x/docs/2026-07-28/a.md",), body=b"# A\nbody\n"):
    from docsentry.corpus.sources.base import Fetched
    from docsentry.models import DocRef, SourceKind, utcnow

    class StubSource:
        name = "one"
        kind = SourceKind.LLMS_TXT

        def discover(self):
            return [
                DocRef(source="one", kind=self.kind, locator=locator, title="A")
                for locator in locators
            ]

        def fetch(self, ref):
            return Fetched(ref=ref, data=body, fetched_at=utcnow())

        def refreshable(self):
            return True

    return StubSource()


def _invoke(tmp_path, monkeypatch, **stub_kwargs):
    import scripts.fetch_corpus as cli

    monkeypatch.setattr(cli, "build_source", lambda config, settings: _stub(**stub_kwargs))
    return runner.invoke(
        app,
        [
            "--config", str(_write_config(tmp_path)),
            "--data-dir", str(tmp_path / "data"),
            "--reports-dir", str(tmp_path / "reports"),
        ],
    )


def test_damaged_manifest_exits_with_an_actionable_message(tmp_path):
    """Task 11's debt: an unreadable manifest must not reach the user as a traceback."""
    data = tmp_path / "data"
    (data / "manifests").mkdir(parents=True)
    (data / "manifests" / "one.json").write_text("{not json", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--config", str(_write_config(tmp_path)),
            "--data-dir", str(data),
            "--reports-dir", str(tmp_path / "reports"),
        ],
    )

    assert result.exit_code == 2
    assert "one.json" in result.output  # which file
    assert "delete" in result.output  # and what to do about it
    assert "Traceback" not in result.output


def test_second_run_is_a_no_op(tmp_path, monkeypatch):
    """The property the health check and the scheduled task both depend on."""
    assert _invoke(tmp_path, monkeypatch).exit_code == 0

    assert _invoke(tmp_path, monkeypatch).exit_code == 0

    payload = json.loads((tmp_path / "reports" / "latest" / "fetch.json").read_text(encoding="utf-8"))
    counts = payload["sources"][0]
    assert (counts["added"], counts["updated"], counts["skipped"]) == (0, 0, 1)


def test_corpus_jsonl_is_sorted_and_leaves_no_temp_file(tmp_path, monkeypatch):
    """Sorted by doc_id for reproducible diffs; written atomically."""
    from docsentry.models import make_doc_id

    result = _invoke(tmp_path, monkeypatch, locators=("https://x/z.md", "https://x/a.md"))

    assert result.exit_code == 0, result.output
    lines = (tmp_path / "data" / "corpus.jsonl").read_text(encoding="utf-8").strip().splitlines()
    ids = [json.loads(line)["doc_id"] for line in lines]
    assert ids == sorted(ids)
    assert ids[0] == make_doc_id("one", "https://x/a.md")  # handed back z first
    assert list((tmp_path / "data").glob("*.tmp")) == []


# --- two sources in one run ------------------------------------------------
#
# The deletion baseline is per-source, so one shared manifest makes each source
# see the others' locators as vanished. Every other test here syncs a single
# source, which is exactly why this went unnoticed until the M1 acceptance run.


def _pages(name, locator):
    from docsentry.corpus.sources.base import Fetched
    from docsentry.models import DocRef, SourceKind, utcnow

    class StubSource:
        kind = SourceKind.LLMS_TXT

        def __init__(self):
            self.name = name

        def discover(self):
            return [DocRef(source=name, kind=self.kind, locator=locator, title=name)]

        def fetch(self, ref):
            return Fetched(ref=ref, data=f"# {name}\nbody\n".encode(), fetched_at=utcnow())

        def refreshable(self):
            return True

    return StubSource()


def _invoke_two_sources(tmp_path, monkeypatch):
    import scripts.fetch_corpus as cli

    stubs = {
        "alpha": _pages("alpha", "https://alpha.example.com/docs/a.md"),
        "beta": _pages("beta", "https://beta.example.com/docs/b.md"),
    }
    monkeypatch.setattr(cli, "build_source", lambda config, settings: stubs[config.name])
    return runner.invoke(
        app,
        [
            "--config", str(_write_config(tmp_path, TWO_SOURCE_CONFIG)),
            "--data-dir", str(tmp_path / "data"),
            "--reports-dir", str(tmp_path / "reports"),
        ],
    )


def _counts(tmp_path):
    payload = json.loads((tmp_path / "reports" / "latest" / "fetch.json").read_text(encoding="utf-8"))
    return {source["name"]: source for source in payload["sources"]}


def test_one_source_never_deletes_another_sources_documents(tmp_path, monkeypatch):
    result = _invoke_two_sources(tmp_path, monkeypatch)

    assert result.exit_code == 0, result.output
    counts = _counts(tmp_path)
    assert counts["alpha"]["added"] == 1
    assert counts["beta"]["added"] == 1
    # Nothing has vanished from either source on a first run.
    assert counts["alpha"]["deleted"] == 0, "alpha's documents were counted as vanished during beta's sync"
    assert counts["beta"]["deleted"] == 0


def test_two_sources_are_idempotent_across_runs(tmp_path, monkeypatch):
    """The scheduled task's premise, which only holds if the baselines are separate."""
    _invoke_two_sources(tmp_path, monkeypatch)

    result = _invoke_two_sources(tmp_path, monkeypatch)

    assert result.exit_code == 0, result.output
    for name, counts in _counts(tmp_path).items():
        assert (counts["added"], counts["updated"], counts["deleted"]) == (0, 0, 0), (
            f"{name} churned on a second run: {counts}"
        )
        assert counts["skipped"] == counts["discovered"] == 1

```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_fetch_corpus_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.fetch_corpus'`
（原计划记 `ImportError: cannot import name 'app' ...`。`scripts/` 是包但该模块不存在，
所以是 ModuleNotFoundError；见本任务开头的 ⚠️。）

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
from docsentry.corpus.manifest import Manifest, ManifestUnreadable
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

    # One manifest per source, all loaded before anything is fetched: a damaged
    # baseline should abort the whole run rather than half of it. Sharing one
    # file across sources would make each source read the others' locators as
    # vanished -- see Settings.manifest_path_for.
    manifests: dict[str, Manifest] = {}
    for source_config in selected:
        if full:
            manifests[source_config.name] = Manifest()  # empty == everything looks new
            continue
        try:
            manifests[source_config.name] = Manifest.load(settings.manifest_path_for(source_config.name))
        except ManifestUnreadable as exc:
            # Aborting beats pretending the file was absent: the manifest is
            # also the deletion baseline, so rebuilding it quietly costs more
            # than the re-fetch it saves (see the manifest module's docstring).
            typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
            typer.secho(
                f"       delete {exc.path} to rebuild it from scratch: every page is then re-fetched.",
                err=True,
            )
            raise typer.Exit(code=2)

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
                manifest=manifests[source_config.name],
                report=source_report,
                workers=settings.fetch_workers,
            )
        )
        reports.append(source_report)

    for name, source_manifest in manifests.items():
        source_manifest.save(settings.manifest_path_for(name))
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
Expected: `8 passed`（原计划记 5；补 1 条修法测试 + 2 条守卫后为 8）

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

> **⚠️ Step 3 的 manifest 加载是对 `Manifest.load` 的一次更差的重新实现；计划 7 条测试没有一条跨过它的失败路径（2026-09-22 实测，已修）**
>
> **① `load_manifest_entries` 重现了 Task 11 已经修掉的那个异常枚举缺陷。** 实测 6 条探针（计划的测试
> 一条都不覆盖这些输入）：
>
> | 探针输入 | Step 3 原代码 | 改用 `Manifest.load` 后 |
> |---|---|---|
> | manifest 存在、JSON 截断 | **exit 0**，`no manifest at … -- run fetch_corpus.py first` | exit 2，`… is unreadable: not valid JSON: …` |
> | 合法 JSON、形状是 list | exit 1，`AttributeError` traceback | exit 2，`expected a JSON object, got list` |
> | entry 缺 `fetched_at` | exit 1，`KeyError` traceback | exit 2，`entry '…' is malformed: 'fetched_at'` |
> | `fetched_at` 无时区 | exit 1，`TypeError` traceback | exit 2（依赖下面 ② 的加固） |
> | 不是 UTF-8 的字节 | exit 1，`UnicodeDecodeError` traceback | exit 2，`'utf-8' codec can't decode byte 0xff …` |
> | `--manifest` 指向目录 | **exit 0**，`no manifest` | exit 2，`Permission denied: …` |
>
> 第 1、6 行是两处**谎报**：把「读不出来」说成「不存在」，退出码还是 0。这个模块的 docstring 写着
> 「The failure this guards against is silent: a source that failed months ago leaves an index that looks
> complete」——而它对一个损坏的 manifest 给出的回答，正是它声明要消灭的那类静默假安慰，只是升了一层：
> 索引已经不可信，告警不响。**代价**：health.py 是设计 §6.1.5 第三条风险的载体、定时任务的判据，
> 而日志里 `no manifest` 与「首次运行、还没抓过」**逐字不可区分**。第 5 行的
> `UnicodeDecodeError ⊂ ValueError`（**不是** `OSError`）就是 Task 11 那条 ⚠️ 修掉的同一个错——
> 同一个计划补在一个模块里，又在下一个模块踩了回来。
>
> **修法**：删掉 `load_manifest_entries`，入口直接 `Manifest.load` + catch `ManifestUnreadable` → `exit 2`
> + 打印 `{exc}`（含路径与原因）+ 一行可操作的话。**与 `fetch_corpus.py` 对同一个异常的处置保持一致。**
> 但**别照抄它的措辞**——两个工具的成本不同：**health.py 从不回写 manifest**，所以 Task 11
> 「静默重建会毁掉删除基线」那条论证在这里不成立。它仍然该 exit 2，理由是另一个：**一个读不出文件的
> 健康检查回答「一切正常」，比拒绝回答更糟**；而「删掉它重建」是 fetch 侧的决定，不由只读的诊断工具越俎代庖。
>
> **`stale_documents` 的参数随之由原始 JSON dict 改为 `Manifest`**：入口拿到的已是 `Manifest`，
> 再转回 dict 等于同一份数据在一个模块里有两种表示。计划 3 条单测的夹具改用 `Manifest` /
> `ManifestEntry` 构造；**4 条 CLI 测试逐字节不变**（它们写真实 manifest 文件，`Manifest.load` 照读）。
>
> **② `ManifestEntry.from_json` 接受无时区时间戳**（探针第 4 行）。`fromisoformat("2020-01-01T00:00:00")`
> 合法、parse 得出来，然后在**第一个做日期算术的读方**那里炸——health.py 的 `now - fetched_at` 实测
> `TypeError: can't subtract offset-naive and offset-aware datetimes`。修法：`from_json` 里拒收 naive，
> 抛 `ValueError` → 被 `Manifest.load` 已有的 `except (KeyError, TypeError, ValueError)` 转成
> `ManifestUnreadable`。**这是 Task 11 的模块**，敢改的依据：`from_json` 全仓只有一个调用方
> （`Manifest.load`），而我们自己的写方 `utcnow()` 恒为 aware——**naive 值只可能来自手改或外部工具，
> 那正是该被拒绝的输入**。`tests/test_manifest.py` 补 1 条：
>
> ```python
> def test_load_naive_timestamp_raises(tmp_path):
>     # A timestamp with no offset parses fine, then detonates in the first reader
>     # that does date arithmetic (`now - fetched_at`). We only ever write
>     # utcnow(), so a naive value is foreign by construction -- reject it at the
>     # boundary, where the fault is still attributable to a file.
>     path = tmp_path / "manifest.json"
>     path.write_text(
>         json.dumps(
>             {"https://x/a.md": {"content_hash": "h", "version": "draft", "fetched_at": "2020-01-01T00:00:00"}}
>         ),
>         encoding="utf-8",
>     )
>
>     with pytest.raises(ManifestUnreadable, match="unreadable") as excinfo:
>         Manifest.load(path)
>
>     assert "no timezone" in excinfo.value.reason
> ```
>
> **③ 补 2 条守卫测试（2026-09-22）。** 上表的 P1 与 P5 是两处具体缺陷，但修完之后，
> 「读不出文件就拒绝回答」这条契约**在测试里没有任何一处被钉住**——下一次把 `except` 改回
> 静默返回 `{}`，套件照样全绿。而 health.py 的 docstring 现在正是拿这条当核心承诺写的。
> 两条守卫各钉一个已经咬过人的事实：截断 JSON（不许谎报成 `no manifest` + 退出码 2 + 输出含路径）、
> 非 UTF-8 字节（`UnicodeDecodeError ⊂ ValueError`，**不是** `OSError`）。
>
> **④ 这个脚本没有 `__main__` 入口，`uv run scripts/health.py` 是一句静默空操作
> （2026-09-22 首次真跑时实测，已修）**
>
> Step 3 的代码块结束于 `main()` 函数体，**没有** `if __name__ == "__main__": app()` ——
> 而 `fetch_corpus.py` 有。于是被 `python scripts/health.py` 直接执行时，模块把 `app` 定义出来就退出了：
> **exit code 0、stdout 空、stderr 空**。实测即 `CompletedProcess(returncode=0, stdout='', stderr='')`。
>
> 这正是 Task 17 Step 5 唯一写下的调用方式（`uv run scripts/health.py`），也是用户唯一会敲的那条命令。
> **一个健康检查静默地什么都不做**——它存在的理由恰恰是消灭这种失败。
>
> **为什么上面 9 条测试全都看不见它**：它们都走 `CliRunner.invoke(app, [...])`，直接调用 Typer 应用对象，
> **从不需要模块本身可执行**。「测试全绿 ≠ 那个产物能用」，这是本项目第二次栽在这条上。
>
> **修法**：补上 `__main__` 入口。**并补 3 条测试**，直接跑进程而不经过 `CliRunner`：
> ① `test_every_script_has_a_command_line_entry_point`（参数化扫 `scripts/*.py`，以 `--help` 验证可执行性——
> 以后新增脚本自动被覆盖）、② `test_health_script_reports_when_run_as_documented`（按文件里写的那条命令真跑，
> 断言输出含 `documents: 1`）。第 ③ 条是 `merge_manifests` 的行为：一个源损坏时**整次合并中止**，
> 不能悄悄跳过它（`test_cli_aborts_on_any_unreadable_manifest_not_just_the_first`）。
>
> **同时 `health.py` 的默认读取对象变了**：manifest 改成每源一份（见 Task 15 的 ⚠️），所以默认读
> `data/manifests/` 下所有文件并合并（`merge_manifests`），`--manifest <file>` 保持"只看这一个文件"的语义
> ——上面 6 条走 `--manifest` 的测试因此逐字节不变。
>
> **测试计数：7 → 9 → 14**（③ 加 2 条守卫；④ 加 2 条合并 + 3 条可执行性，其中 1 条按脚本参数化出 2 个用例）。
> Step 4 的预期同步改为 **`14 passed`**。
>
> 三处改动都已离线实测（scratch 里跑计划代码 + 计划测试，只改 import）：计划那 4 条 CLI 测试
> 在改后**逐字节不变地通过**，9 条全绿。**实现落地时直接按上面的代码块抄**——repo 里的
> `scripts/health.py` 与 `tests/test_health.py` 是从本文件的代码块**提取**生成的，不是手抄的。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_health.py
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from docsentry.corpus.manifest import Manifest, ManifestEntry
from scripts.health import app, stale_documents

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[1]

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


def _manifest_of(entries):
    """``{locator: (version, days_old)}`` -> Manifest -- the shape the CLI reads."""
    return Manifest(
        {
            locator: ManifestEntry(
                content_hash="h", version=version, fetched_at=NOW - timedelta(days=days_old)
            )
            for locator, (version, days_old) in entries.items()
        }
    )


def test_stale_documents_flags_old_entries():
    manifest = _manifest_of(
        {"https://x/fresh.md": ("2026-07-28", 1), "https://x/old.md": ("2026-07-28", 30)}
    )

    stale = stale_documents(manifest, max_age_days=7, now=NOW)

    assert [locator for locator, _, _ in stale] == ["https://x/old.md"]


def test_stale_documents_reports_days_since_check():
    manifest = _manifest_of({"https://x/old.md": ("2026-07-28", 30)})

    stale = stale_documents(manifest, max_age_days=7, now=NOW)

    assert stale[0][1] == 30


def test_stale_documents_is_empty_when_all_fresh():
    manifest = _manifest_of({"https://x/a.md": ("2026-07-28", 0)})

    assert stale_documents(manifest, max_age_days=7, now=NOW) == []


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


def test_cli_merges_every_source_manifest(tmp_path, monkeypatch):
    """One manifest per source, so the default view is all of them together."""
    data = tmp_path / "data"
    manifests = data / "manifests"
    manifests.mkdir(parents=True)
    (manifests / "mcp.json").write_text(json.dumps({"https://m/a.md": _entry("2026-07-28")}), encoding="utf-8")
    (manifests / "langgraph.json").write_text(json.dumps({"https://l/a.md": _entry("unknown")}), encoding="utf-8")
    monkeypatch.setenv("DOCSENTRY_DATA_DIR", str(data))

    result = runner.invoke(app, ["--now", NOW.isoformat()])

    assert result.exit_code == 0, result.output
    assert "documents: 2" in result.output
    assert "1 dated, 0 draft, 1 unknown" in result.output
    assert "2 sources" in result.output


def test_cli_aborts_on_any_unreadable_manifest_not_just_the_first(tmp_path, monkeypatch):
    """Merging must not dilute the rule the guard tests below pin down."""
    data = tmp_path / "data"
    manifests = data / "manifests"
    manifests.mkdir(parents=True)
    (manifests / "a-good.json").write_text(json.dumps({"https://x/a.md": _entry()}), encoding="utf-8")
    (manifests / "z-broken.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("DOCSENTRY_DATA_DIR", str(data))

    result = runner.invoke(app, ["--now", NOW.isoformat()])

    assert result.exit_code == 2
    assert "no manifest" not in result.output.lower()


def test_cli_refuses_to_report_on_an_unreadable_manifest(tmp_path):
    # The plan's loader caught the exception and returned {} -- a corrupt
    # manifest was reported as an absent one with exit code 0, which a
    # scheduled task cannot tell apart from a first run.
    path = tmp_path / "manifest.json"
    path.write_bytes(b'{"https://x/a.md": {"content_hash": "h",')  # truncated write

    result = runner.invoke(app, ["--manifest", str(path), "--now", NOW.isoformat()])

    assert result.exit_code == 2
    assert str(path) in result.output
    assert "no manifest" not in result.output.lower()


def test_cli_refuses_on_undecodable_bytes(tmp_path):
    # UnicodeDecodeError derives from ValueError, not OSError, so an
    # `except OSError` around the read does not catch it. That is how the first
    # version of this escaped (see the manifest module's docstring).
    path = tmp_path / "manifest.json"
    path.write_bytes(b"\xff\xfe{}")  # not UTF-8

    result = runner.invoke(app, ["--manifest", str(path), "--now", NOW.isoformat()])

    assert result.exit_code == 2
    assert "unreadable" in result.output.lower()


# --- the command line the plan actually documents --------------------------
#
# Every test above calls the Typer app object through CliRunner, which never
# needs the module to be *executable*. So all of them passed while
# `uv run scripts/health.py` -- the invocation in the plan and the only one a
# user types -- was a silent no-op: no `__main__` guard, exit 0, no output.

SCRIPTS = sorted(path for path in (REPO_ROOT / "scripts").glob("*.py") if path.name != "__init__.py")


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda path: path.name)
def test_every_script_has_a_command_line_entry_point(script):
    result = subprocess.run(
        [sys.executable, str(script), "--help"], capture_output=True, text=True, cwd=REPO_ROOT
    )

    assert result.returncode == 0, f"{script.name} is not runnable: {result.stderr}"
    assert "usage" in result.stdout.lower()


def test_health_script_reports_when_run_as_documented(tmp_path):
    data = tmp_path / "data"
    (data / "manifests").mkdir(parents=True)
    (data / "manifests" / "one.json").write_text(json.dumps({"https://x/a.md": _entry()}), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "health.py"), "--now", NOW.isoformat()],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "DOCSENTRY_DATA_DIR": str(data)},
    )

    assert result.returncode == 0, result.stderr
    assert "documents: 1" in result.stdout
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

Reading goes through ``Manifest.load`` rather than re-parsing the JSON here.
There is one loader for this file and it already draws the line between "no
manifest yet" and "manifest present but unusable" (that module's docstring
explains why the distinction is load-bearing); a second, weaker parser beside
it would report a corrupt manifest as a missing one -- which is the same
silent-completeness failure this module exists to surface, one level up.

There is one manifest per source, so the default reads and merges them all:
the questions here are about the corpus as a whole. ``--manifest`` points at a
single file instead, which is what the unit tests use.

Unlike ``fetch_corpus``, this script never writes the manifest, so an unreadable
one cannot cost us the deletion baseline. It aborts anyway: a health check that
answers "nothing to report" for a file it could not read is worse than one that
refuses to answer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import typer

from docsentry.config import Settings
from docsentry.corpus.manifest import Manifest, ManifestUnreadable
from docsentry.corpus.versioning import version_bucket

app = typer.Typer(add_completion=False, help="Report corpus health and staleness.")


def merge_manifests(manifests_dir: Path) -> tuple[Manifest, str]:
    """Every per-source manifest under ``manifests_dir``, as one view.

    Locators are unique per source; should two sources ever list the same one,
    the last file read wins, which can only misstate the reported totals.
    """
    paths = sorted(manifests_dir.glob("*.json")) if manifests_dir.is_dir() else []
    merged = Manifest()
    for path in paths:
        for locator, entry in Manifest.load(path).items():
            merged.set(locator, entry)
    label = f"{manifests_dir} ({len(paths)} sources)" if paths else str(manifests_dir)
    return merged, label


def stale_documents(manifest: Manifest, *, max_age_days: int, now: datetime):
    """``[(locator, days_since_check, version)]`` for entries older than the limit."""
    stale = []
    for locator, entry in manifest.items():
        age_days = (now - entry.fetched_at).days
        if age_days > max_age_days:
            stale.append((locator, age_days, entry.version))
    return sorted(stale, key=lambda item: item[1], reverse=True)


@app.command()
def main(
    manifest: Path = typer.Option(None, "--manifest"),
    max_age_days: int = typer.Option(7, "--max-age-days", help="Warn beyond this many days unverified"),
    now: str = typer.Option(None, "--now", help="Override the current time (for tests)"),
) -> None:
    settings = Settings()
    try:
        if manifest is not None:
            corpus_manifest, label = Manifest.load(manifest), str(manifest)
        else:
            corpus_manifest, label = merge_manifests(settings.manifests_dir)
    except ManifestUnreadable as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        typer.secho(
            "       the corpus is unverified until this is resolved;"
            " run fetch_corpus.py to rebuild it.",
            err=True,
        )
        raise typer.Exit(code=2)

    if not corpus_manifest:
        typer.echo(f"no manifest at {label} -- run fetch_corpus.py first")
        raise typer.Exit(code=0)

    buckets = {"dated": 0, "draft": 0, "unknown": 0}
    for _, entry in corpus_manifest.items():
        buckets[version_bucket(entry.version)] += 1

    typer.echo(f"manifest: {label}")
    typer.echo(f"documents: {len(corpus_manifest)}")
    typer.echo(f"versions: {buckets['dated']} dated, {buckets['draft']} draft, {buckets['unknown']} unknown")

    current = datetime.fromisoformat(now) if now else datetime.now(timezone.utc)
    stale = stale_documents(corpus_manifest, max_age_days=max_age_days, now=current)
    if stale:
        typer.secho(f"\nstale: {len(stale)} documents unverified for over {max_age_days} days", fg=typer.colors.YELLOW)
        for locator, age_days, version in stale[:20]:
            typer.echo(f"  {age_days:>4}d  [{version}]  {locator}")
        if len(stale) > 20:
            typer.echo(f"  ... and {len(stale) - 20} more")


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_health.py -v`
Expected: `14 passed`

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

> **⚠️ Step 1 的 `_sync` 自己造了一个 source，绕开了 CLI 用的 `build_source()`（2026-09-22 实测，已修）**
>
> 原代码直接 `LlmsTxtSource(name=…, llms_txt=…, url_include=…, timeout_s=…, retries=…)`，两个后果：
>
> - **`keep_all_versions` 没有接**。`LlmsTxtSource.__init__` 的默认值是 `True`，而 `configs/sources.yaml`
>   里两个源恰好都是 `true`——**所以今天测不出差别**。但 `build_source()` 是 `config.keep_all_versions`
>   **唯一**的接线处，验收测试绕开了它：只要有人把配置改成 `false`，CLI 会剪枝、验收测试照旧保留全部
>   版本，**测试仍绿，却在对一条没人跑的管线做断言**。
> - `_sync` 的第一个参数 `name` 完全没被使用（源名取的是 `config.name`；实测确认是死参数）。
>
> 这就是本项目已经付过学费的那类缝：**两个各自评审过的构造点，测试只覆盖其中一个**——Task 9/13 的
> local_dir locator 是同一形状（见 Task 13 开头的 ⚠️）。修法：`_sync` 改调
> `build_source(config, settings)`，调用点由 `_sync("mcp", sources["mcp"], …)` 改为
> `_sync(sources["mcp"], …)`。**测试数不变（6）**；离线已核：收集 6 条、`build_source` 对两个源返回的
> 属性与配置逐项一致。
>
> **这不改变里程碑的验证强度**：Step 3–5 会真跑 CLI 并核对控制台数字，配置接线在那里被端到端覆盖。
> 这条修的是**测试文件本身是否忠实代表**——验收测试说「这条管线产出 621 篇」时，指的必须是 CLI 跑的那条。

> **⚠️ 2026-09-22 首次联网实测（本计划此前从未真跑过联网源）：三个真缺陷 + 一次语料漂移，已全部修复并重跑通过**
>
> 四件事一次跑出来，**这就是这条验收测试存在的意义**。逐条：
>
> **A. 一个源删掉另一个源的文档。** `test_two_sources_yield_at_least_400_documents` 直接挂：
> langgraph 的 report 里 `deleted=252`，而那 252 篇是 MCP 的。根因、复现与修法见 **Task 15 的 ⚠️**
> 与设计文档 §6.1.4。本测试因此新增 `assert report.deleted == 0`——**首次运行本就没有东西可删**，
> 这一条就是 A 的守卫（它今天会直接抓住回归）。
>
> **B. 验收测试要求上游语料完美无瑕。** 计划的 `assert not report.failed` 挂在一条 404 上：
> `oss/python/deepagents/code-link.md` 被 LangChain 的索引列着，但站点对 `.md` 与不带 `.md` 两种形式
> **都回 404**（实测 `curl` 确认）。而管线自己的 docstring 写的是「one 404 must not cost us the other 699
> pages, and the report makes the loss visible」——**404 是被汇报的对象，不是系统的失败**。
> 修法：断言改为「有界且可归因」（见下方 `MAX_FAILURE_RATE`，且每条失败必须写明原因）。
>
> **C. 16 篇 HTML 冒充 Markdown，占语料正文字节的 48%。** 首轮 790 篇里，`reference/*.md`、
> `changelog-*.md`、`academy.md`、`studio.md` 共 16 篇由站点以 **`200 text/html`** 返回（真 markdown 页是
> `text/markdown; charset=utf-8`），转换器照单全收，还把 `origin_format` 报成 `md`。两个后果：
> ① 语料是按 Markdown 构造的，却混进 13.42 MB 的 Vercel 应用外壳；
> ② 其中 4 篇内嵌 per-request CSRF token，**字节每次请求都变**，于是第二次运行永远报 `updated=4`——
> **幂等性在结构上不可能成立**。
> 修法见 Task 6 / Task 8 / Task 13 的追补：`Fetched` 带上服务器的 `Content-Type`，管线拒收非 markdown 并
> 记为失败。修后：16 篇进失败清单，`corpus.jsonl` 774 篇（790 − 16），第二次运行
> `added=0 updated=0 skipped=774 deleted=0` ✓。
> **顺带**：本计划原有的 `test_documents_are_real_markdown_with_titles` 只抽样 MCP 的
> `/specification/2026-07-28/`，所以它检查了一条源、对另一条完全失明。新增
> `test_no_html_page_is_ingested`，扫**全部源的全部文档**。
>
> **D. `health.py` 没有 `__main__` 入口。** Step 5 那条命令原本是一句静默空操作（exit 0、零输出）。
> 详见 **Task 16 的 ⚠️ ④**。
>
> **附：语料本身也动了**（这不是缺陷，恰是本项目研究的现象）。langgraph 从 369 篇变成 **539** 篇——
> LangChain 把 `/oss/python/` 拆成了 8 个平级子索引（`/oss/python/llms.txt` 369 + concepts 4 +
> contributing 8 + deepagents 40 + langchain 76 + langgraph 43 + migrate 4 + releases 3，去重后 539）。
> 因此下面 Step 3/4/5 的期望数字**按 2026-09-22 实测重写**；且「总数」类断言一律改成**下界**——
> 语料会变，验收标准不该跟着变。
>
> **测试计数 6 → 8**（补 `test_every_failure_names_a_reason_we_expect`、`test_no_html_page_is_ingested`；
> `test_documents_are_real_markdown_with_titles` 更名为 `test_mcp_documents_are_real_markdown_with_titles`
> 并限定到 MCP；`test_second_run_skips_everything` 的核算改为「skipped + failed == discovered」，
> 因为失败页本来就不会被 skip）。
>
> **补记（同日，用户定的）：6 条只读测试改用共享 fixtures。** 原写法每条测试各自 sync 自己需要的源，
> 实测 **9 分 40 秒 / 约 5250 次请求**——同一份上游状态在一次运行里被下载了 6–7 遍。改成
> module 作用域的 `synced` fixture（两源各抓一次，仍然共用一个 `raw_root`、仍按配置顺序），
> 于是：**4 分 57 秒 / 约 2370 次请求**。
>
> **没有削弱的守卫**：A 的守卫（一个进程里两源先后写进同一 `raw_root`，断言 `deleted == 0`）由 fixture
> 本身承担；C 的守卫仍扫全部 774 篇；版本/标题/失败归因全部照旧。**削弱的只是冗余**——两源序列原本跑 3 遍、
> mcp 同步跑 4 遍，而对活语料来说一次运行内重复上游状态买不到东西。
> **代价（如实记下）**：setup 出问题会以 ERROR 挂在 6 条测试上，第一眼看到的失败未必是根因；
> 且读代码的人必须看 fixture 才知道测试的起点。
>
> **`test_second_run_skips_everything` 保持自闭环**（自己的 data dir、自己跑两遍）：幂等性 *就是*
> 「同一目录连跑两次」，借别人的基线会让这条测试依赖夹具的执行顺序，且窗口内上游内容真变了会误报。
> 因此套件里仍有两次全量跑省不掉——这是这条性质的固有成本，不是夹具的缺陷。

- [ ] **Step 1: 写验收测试**

```python
"""M1 acceptance against the real corpora.

Excluded by default (see pyproject `addopts`). Run with:

    uv run pytest -m network -v

Slow by design: it downloads both corpora end to end. Six of the eight tests
read one shared first-run sync (see the `synced` fixture); only the idempotence
test re-fetches, because two consecutive runs *are* its subject.

This is the only test that talks to the real internet, and the first live run
(2026-09-22) is why it exists: it found that a page the site does not publish
as Markdown was being ingested as if it were, that LangChain serves sixteen
such pages, and that two sources sharing one manifest delete each other's
entries. None of that was visible to the other 192 tests, which use stubs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docsentry.config import Settings, load_sources_config
from docsentry.corpus.converters.markdown import MarkdownConverter
from docsentry.corpus.manifest import Manifest
from docsentry.corpus.pipeline import sync_source
from docsentry.corpus.report import SourceReport
from scripts.fetch_corpus import build_source

pytestmark = pytest.mark.network

CONFIG = Path("configs/sources.yaml")

# Upstream is not perfect and neither are we entitled to assume it is: the
# index lists pages that 404, and pages that are not served as Markdown at all
# (design spec 6.1.2 -- a source can only promise to re-read the pointer).
# What we do owe is that the loss is small, bounded, and *named*.
MAX_FAILURE_RATE = 0.05


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings()


@pytest.fixture(scope="module")
def sources():
    return {s.name: s for s in load_sources_config(CONFIG).sources}


def _enabled(sources) -> list:
    return [config for config in sources.values() if config.enabled]


def _scoped(settings: Settings, data_dir: Path) -> Settings:
    """The real settings, pointed at a temp dir.

    Same type and same derived paths -- including ``manifest_path_for`` -- so the
    test exercises the CLI's own layout rather than a parallel one, without
    reading or writing the repo's ``data/``.
    """
    return settings.model_copy(update={"data_dir": data_dir, "reports_dir": data_dir.parent / "reports"})


def _sync(config, settings: Settings):
    """Run one source exactly as the CLI does: its own manifest, start to finish."""
    manifest = Manifest.load(settings.manifest_path_for(config.name))
    report = SourceReport(name=config.name, kind=config.kind)

    documents = sync_source(
        source=build_source(config, settings),
        converter=MarkdownConverter(),
        raw_root=settings.raw_dir,
        manifest=manifest,
        report=report,
        workers=settings.fetch_workers,
    )
    manifest.save(settings.manifest_path_for(config.name))
    return documents, report


def _sync_all(configs, settings: Settings):
    return {config.name: _sync(config, settings) for config in configs}


@pytest.fixture(scope="module")
def synced(settings, sources, tmp_path_factory):
    """Both sources, one first run, shared by the tests below.

    Syncing per test downloaded the two corpora seven times over (~5250 requests,
    measured 9m40s) to observe an upstream state that cannot differ within a
    single run. The sources still share one ``raw_root``, in config order -- that
    is the CLI's own shape, and the reason a cross-source deletion is visible
    here at all (`test_one_source_never_deletes_another_sources_documents` in
    test_fetch_corpus_cli.py pins the same interaction on stubs).
    """
    scoped = _scoped(settings, tmp_path_factory.mktemp("corpus"))
    return _sync_all(_enabled(sources), scoped)


def test_two_sources_yield_at_least_400_documents(synced):
    total = 0
    for name, (documents, report) in synced.items():
        # A first run has nothing to delete. Counting a deletion here means a
        # source looked at another source's baseline (or its own stray files).
        assert report.deleted == 0, f"{name} deleted {report.deleted} on a first run"
        assert len(report.failed) <= MAX_FAILURE_RATE * report.discovered, f"{name}: {report.failed[:5]}"
        total += len(documents)

    assert total >= 400, f"only {total} documents"


def test_every_failure_names_a_reason_we_expect(synced):
    """The report is where a loss belongs; it must never be unexplained."""
    for name, (_, report) in synced.items():
        for failure in report.failed:
            assert "404" in failure["error"] or "unexpected content type" in failure["error"], (
                f"{name}: {failure}"
            )


def test_no_html_page_is_ingested(synced):
    """langchain serves sixteen `.md` URLs as `text/html`.

    Four of those embed a per-request CSRF token, so before this guard they
    were also the reason a second run could never report zero changes.
    """
    for name, (documents, _) in synced.items():
        for document in documents:
            assert not document.content.lstrip().startswith("<!DOCTYPE"), f"{name}: {document.url}"


def test_mcp_version_labelling_is_at_least_90_percent(synced):
    """The M1 criterion, measured over the pages actually indexed.

    `/docs/` + `/specification/` are 252 pages: 198 dated + 54 draft. The 95
    versionless pages (`/seps/`, `/community/`, `/registry/`, `/extensions/`)
    are deliberately not part of this source (see configs/sources.yaml), so
    they cannot dilute the figure. `draft` is a real version channel and counts
    as labelled.
    """
    _, report = synced["mcp"]

    assert report.versions["dated"] + report.versions["draft"] >= 0.9 * report.discovered
    assert report.discovered >= 240


def test_mcp_covers_every_published_spec_version(synced):
    """Version-aware retrieval is only meaningful if the versions are all there."""
    documents, _ = synced["mcp"]

    versions = {document.version for document in documents}

    assert {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"} <= versions
    assert "draft" in versions


def test_langchain_recursion_expands_the_python_index(synced):
    """Recursion reaches the topic sub-indexes, not just the top-level one.

    2026-09-22: 539 discovered -- 369 from `/oss/python/llms.txt` plus seven
    sibling sub-indexes (concepts, contributing, deepagents, langchain,
    langgraph, migrate, releases). The floor is deliberately well below the
    observed count: this asserts that recursion happened, not how big the
    corpus is on any given day.
    """
    documents, report = synced["langgraph"]

    assert len(documents) >= 350
    assert report.versions["unknown"] == len(documents)  # the corpus carries no versions


def test_mcp_documents_are_real_markdown_with_titles(synced):
    documents, _ = synced["mcp"]
    sample = [d for d in documents if "/specification/2026-07-28/" in d.url]

    assert sample, "no 2026-07-28 specification pages retrieved"

    for document in sample:
        assert document.title, f"no title extracted from {document.url}"
        assert len(document.content) > 500, f"suspiciously short: {document.url}"
        # the per-page navigation banner must be gone from every page
        assert "Documentation Index" not in document.content, document.url


def test_second_run_skips_everything(settings, sources, tmp_path):
    """Idempotence -- the property the scheduled task depends on.

    Deliberately not the shared fixture: two consecutive runs against one data
    dir *is* the property, so it owns its corpus rather than borrowing a
    baseline someone else established.
    """
    scoped = _scoped(settings, tmp_path / "data")
    configs = _enabled(sources)
    _sync_all(configs, scoped)

    for name, (_, second) in _sync_all(configs, scoped).items():
        assert second.added == 0, f"{name} re-added {second.added}"
        assert second.updated == 0, f"{name} re-fetched {second.updated} as changed"
        assert second.deleted == 0, f"{name} deleted {second.deleted}"
        # Every discovered page is either unchanged or explained by a failure.
        assert second.skipped + len(second.failed) == second.discovered
```

- [ ] **Step 2: 跑验收测试**

Run: `uv run pytest -m network -v`
Expected: `8 passed`（**实测 4 分 57 秒**。计划原文记「1–3 分钟」，那是 6 条测试时的估算。
最初「每条测试各自抓」的写法实测 **9 分 40 秒 / 约 5250 次请求**，改成共享 fixtures 后 **297 秒 / 约 2370 次**——
详见下面 ⚠️ 里的取舍。）

- [ ] **Step 3: 真实抓取一回，留下证据**

Run: `uv run scripts/fetch_corpus.py --update`
Expected 输出形态（**2026-09-22 实测数字**）：

```
fetching mcp ...
fetching langgraph ...

fetch report  (NN.Ns)

  17 failed:
    - langgraph: …/deepagents/changelog-js.md: unexpected content type: text/html; charset=utf-8
    …（共 16 条非 markdown）
    - langgraph: …/deepagents/code-link.md: HTTPStatusError: … 404 …

  mcp        discovered=252   added=252   updated=0     skipped=0     deleted=0
             versions: 198 dated, 54 draft, 0 unknown (100% labelled)
  langgraph  discovered=539   added=522   updated=0     skipped=0     deleted=0
             versions: 0 dated, 0 draft, 522 unknown (0% labelled)

  total      discovered=791 added=774 updated=0 skipped=0 deleted=0

corpus: data\corpus.jsonl  (774 documents)
report: reports\fetch-<ts>.json
```

**退出码是 1**（有失败即非零，供定时任务感知），这是预期行为，不是错误。
`522 = 539 − 16 篇 HTML − 1 条 404`。

- [ ] **Step 4: 再跑一次，确认幂等**

Run: `uv run scripts/fetch_corpus.py --update`
Expected: `added=0 updated=0 deleted=0`，且**每个源 `skipped + 失败数 == discovered`**
（失败页不会被 skip，所以原文那句「skipped 等于各自 discovered」是错的）：
mcp `skipped=252`、langgraph `skipped=522`（另 17 条失败）、total `skipped=774`。

- [ ] **Step 5: 跑健康检查**

Run: `uv run scripts/health.py`
Expected（**默认合并 `data/manifests/` 下的每源一份**）：

```
manifest: data\manifests (2 sources)
documents: 774
versions: 198 dated, 54 draft, 522 unknown
```

无 stale 告警（首轮刚抓过）。计划原文记的 `documents: 621` 是旧语料规模。

- [ ] **Step 6: 全量测试 + 提交**

Run: `uv run pytest && uv run pytest -m network -q`
Expected: `192 passed, 6 deselected` + `8 passed`

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
| M1 语料层 | D3 | `Source` 抽象（llms_txt + local_dir）可用；两源 ≥400 篇 `.md`（实测 774）；**每源一份 manifest**，增量更新（先插后删，含崩溃测试）可运行且跨源幂等；**非 markdown 页面按 `Content-Type` 拒收并记入失败清单**；抓取报告输出含失败清单与 `dated`/`draft`/`unknown` 三分项；**被纳入索引的 MCP 页面版本标注率 ≥90%**（实测 252 篇 → 100%：198 日期 + 54 draft） |
```

- [ ] **Step 3: README 增加 Progress 小节**

> **2026-09-22 修正：README 里已经有一个 `## Progress` 小节**（在 `## Stack` 之后），本节原本要求在
> `## Approach` 之前**插入**一个新小节——那会变成两个 Progress。改为**就地更新已有的那个**：
> 把 Corpus pipeline 那一项勾上并写成 M1 的名字，随后补一行语料现状。
> 下面这段代码块保留为「要表达的内容」的记录，不是逐字粘贴的对象。

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
LangChain Python 522 篇（无版本，语料性质），合计 774 篇。
另有 17 条上游失败被如实记入抓取报告：16 条站点以 `text/html` 返回、1 条 404。
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
