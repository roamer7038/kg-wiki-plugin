"""qmd 委譲ファサード（02 §2.3・§4.2、03 §4.11、04 §8）。

qmd 固有の概念（コレクション・チャンク・sqlite index）は本モジュール外に出さない
（A-9）。サブプロセスは常に引数配列で起動する（NFR-6）。

【注意】qmd のコマンド体系・JSON フィールド名は 04 §8.4 の想定値であり、
実機確認までは仮（_CMD_* 定数と map_results のフィールド参照に隔離してある）。
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import config as config_mod
from . import refs
from .errors import FeatureDisabledError, KgError
from .layers import GLOBAL

# プラグイン同梱の動作確認済みバージョンレンジ（03 §2.2）。
# 空 = 実機確認未了（kg init --with-qmd は検出した実バージョンを記録する）。
VERIFIED_VERSION_RANGE = ""

# 04 §8.4 の想定コマンド体系（実機確認までは仮）
_CMD_VSEARCH = "vsearch"
_CMD_HYBRID = "query"
_CMD_UPDATE = "update"


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
    """qmd の実バージョン。取得できなければ None。"""
    path = qmd_path()
    if path is None:
        return None
    try:
        proc = subprocess.run([path, "--version"], capture_output=True, text=True,
                              timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def _run_json(args_list):
    proc = subprocess.run([qmd_path()] + args_list, capture_output=True, text=True)
    if proc.returncode != 0:
        raise KgError(f"qmd の実行失敗（exit {proc.returncode}）: "
                      f"{proc.stderr.strip()}")
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        raise KgError("qmd の出力を JSON として解釈できない") from None
    return data


def map_results(items, layer_roots):
    """チャンク結果 → ref への決定論的写像・重複排除（04 §8.3）。

    items: qmd の返却順（= ランク順）の [{"path": ..., "score": ...}]。
    layer_roots: [(kind, root_path)]。
    返り値: (mapped, unmapped)。mapped = [(score, ref, kind)] を
    「重複排除後の最良ランクの返却順（同点 ref 昇順）」で返す。
    """
    resolved = [(kind, Path(root).resolve()) for kind, root in layer_roots]
    best = {}  # ref -> [rank, score, kind]
    unmapped = []
    for rank, item in enumerate(items):
        path = item.get("path")
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
    subcmd = _CMD_VSEARCH if mode == "vsearch" else _CMD_HYBRID
    merged = {}  # ref -> (score, kind)  プロジェクト層優先・最高スコア
    order = []
    for layer in layer_list:
        items = _run_json([subcmd, query, "--json", "--collection",
                           collection_name(layer), "--limit", str(limit)])
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


def sync(root) -> None:
    """kg build ステップ (6): qmd 側 index の同期（02 §4）。失敗は例外（呼び出し側で警告化）。"""
    proc = subprocess.run([qmd_path(), _CMD_UPDATE], capture_output=True, text=True)
    if proc.returncode != 0:
        raise KgError(f"qmd update 失敗（exit {proc.returncode}）: {proc.stderr.strip()}")
