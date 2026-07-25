"""kg serve の CLI 契約（05 §2.1）。サーバは起動せず引数検証のみを見る。"""

import errno
import re
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import BIN_KG, FIXTURES, LIB, clean_env, run_kg  # noqa: F401


def _read_line_with_timeout(stream, timeout=5.0):
    """stream.readline() をタイムアウト付きで行う（ハング防止）。"""
    ready, _, _ = select.select([stream], [], [], timeout)
    if not ready:
        return None
    return stream.readline()


def _stop_server(proc, timeout=5.0):
    """SIGINT を送って停止させ、returncode を返す（テストをハングさせない）。

    バックグラウンドのシェルジョブへの `kill -INT` は非対話 bash では効かない
    （SIGINT の disposition が SIG_IGN のまま継承される）ため、
    subprocess.Popen で直接起動したプロセスに対して send_signal する。
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


class TestServeArgs(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "global"
        shutil.copytree(FIXTURES / "wiki-mini" / "global", self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_non_loopback_host_is_usage_error(self):
        r = run_kg(["serve", "--host", "0.0.0.0"], root=self.root)
        self.assertEqual(r.returncode, 3)
        self.assertIn("ループバック", r.stderr)

    def test_public_ip_host_is_usage_error(self):
        r = run_kg(["serve", "--host", "192.168.1.10"], root=self.root)
        self.assertEqual(r.returncode, 3)

    def test_localhost_is_accepted_as_loopback(self):
        """--host localhost が実際に受理され、サーバが起動することを検証する。

        （旧テストは `--json` が serve パーサに未定義で argparse が host の値に
        関わらず同じ exit 3 を返すだけだったため、host の受理を検証できていな
        かった。ここでは実際に待ち受けさせ、起動行が出ることを見る。）
        """
        proc = subprocess.Popen(
            [sys.executable, str(BIN_KG), "serve", "--root", str(self.root),
             "--host", "localhost", "--port", "0", "--quiet"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=clean_env(self.root))
        try:
            line = _read_line_with_timeout(proc.stderr, 5.0)
            self.assertIsNotNone(line, "サーバがタイムアウト内に応答しなかった")
            self.assertNotIn("ループバック", line)
            self.assertIn("待ち受け中", line)
        finally:
            self.assertEqual(_stop_server(proc), 0)

    def test_ipv6_loopback_actually_binds(self):
        """--host ::1 が実際に IPv6 で待ち受けられることを検証する。

        LOOPBACK_HOSTS は "::1" を受理するが、HTTPServer は
        address_family = socket.AF_INET 固定のため、IPv6 に切り替えないと
        必ずバインドに失敗する（レビュー指摘）。この環境で IPv6 ループバック
        自体が使えない場合は skip する。
        """
        probe = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        try:
            probe.bind(("::1", 0))
        except OSError as e:
            probe.close()
            self.skipTest("この環境では IPv6 ループバックが使えない: %s" % e)
        probe.close()

        proc = subprocess.Popen(
            [sys.executable, str(BIN_KG), "serve", "--root", str(self.root),
             "--host", "::1", "--port", "0", "--quiet"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=clean_env(self.root))
        try:
            line = _read_line_with_timeout(proc.stderr, 5.0)
            self.assertIsNotNone(line, "サーバがタイムアウト内に応答しなかった")
            self.assertIn("[::1]", line)
            self.assertIn("待ち受け中", line)
        finally:
            self.assertEqual(_stop_server(proc), 0)

    def test_all_non_get_methods_return_405_over_http(self):
        """05 §3.1: GET 以外は 405。

        route() は全非 GET を 405 にするが、HTTP アダプタが do_GET/do_POST
        しか定義しないと、PUT/DELETE/OPTIONS 等は http.server 既定の 501 に
        なり route() に届かない（統合バグ）。実サーバに投げて 405 を確認する。
        """
        import http.client
        proc = subprocess.Popen(
            [sys.executable, str(BIN_KG), "serve", "--root", str(self.root),
             "--host", "127.0.0.1", "--port", "0", "--quiet"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=clean_env(self.root))
        try:
            line = _read_line_with_timeout(proc.stderr, 5.0)
            self.assertIsNotNone(line, "サーバがタイムアウト内に応答しなかった")
            port = int(re.search(r":(\d+)/", line).group(1))
            for method in ("POST", "PUT", "DELETE", "OPTIONS", "PATCH"):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request(method, "/")
                status = conn.getresponse().status
                conn.close()
                self.assertEqual(status, 405, "%s は 405 であること" % method)
        finally:
            self.assertEqual(_stop_server(proc), 0)

    def test_bind_failure_on_port_in_use_advises_port_flag(self):
        """ポート使用中（EADDRINUSE）のときだけ --port の案内を出す。"""
        proc = subprocess.Popen(
            [sys.executable, str(BIN_KG), "serve", "--root", str(self.root),
             "--port", "0", "--quiet"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=clean_env(self.root))
        try:
            line = _read_line_with_timeout(proc.stderr, 5.0)
            self.assertIsNotNone(line, "サーバがタイムアウト内に応答しなかった")
            m = re.search(r":(\d+)/", line)
            self.assertIsNotNone(m, "待ち受け URL からポート番号を抽出できない: %r" % line)
            port = int(m.group(1))

            r = run_kg(["serve", "--port", str(port), "--quiet"], root=self.root)
            self.assertEqual(r.returncode, 1)
            self.assertIn("--port で別のポートを指定すること", r.stderr)
        finally:
            self.assertEqual(_stop_server(proc), 0)

    def test_bind_failure_other_than_port_in_use_does_not_advise_port_flag(self):
        """EADDRINUSE 以外の原因では --port の案内を出さない（誤誘導しない）。

        非特権ユーザは通常 1024 未満のポートへバインドできない（EACCES）ため、
        これを EADDRINUSE 以外の原因として使う。この環境で事情が異なる場合は
        skip する。
        """
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", 80))
        except OSError as e:
            probe.close()
            if e.errno != errno.EACCES:
                self.skipTest(
                    "この環境ではポート 80 が想定外の理由で失敗する: %s" % e)
        else:
            probe.close()
            self.skipTest("この環境では非特権ユーザでもポート 80 へバインドできる")

        r = run_kg(["serve", "--port", "80", "--quiet"], root=self.root)
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("--port で別のポートを指定すること", r.stderr)

    def test_json_option_is_rejected_by_argparse(self):
        """--json は serve パーサに未定義なので argparse が unrecognized arguments で弾く。"""
        r = run_kg(["serve", "--json"], root=self.root)
        self.assertEqual(r.returncode, 3)

    def test_limit_option_is_rejected_by_argparse(self):
        """--limit は serve パーサに未定義なので argparse が unrecognized arguments で弾く。"""
        r = run_kg(["serve", "--limit", "5"], root=self.root)
        self.assertEqual(r.returncode, 3)

    def test_date_option_is_rejected_by_argparse(self):
        """--date は serve パーサに未定義なので argparse が unrecognized arguments で弾く。"""
        r = run_kg(["serve", "--date", "2026-07-24"], root=self.root)
        self.assertEqual(r.returncode, 3)

    def test_help_lists_serve(self):
        r = run_kg(["--help"])
        self.assertIn("serve", r.stdout)


class TestServeUnexpectedException(unittest.TestCase):
    """route() が想定外の例外を投げたときに 500 へ変換されることを検証する（05 §3.6）。

    実サーバを起動せず、serve.route をモンキーパッチして serve._safe_route を
    直接呼ぶ（HTTP アダプタの薄いラッパ経由の挙動を、ソケットなしで確認する）。
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "global"
        shutil.copytree(FIXTURES / "wiki-mini" / "global", self.root)
        sys.path.insert(0, str(LIB))
        from kgwiki import layers, serve
        self.serve = serve
        self.ctx = serve.ViewContext(
            layer_list=[layers.Layer(layers.GLOBAL, self.root)], topics=None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unexpected_exception_becomes_500_without_leaking_details(self):
        secret = "SECRET-DETAIL-should-not-leak-42"

        def boom(method, path, query, ctx):
            raise RuntimeError(secret)

        original_route = self.serve.route
        self.serve.route = boom
        try:
            response = self.serve._safe_route("GET", "/", {}, self.ctx)
        finally:
            self.serve.route = original_route

        self.assertEqual(response.status, 500)
        body = response.body.decode("utf-8", errors="replace")
        self.assertNotIn(secret, body)
        self.assertNotIn("RuntimeError", body)
        self.assertNotIn("Traceback", body)

    def test_route_still_works_after_a_previous_exception(self):
        """500 を返した後もサーバ（route 経由の処理）は動き続ける。"""

        def boom(method, path, query, ctx):
            raise RuntimeError("boom")

        original_route = self.serve.route
        self.serve.route = boom
        try:
            first = self.serve._safe_route("GET", "/", {}, self.ctx)
        finally:
            self.serve.route = original_route
        self.assertEqual(first.status, 500)

        second = self.serve._safe_route("GET", "/", {}, self.ctx)
        self.assertEqual(second.status, 200)


if __name__ == "__main__":
    unittest.main()
