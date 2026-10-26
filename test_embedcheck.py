"""embedcheck —— 自检测试。

比对向量库中的条目与来源文件，标出内容已变、已删或重复入库的条目。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import embedcheck  # noqa: E402


class TestEmbedCheck(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.docs = os.path.join(self.tmpdir, "docs")
        os.makedirs(self.docs)
        with open(os.path.join(self.docs, "a.md"), "w", encoding="utf-8") as f:
            f.write("原始内容。")
        with open(os.path.join(self.docs, "b.md"), "w", encoding="utf-8") as f:
            f.write("另一个文件的内容。")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_orphaned_source_detected(self):
        store = [{"id": "x#1", "content": "原始内容。", "source": "gone.md"}]
        sources = {k: v for k, v in
                   embedcheck.load_sources(self.docs).items()}
        r = embedcheck.check(store, sources, "id", "content", "source")
        self.assertEqual(r["summary"]["orphaned_count"], 1)

    def test_changed_content_detected(self):
        store = [{"id": "x#1", "content": "旧的内容。", "source": "a.md"}]
        sources = embedcheck.load_sources(self.docs)
        r = embedcheck.check(store, sources, "id", "content", "source")
        self.assertEqual(r["summary"]["changed_count"], 1)

    def test_in_sync_store(self):
        store = [{"id": "x#1", "content": "原始内容。", "source": "a.md"}]
        sources = embedcheck.load_sources(self.docs)
        r = embedcheck.check(store, sources, "id", "content", "source")
        self.assertEqual(r["in_sync"], 0)

    def test_duplicate_ingestion_detected(self):
        store = [{"id": "x#1", "content": "原始内容。", "source": "a.md"},
                 {"id": "x#2", "content": "原始内容。", "source": "a.md"}]
        sources = embedcheck.load_sources(self.docs)
        r = embedcheck.check(store, sources, "id", "content", "source")
        self.assertEqual(r["summary"]["duplicate_source_count"], 1)

    def test_punctuation_only_change_is_not_content_change(self):
        """防呆：只改标点不算内容变了。"""
        store = [{"id": "x#1", "content": "原始 内容", "source": "a.md"}]
        sources = embedcheck.load_sources(self.docs)
        r = embedcheck.check(store, sources, "id", "content", "source")
        self.assertEqual(r["summary"]["changed_count"], 0)
