"""05 §8 の信頼境界をテストで固定する。"""

import http.client
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import quote, unquote

from helpers import BIN_KG, FIXTURES, LIB, clean_env, run_kg  # noqa: F401
from kgwiki import layers, serve


class TestPathTraversal(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "global"
        shutil.copytree(FIXTURES / "wiki-mini" / "global", self.root)
        self.assertEqual(run_kg(["build"], root=self.root).returncode, 0)
        (self.tmp / "secret.md").write_text("SECRET", encoding="utf-8")
        self.ctx = serve.ViewContext(
            layer_list=[layers.Layer(layers.GLOBAL, self.root)], topics=None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def get(self, path):
        return serve.route("GET", path, {}, self.ctx)

    def test_dotdot_in_path_never_reads_outside_root(self):
        for path in ("/p/../../secret", "/p/llm/../../../secret",
                     "/p/llm/concepts/../../../../secret"):
            r = self.get(path)
            self.assertIn(r.status, (400, 404), path)
            self.assertNotIn("SECRET", r.body.decode("utf-8"), path)

    def test_decoded_dotdot_is_rejected(self):
        """アダプタは unquote 後に route へ渡すため、デコード後の値で検証する。"""
        r = self.get("/p/llm/concepts/../../../secret")
        self.assertIn(r.status, (400, 404))

    def test_uppercase_and_symbols_in_slug_are_rejected(self):
        for path in ("/p/llm/concepts/RAG", "/p/llm/concepts/a b",
                     "/p/llm/concepts/a.md"):
            self.assertEqual(self.get(path).status, 400, path)

    def test_percent_encoded_dotdot_is_rejected_after_decode(self):
        """run_server は unquote(parsed.path) を route() に渡す契約（05 §6）。

        ここでは実サーバを起動せず、その契約を模して %2e%2e%2f を unquote した
        値を route() に渡し、デコード後もパストラバーサルが成立しないことを
        固定する。
        """
        for raw in ("/p/%2e%2e%2f%2e%2e%2fsecret",
                    "/p/llm/concepts/%2e%2e%2f%2e%2e%2f%2e%2e%2fsecret"):
            decoded = unquote(raw)
            r = self.get(decoded)
            self.assertIn(r.status, (400, 404), raw)
            self.assertNotIn("SECRET", r.body.decode("utf-8"), raw)

    def test_malformed_percent_encoding_does_not_crash_route(self):
        """不正なパーセントエンコード（%FF%FE 等）が route() を落とさないこと。

        urllib.parse.unquote は既定で errors="replace" のため例外は出ないはず
        だが、adapter の契約（unquote してから渡す）を模して固定する。
        """
        for raw in ("/p/%FF%FE", "/p/llm/concepts/%FF",
                    "/p/llm/concepts/rag%00"):
            decoded = unquote(raw)
            r = self.get(decoded)  # 例外を投げないこと自体が検証対象
            self.assertIn(r.status, (400, 404), raw)


class TestResponseHardening(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "global"
        shutil.copytree(FIXTURES / "wiki-mini" / "global", self.root)
        self.assertEqual(run_kg(["build"], root=self.root).returncode, 0)
        self.ctx = serve.ViewContext(
            layer_list=[layers.Layer(layers.GLOBAL, self.root)], topics=None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_cors_headers(self):
        r = serve.route("GET", "/", {}, self.ctx)
        keys = {k.lower() for k in r.headers}
        self.assertNotIn("access-control-allow-origin", keys)

    def test_query_is_escaped_in_search_page(self):
        r = serve.route("GET", "/search", {"q": ['<script>alert(1)</script>']},
                        self.ctx)
        body = r.body.decode("utf-8")
        self.assertNotIn("<script>alert(1)</script>", body)

    def test_all_methods_other_than_get_are_405(self):
        for method in ("POST", "PUT", "DELETE", "PATCH", "HEAD"):
            self.assertEqual(serve.route(method, "/", {}, self.ctx).status, 405)

    def test_search_redirect_location_is_fixed_regardless_of_query(self):
        """検索クエリの値が Location ヘッダへ反映される経路がないこと（ヘッダ

        インジェクション対策）。/search?q= が空/空白のみのときの Location は
        常に固定文字列 "/" であり、クエリの中身が反映されない
        （q.strip() が空文字になる CRLF・空白のみの値で確認する）。
        """
        for q in ("", "   ", "\r\n", "\n\r  \t"):
            r = serve.route("GET", "/search", {"q": [q]}, self.ctx)
            self.assertEqual(r.status, 302, repr(q))
            self.assertEqual(r.headers["Location"], "/", repr(q))

    def test_search_query_with_embedded_crlf_is_not_redirected(self):
        """strip() 後に非空となる CRLF 混じりのクエリは検索結果 200 になり、

        Location ヘッダそのものが存在しないこと（=注入の余地がないこと）。
        """
        r = serve.route("GET", "/search", {"q": ["\r\nX-Injected: yes"]}, self.ctx)
        self.assertEqual(r.status, 200)
        self.assertNotIn("Location", r.headers)


class TestContentLengthByteAccuracy(unittest.TestCase):
    """Content-Length は run_server 側で len(response.body)（バイト列）から

    計算される（05 §6）。response.body が bytes であり、マルチバイト文字を
    含む本文で文字数とバイト数が食い違うことを固定し、この不変条件が崩れて
    いないことを検証する。
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "global"
        shutil.copytree(FIXTURES / "wiki-mini" / "global", self.root)
        self.assertEqual(run_kg(["build"], root=self.root).returncode, 0)
        self.ctx = serve.ViewContext(
            layer_list=[layers.Layer(layers.GLOBAL, self.root)], topics=None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_page_body_is_bytes_and_multibyte_safe(self):
        r = serve.route("GET", "/p/llm/concepts/rag", {}, self.ctx)
        self.assertEqual(r.status, 200)
        self.assertIsInstance(r.body, bytes)
        text = r.body.decode("utf-8")
        self.assertGreater(len(text), 0)
        # 日本語（マルチバイト UTF-8）を含む本文であること（前提の確認）。
        self.assertTrue(any(ord(c) > 127 for c in text))
        # Content-Length に使われるのはバイト数（run_server: len(body)）であり、
        # 文字数と一致しないことを確認する。
        self.assertNotEqual(len(r.body), len(text))


def _read_line_with_timeout(stream, timeout=5.0):
    """stream.readline() をタイムアウト付きで行う（ハング防止）。"""
    ready, _, _ = select.select([stream], [], [], timeout)
    if not ready:
        return None
    return stream.readline()


def _stop_server(proc, timeout=5.0):
    """SIGINT を送って停止させ、returncode を返す（テストをハングさせない）。

    バックグラウンドのシェルジョブへの `kill -INT` は非対話 bash では効かない
    ため、subprocess.Popen で直接起動したプロセスに対して send_signal する。
    """
    if proc.poll() is None:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=timeout)
    for stream in (proc.stdout, proc.stderr):
        if stream is not None:
            stream.close()
    return proc.returncode


class TestServerAdversarialInput(unittest.TestCase):
    """実サーバでのみ検証できる性質（05 §8 の追加観点）。

    ヘッダインジェクション・巨大入力・不正パーセントエンコードは
    BaseHTTPRequestHandler / ソケット層を経由して初めて検証できるため、
    このクラスに限り実サーバを起動する。全ての接続に短いタイムアウトを
    設定し、停止は send_signal(SIGINT) + timeout 付き wait で確実に行う。
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.root = cls.tmp / "global"
        shutil.copytree(FIXTURES / "wiki-mini" / "global", cls.root)
        result = run_kg(["build"], root=cls.root)
        if result.returncode != 0:
            shutil.rmtree(cls.tmp, ignore_errors=True)
            raise RuntimeError("fixture build failed: %s" % result.stderr)
        cls.proc = subprocess.Popen(
            [sys.executable, str(BIN_KG), "serve", "--root", str(cls.root),
             "--port", "0", "--quiet"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=clean_env(cls.root))
        line = _read_line_with_timeout(cls.proc.stderr, 5.0)
        if line is None:
            _stop_server(cls.proc)
            shutil.rmtree(cls.tmp, ignore_errors=True)
            raise RuntimeError("サーバがタイムアウト内に応答しなかった")
        m = re.search(r":(\d+)/", line)
        if m is None:
            _stop_server(cls.proc)
            shutil.rmtree(cls.tmp, ignore_errors=True)
            raise RuntimeError("待ち受け URL からポート番号を抽出できない: %r" % line)
        cls.port = int(m.group(1))

    @classmethod
    def tearDownClass(cls):
        _stop_server(cls.proc)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _get(self, path, timeout=10.0):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            conn.request("GET", path)
            r = conn.getresponse()
            body = r.read()
            return r.status, body, dict(r.getheaders())
        finally:
            conn.close()

    def test_huge_path_does_not_hang(self):
        """観点2: 10 万文字の URL パスでサーバが固まらないこと。"""
        start = time.time()
        status, _body, _headers = self._get("/p/" + "a" * 100000, timeout=10.0)
        self.assertLess(time.time() - start, 10.0, "巨大なパスでハングした")
        self.assertIn(status, (400, 404, 414), status)

    def test_huge_query_does_not_hang(self):
        """観点2: 巨大なクエリ文字列でサーバが固まらず、その後も生存すること。"""
        start = time.time()
        try:
            self._get("/search?q=" + "a" * 500000, timeout=10.0)
        except (http.client.HTTPException, OSError):
            pass  # ソケット層で切断されるのは許容。ハングしないことのみ確認する。
        self.assertLess(time.time() - start, 10.0, "巨大なクエリでハングした")
        status, _body, _headers = self._get("/")
        self.assertEqual(status, 200, "巨大なクエリ処理後もサーバが生存していること")

    def test_malformed_percent_encoding_does_not_500_or_crash(self):
        """観点3: 不正なパーセントエンコードで 500 やプロセスクラッシュが

        起きないこと。
        """
        for path in ("/p/%FF%FE", "/%C0%AF", "/p/llm/concepts/rag%00"):
            status, _body, _headers = self._get(path)
            self.assertNotEqual(status, 500, path)
        status, _body, _headers = self._get("/")
        self.assertEqual(status, 200, "不正エンコード処理後もサーバが生存していること")

    def test_header_injection_via_query_is_not_reflected(self):
        """観点1: クエリに含めた CRLF が応答ヘッダへ反映されないこと。"""
        injected = quote("\r\nX-Injected: yes")
        status, _body, headers = self._get("/search?q=" + injected)
        self.assertNotIn("X-Injected", headers)
        # 空でないクエリなので、302 リダイレクトにはならず検索結果 200 になる。
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
