"""qmd 委譲ファサード（02 §2.3・§4.2、03 §4.11、04 §8）。

qmd 固有の概念（コレクション・チャンク・sqlite index）は本モジュール外に出さない
（A-9）。サブプロセスは常に引数配列で起動する（NFR-6）。

コマンド体系・JSON 形式は qmd 2.5.3 で実機確認済み（04 §8.4 の消化）:
  - 検索: `qmd vsearch|query <q> --json --full-path -n <N> -c <collection>`
    stdout = JSON 配列（フィールド: score / file / line / title / snippet）。
    進捗・クエリ拡張の表示は stderr。
  - 同期: `qmd update`（再インデックス）+ `qmd embed`（不足ベクトルの生成。
    差分が無ければ両者とも 0.1 秒程度）
  - コレクション登録: `qmd collection add <path> --name <n> --mask <glob>`
  - バージョン: `qmd --version` → 例 "qmd 2.5.3 (89bdede)"
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import config as config_mod
from . import refs
from .errors import FeatureDisabledError, KgError
from .layers import GLOBAL

# プラグイン同梱の動作確認済みバージョンレンジ（03 §2.2。2026-07-13 に 2.5.3 で確認）
VERIFIED_VERSION_RANGE = "2.5"

# pages/ 配下の Markdown のみをインデックスする（_derived 等を除外）
COLLECTION_MASK = "topics/*/pages/**/*.md"
VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")


def qmd_path():
    return shutil.which("qmd")


def collection_name(layer) -> str:
    """コレクション命名（04 §8.2）。プロジェクト root = .kg-wiki の親と解釈する。"""
    if layer.kind == GLOBAL:
        return "kgwiki-global"
    project_root = Path(layer.root).resolve().parent
    digest = hashlib.sha256(str(project_root).encode("utf-8")).hexdigest()[:8]
    return f"kgwiki-{digest}"


def enabled_by_config(layer_list) -> bool:
    """設定値の解決（02 §2.3: 環境変数 > config.yml > 既定 false）。

    複数層選択時はいずれかの層の config が有効なら有効とみなす。
    """
    env = os.environ.get("CLAUDE_PLUGIN_OPTION_ENABLE_QMD")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    for layer in layer_list:
        cfg, _issues, _exists = config_mod.load_config(layer.root)
        if cfg is not None and cfg.qmd_enabled:
            return True
    return False


def require_enabled(layer_list) -> None:
    """有効化条件の AND 検査（02 §2.3）。欠ける場合 FeatureDisabledError（exit 4）。"""
    if not enabled_by_config(layer_list):
        raise FeatureDisabledError(
            "qmd 連携が無効。有効化: kg init --with-qmd（config の qmd.enabled: true）"
            "または環境変数 CLAUDE_PLUGIN_OPTION_ENABLE_QMD=true")
    if qmd_path() is None:
        raise FeatureDisabledError(
            "qmd が PATH に見つからない。導入: npm install -g @tobilu/qmd（Node.js 22+）")


def version():
    """qmd の実バージョン（semver 部分のみ）。取得できなければ None。"""
    path = qmd_path()
    if path is None:
        return None
    try:
        proc = subprocess.run([path, "--version"], capture_output=True, text=True,
                              timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    match = VERSION_RE.search(proc.stdout)
    return match.group(1) if match else None


def _run(args_list, timeout=None):
    proc = subprocess.run([qmd_path()] + args_list, capture_output=True, text=True,
                          timeout=timeout)
    if proc.returncode != 0:
        raise KgError(f"qmd の実行失敗（exit {proc.returncode}）: "
                      f"{proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else ''}")
    return proc.stdout


def _run_json(args_list):
    stdout = _run(args_list)
    try:
        return json.loads(stdout)
    except ValueError:
        # 防御: 進捗行等が stdout に混入した場合は JSON 配列の開始から読む
        start = stdout.find("[")
        if start >= 0:
            try:
                return json.loads(stdout[start:])
            except ValueError:
                pass
        raise KgError("qmd の出力を JSON として解釈できない") from None


def map_results(items, layer_roots):
    """チャンク結果 → ref への決定論的写像・重複排除（04 §8.3）。

    items: qmd の返却順（= ランク順）の [{"file": ..., "score": ...}]。
    layer_roots: [(kind, root_path)]。
    返り値: (mapped, unmapped)。mapped = [(score, ref, kind)] を
    「重複排除後の最良ランクの返却順（同点 ref 昇順）」で返す。
    """
    resolved = [(kind, Path(root).resolve()) for kind, root in layer_roots]
    best = {}  # ref -> [rank, score, kind]
    unmapped = []
    for rank, item in enumerate(items):
        path = item.get("file")
        score = item.get("score")
        if not isinstance(path, str) or not isinstance(score, (int, float)):
            unmapped.append(repr(item))
            continue
        real = Path(path).resolve()
        ref = None
        kind = None
        for k, root in resolved:
            try:
                parts = real.relative_to(root).parts
            except ValueError:
                continue
            if (len(parts) == 5 and parts[0] == "topics" and parts[2] == "pages"
                    and parts[4].endswith(".md")):
                candidate = f"{parts[1]}/{parts[3]}/{parts[4][:-3]}"
                if refs.is_canonical(candidate):
                    ref = candidate
                    kind = k
                    break
        if ref is None:
            unmapped.append(path)  # パターン外は破棄（stderr 診断は呼び出し側）
            continue
        if ref not in best:
            best[ref] = [rank, float(score), kind]
        else:
            best[ref][1] = max(best[ref][1], float(score))  # 最高スコアに重複排除
    mapped = [(entry[1], ref, entry[2]) for ref, entry in best.items()]
    mapped.sort(key=lambda r: (best[r[1]][0], r[1]))  # 最良ランク順 → ref 昇順
    return mapped, unmapped


def search(mode: str, query: str, layer_list, topics, limit: int):
    """vsearch / hybrid の委譲実行（03 §4.11）。[(score, ref, kind)] を返す。"""
    import sys

    subcmd = "vsearch" if mode == "vsearch" else "query"
    merged = {}  # ref -> (score, kind)  プロジェクト層優先・最高スコア
    order = []
    for layer in layer_list:
        items = _run_json([subcmd, query, "--json", "--full-path",
                           "-n", str(limit), "-c", collection_name(layer)])
        if not isinstance(items, list):
            raise KgError("qmd の JSON 出力が配列でない")
        mapped, unmapped = map_results(items, [(layer.kind, layer.root)])
        for path in unmapped:
            print(f"kg {mode}: qmd 結果を ref に写像できない: {path}",
                  file=sys.stderr)
        for score, ref, kind in mapped:
            if topics is not None and ref.split("/")[0] not in topics:
                continue
            if ref not in merged:
                order.append(ref)
                merged[ref] = (score, kind)
            else:
                prev_score, _prev_kind = merged[ref]
                merged[ref] = (max(prev_score, score), kind)  # 後の層（project）優先
    results = [(merged[ref][0], ref, merged[ref][1]) for ref in order]
    results.sort(key=lambda r: (-r[0], r[1]))  # 層統合後はスコア降順 → ref 昇順
    return results[:limit]


def register_collection(layer) -> str:
    """コレクション登録（kg init --with-qmd）。

    同名コレクションが既に同じパスを指していれば何もしない。別パスを指している
    場合（wiki_root の変更等）は付け替える。
    """
    name = collection_name(layer)
    root = str(Path(layer.root).resolve())
    try:
        show = _run(["collection", "show", name])
    except KgError:
        show = ""  # 不在（qmd は exit 1 を返す）
    match = re.search(r"^\s*Path:\s*(.+)$", show, re.MULTILINE)
    if match:
        if str(Path(match.group(1).strip()).resolve()) == root:
            return name
        _run(["collection", "remove", name])  # 別パスの既存を付け替える
    _run(["collection", "add", root, "--name", name, "--mask", COLLECTION_MASK])
    return name


def sync(root) -> None:
    """kg build ステップ (6): qmd 側 index の同期 + 不足ベクトルの生成（02 §4）。

    失敗は例外（呼び出し側で警告化し exit 0 を維持する）。差分なしなら合計 0.2 秒程度。
    """
    _run(["update"])
    _run(["embed"])
