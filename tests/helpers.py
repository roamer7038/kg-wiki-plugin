"""テスト共通ヘルパー。"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
BIN_KG = PLUGIN_ROOT / "bin" / "kg"
FIXTURES = PLUGIN_ROOT / "tests" / "fixtures"
LIB = PLUGIN_ROOT / "lib"

sys.path.insert(0, str(LIB))


def clean_env(project_dir=None):
    """kg の層解決に影響する環境変数を隔離した env を返す。"""
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("CLAUDE_PLUGIN_OPTION_") or key == "KG_WIKI_ROOT":
            del env[key]
    # CLAUDE_PROJECT_DIR を必ず固定し、実行環境のプロジェクト層を拾わない
    env["CLAUDE_PROJECT_DIR"] = str(project_dir) if project_dir else tempfile.gettempdir()
    return env


def run_kg(args, root=None, project_dir=None, cwd=None, env=None):
    """bin/kg をサブプロセス実行する。"""
    cmd = [sys.executable, str(BIN_KG)] + list(args)
    if root is not None:
        cmd += ["--root", str(root)]
    return subprocess.run(
        cmd, capture_output=True, text=True, cwd=cwd,
        env=env if env is not None else clean_env(project_dir),
    )


def copy_fixture(name: str, dest: Path) -> Path:
    src = FIXTURES / name
    dest = Path(dest) / name
    shutil.copytree(src, dest)
    return dest


def tree_bytes(root: Path) -> dict:
    """ディレクトリ全体の {相対パス: バイト列}（冪等性のバイト一致検証用）。"""
    result = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_file():
            result[str(path.relative_to(root))] = path.read_bytes()
    return result
