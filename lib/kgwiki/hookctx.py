"""kg hook-context: UserPromptSubmit hook への軽量注入。

hook 経路の規約: **常に exit 0**。無効化・0 件・内部エラー・500ms 超過のいずれでも
空出力で正常終了する（部分結果は返さない）。プロンプトは stdin の hook JSON からのみ
読み（未検証文字列を引数化しない）、出力には信頼境界の注意書きを付す。

注入の有効/無効は環境変数 `KG_WIKI_HOOK_CONTEXT` のみで判定する。
未設定時は既定の有効とする。
"""

import json
import os
import re
import time

from . import layers as layers_mod
from . import output
from . import pages as pages_mod
from . import search as search_mod

ENV_ENABLE = "KG_WIKI_HOOK_CONTEXT"
BUDGET_SEC = 0.5   # 自己打ち切り（hook timeout に依存しない一次防衛）
MAX_TERMS = 8      # 先頭 8 項で打ち切る
LIMIT = 5          # ポインタは最大 5 件
TRUE_VALUES = ("1", "true", "yes", "on")

# 英数字 3 文字以上、または CJK 2 文字以上の run（CJK 判定は search と同じブロック）
_CJK = "".join(f"\\u{lo:04x}-\\u{hi:04x}" for lo, hi in search_mod.CJK_RANGES)
TERM_RE = re.compile(f"[0-9a-z]{{3,}}|[{_CJK}]{{2,}}")


def enabled(env=None) -> bool:
    """hook 注入の有効判定。未設定は既定の有効。"""
    env = os.environ if env is None else env
    value = env.get(ENV_ENABLE)
    if value is None:
        return True
    return value.strip().lower() in TRUE_VALUES


def extract_terms(prompt: str):
    """項抽出: 正規化 → run 抽出 → 重複除去 → 先頭 MAX_TERMS。"""
    normalized = pages_mod.normalize_text(prompt)
    terms = []
    for term in TERM_RE.findall(normalized):
        if term not in terms:
            terms.append(term)
        if len(terms) == MAX_TERMS:
            break
    return terms


def _expired(start: float) -> bool:
    return time.monotonic() - start > BUDGET_SEC


def run(stdin_text: str, cli_root=None, start=None, env=None) -> str:
    """注入テキストを返す（空文字なら何も出力しない）。

    各段に 500ms のチェックポイントを置き、超過時は部分結果を返さず空を返す。
    """
    start = time.monotonic() if start is None else start
    if not enabled(env):
        return ""
    data = json.loads(stdin_text)
    if not isinstance(data, dict):
        return ""
    prompt = data.get("prompt")
    if not isinstance(prompt, str):
        return ""
    terms = extract_terms(prompt)
    if not terms or _expired(start):
        return ""

    layer_list = layers_mod.select_layers("all", cli_root=cli_root, quiet=True)
    layer_list = [layer for layer in layer_list if layer.root.is_dir()]
    if not layer_list or _expired(start):
        return ""

    # index 高速パス（--no-body 相当。本文 grep はしない）
    hits = search_mod.run_search(" ".join(terms), layer_list, None, LIMIT,
                                 no_body=True)
    if not hits or _expired(start):
        return ""

    lines = list(output.TRUST_NOTICE)
    for _score, rec in hits:
        lines.append(f"- [[{rec['ref']}]] — {rec.get('summary', '')}".rstrip())
    return "".join(line + "\n" for line in lines)
