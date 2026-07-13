"""統一出力フォーマット・スコア丸め・JSONL 直列化（詳細設計 04 §1.1、基本設計 03 §4.1）。

丸めは Python 組み込み round()（float の二進表現により最近接偶数にならない場合が
ある）ではなく Decimal による（NFR-2）。
"""

import json
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal

# validate 系 issue の重大度順（03 §4.7: error → warn → info）
SEVERITY_RANK = {"error": 0, "warn": 1, "info": 2}


@dataclass
class Issue:
    """検証 issue（03 §4.7 の出力列と一致。04 §1.2）。

    halts は「kg build を中断させる種別か」の内部フラグ（出力しない。03 §4.3:
    frontmatter のパース・スキーマ検証の失敗のみが build を中断し、リンク未解決は
    中断しない）。
    """

    severity: str
    code: str
    target: str
    message: str
    halts: bool = field(default=False, compare=False)

    def line(self) -> str:
        return f"{self.severity}\t{self.code}\t{self.target}\t{self.message}"

    def record(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "target": self.target,
            "message": self.message,
        }


def sort_issues(issues):
    """severity → code → target（→ message）順（03 §4.7）。"""
    return sorted(
        issues,
        key=lambda x: (SEVERITY_RANK.get(x.severity, 9), x.code, x.target, x.message),
    )


def round_score(score) -> Decimal:
    """スコアを小数第 2 位に最近接偶数丸めした Decimal を返す。"""
    return Decimal(str(score)).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def fmt_score(score) -> str:
    """表示用スコア文字列（常に小数第 2 位まで）。"""
    return str(round_score(score))


def score_json(score) -> float:
    """--json 出力用のスコア値（丸め後）。"""
    return float(round_score(score))


def jsonl(obj) -> str:
    """JSONL 1 行（キー辞書順・コンパクト・生 UTF-8。03 §3.1）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def hit_line(score_text: str, ref: str, title: str, summary: str, extra: str = "") -> str:
    """検索系の統一 1 行フォーマット: <score>\t[[ref]]\t<title> — <summary>（03 §4.1）。"""
    line = f"{score_text}\t[[{ref}]]\t{title} — {summary}"
    if extra:
        line += f"\t{extra}"
    return line
