"""refs / hashing / fsio の unit test。"""

import hashlib
import tempfile
import unittest
from pathlib import Path

from helpers import LIB  # noqa: F401
from kgwiki import fsio, hashing, refs
from kgwiki.errors import LockError, RefFormatError


class TestRefs(unittest.TestCase):
    def test_canonical(self):
        r = refs.parse_ref("llm/concepts/graphrag")
        self.assertEqual((r.topic, r.type, r.slug), ("llm", "concepts", "graphrag"))
        self.assertEqual(str(r), "llm/concepts/graphrag")

    def test_non_canonical(self):
        for bad in ("concepts/rag", "topics/llm/concepts/rag", "llm/concepts/RAG",
                    "llm/concepts/日本語", "llm//rag", "llm/concepts/rag/extra",
                    "llm/concepts/a_b"):
            self.assertFalse(refs.is_canonical(bad), bad)
            with self.assertRaises(RefFormatError):
                refs.parse_ref(bad)


class TestHashing(unittest.TestCase):
    def test_page_hash_is_raw_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.md"
            path.write_bytes("こんにちは\n".encode("utf-8"))
            expected = hashlib.sha256("こんにちは\n".encode("utf-8")).hexdigest()
            self.assertEqual(hashing.page_hash(path), f"sha256:{expected}")

    def test_set_hash_definition(self):
        # <ref>\t<hex64>（プレフィクスなし）を ref 昇順・LF 連結（末尾改行なし）
        h1 = "a" * 64
        h2 = "b" * 64
        pages = {"llm/concepts/b": f"sha256:{h2}", "llm/concepts/a": f"sha256:{h1}"}
        joined = f"llm/concepts/a\t{h1}\nllm/concepts/b\t{h2}".encode("utf-8")
        expected = hashlib.sha256(joined).hexdigest()
        self.assertEqual(hashing.set_hash(pages), f"sha256:{expected}")

    def test_set_hash_empty(self):
        expected = hashlib.sha256(b"").hexdigest()
        self.assertEqual(hashing.set_hash({}), f"sha256:{expected}")


class TestFsio(unittest.TestCase):
    def test_atomic_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "f.txt"
            fsio.atomic_write_text(path, "内容")
            self.assertEqual(path.read_text(encoding="utf-8"), "内容")
            leftovers = [p for p in path.parent.iterdir() if p.name != "f.txt"]
            self.assertEqual(leftovers, [])  # tmp ファイルが残らない

    def test_lock_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            with fsio.RootLock(Path(tmp), "build"):
                with self.assertRaises(LockError):
                    fsio.RootLock(Path(tmp), "move").acquire()
            # 解放後は再取得できる
            lock = fsio.RootLock(Path(tmp), "new").acquire()
            lock.release()
            self.assertFalse((Path(tmp) / ".kg-lock").exists())


if __name__ == "__main__":
    unittest.main()
