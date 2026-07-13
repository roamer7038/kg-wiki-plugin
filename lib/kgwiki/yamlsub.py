"""YAML サブセットパーサ（基本設計 03 §1.4、詳細設計 04 §2）。

行指向の 2 段文法（字句 + インデントスタック）の再帰下降実装。
エラー回復規則（04 §2.3）:
  1. content-line の構文エラーは issue 1 件を記録して行ごと読み飛ばす
     （インデントスタックと直前の有効状態は変更しない）。
  2. 重複キーは最初の定義を保持し、後続の定義行を読み飛ばす。
  3. frontmatter 開始/終了 `---` の欠落は回復不能（呼び出し側 pages.py が扱う）。

日付は datetime.date、真偽は bool、整数は int として返す（04 §2.2 の型推論。
実在しない日付は str に落ち、スキーマ検証で検出される）。
"""

import datetime
import re
from dataclasses import dataclass

# plain-first の除外集合（04 §2.1）。これらで始まる未引用値はエラー。
PLAIN_FIRST_FORBIDDEN = set('"\'[#&*!|>%@ ')
KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):(.*)$")
INT_RE = re.compile(r"^-?[0-9]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class YamlIssue:
    line: int
    message: str


@dataclass
class _Line:
    lineno: int
    level: int
    text: str


class _ErrorRecovery(Exception):
    """行単位の構文エラー（内部制御用。規則 1 で握って行を読み飛ばす）。"""


def _infer_scalar(text: str):
    """未引用スカラーの型推論（04 §2.2）。"""
    if text == "true":
        return True
    if text == "false":
        return False
    if INT_RE.match(text):
        return int(text)
    if DATE_RE.match(text):
        try:
            return datetime.date.fromisoformat(text)
        except ValueError:
            return text
    return text


class _Parser:
    def __init__(self, lines, issues):
        self.lines = lines
        self.issues = issues
        self.i = 0

    def _issue(self, lineno: int, message: str) -> None:
        self.issues.append(YamlIssue(lineno, message))

    def _peek(self):
        return self.lines[self.i] if self.i < len(self.lines) else None

    # --- スカラー ---

    def _parse_dq(self, text: str, lineno: int):
        """二重引用符。\\\" と \\\\ のみエスケープ許容（04 §2.2）。(値, 残り) を返す。"""
        out = []
        i = 1
        while i < len(text):
            c = text[i]
            if c == "\\":
                if i + 1 < len(text) and text[i + 1] in ('"', "\\"):
                    out.append(text[i + 1])
                    i += 2
                    continue
                self._issue(lineno, "不正なエスケープ（\\\" と \\\\ のみ許容）")
                raise _ErrorRecovery
            if c == '"':
                return "".join(out), text[i + 1:]
            out.append(c)
            i += 1
        self._issue(lineno, "二重引用符が閉じていない")
        raise _ErrorRecovery

    def _parse_sq(self, text: str, lineno: int):
        """単一引用符。'' のみエスケープ許容。(値, 残り) を返す。"""
        out = []
        i = 1
        while i < len(text):
            c = text[i]
            if c == "'":
                if i + 1 < len(text) and text[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                return "".join(out), text[i + 1:]
            out.append(c)
            i += 1
        self._issue(lineno, "単一引用符が閉じていない")
        raise _ErrorRecovery

    def _check_plain(self, text: str, lineno: int, context: str) -> str:
        """plain スカラーの付随制約 PB1〜PB3 を検査し、トリム済み文字列を返す。"""
        if ": " in text:
            self._issue(lineno, f"未引用の{context}に ': '（コロン+空白）を含む（引用符必須。PB1）")
            raise _ErrorRecovery
        if " #" in text:
            self._issue(lineno, f"未引用の{context}に ' #' を含む（行末コメント不可・引用符必須。PB3）")
            raise _ErrorRecovery
        return text.rstrip(" ")  # PB2

    def _forbidden_first(self, c: str, lineno: int, context: str) -> None:
        """plain-first 除外集合による禁止構文の検出（04 §2.1 の表）。"""
        if c in ("&", "*"):
            self._issue(lineno, "アンカー/エイリアスは不可")
        elif c == "!":
            self._issue(lineno, "タグは不可")
        elif c in ("|", ">"):
            self._issue(lineno, "複数行ブロックスカラーは不可")
        elif c == "#":
            self._issue(lineno, f"{context}が '#' で始まる（コメントは行頭のみ）")
        elif c == " ":
            self._issue(lineno, "':' の後の空白は 1 個のみ")
        else:
            self._issue(lineno, f"{context}が {c!r} で始まる（引用符必須）")
        raise _ErrorRecovery

    def _parse_inline_list(self, text: str, lineno: int):
        """インラインリスト [a, b]。ネスト・末尾カンマ・空要素は禁止。(リスト, 残り) を返す。"""
        items = []
        i = 1  # after '['
        n = len(text)
        while i < n and text[i] == " ":
            i += 1
        if i < n and text[i] == "]":
            return items, text[i + 1:]  # 空リスト
        while True:
            while i < n and text[i] == " ":
                i += 1
            if i >= n:
                self._issue(lineno, "インラインリストが閉じていない")
                raise _ErrorRecovery
            c = text[i]
            if c == '"':
                value, rest = self._parse_dq(text[i:], lineno)
                i = n - len(rest)
            elif c == "'":
                value, rest = self._parse_sq(text[i:], lineno)
                i = n - len(rest)
            elif c in ("[", "{"):
                self._issue(lineno, "フロースタイルのネストは不可")
                raise _ErrorRecovery
            elif c in PLAIN_FIRST_FORBIDDEN:
                self._forbidden_first(c, lineno, "インラインリスト要素")
            else:
                j = i
                while j < n and text[j] not in (",", "]"):
                    j += 1
                raw = self._check_plain(text[i:j], lineno, "インラインリスト要素")
                if raw == "":
                    self._issue(lineno, "インラインリスト要素が空")
                    raise _ErrorRecovery
                value = _infer_scalar(raw)
                i = j
            items.append(value)
            while i < n and text[i] == " ":
                i += 1
            if i >= n:
                self._issue(lineno, "インラインリストが閉じていない")
                raise _ErrorRecovery
            if text[i] == "]":
                return items, text[i + 1:]
            if text[i] == ",":
                i += 1
                j = i
                while j < n and text[j] == " ":
                    j += 1
                if j < n and text[j] == "]":
                    self._issue(lineno, "インラインリストの末尾カンマは不可")
                    raise _ErrorRecovery
                continue
            self._issue(lineno, "インラインリスト要素の後は ',' か ']' であること")
            raise _ErrorRecovery

    def _parse_scalar_value(self, text: str, lineno: int, allow_inline_list: bool,
                            context: str = "値"):
        """値位置のスカラー（またはインラインリスト）を解析する。"""
        c = text[0]
        if c == "[":
            if not allow_inline_list:
                self._issue(lineno, "この位置にインラインリストは書けない")
                raise _ErrorRecovery
            value, rest = self._parse_inline_list(text, lineno)
        elif c == '"':
            value, rest = self._parse_dq(text, lineno)
        elif c == "'":
            value, rest = self._parse_sq(text, lineno)
        elif c in PLAIN_FIRST_FORBIDDEN:
            self._forbidden_first(c, lineno, context)
        else:
            raw = self._check_plain(text, lineno, context)
            return _infer_scalar(raw)
        if rest.strip(" "):
            self._issue(lineno, "値の後に余分な内容がある")
            raise _ErrorRecovery
        return value

    # --- 構造 ---

    def _parse_value_or_block(self, after_colon: str, level: int, lineno: int):
        """map-entry の値。同一行の値、または次行以降の +2 インデントブロック。"""
        if after_colon == "" or after_colon.strip(" ") == "":
            # 値なし → ネストブロック（level+1）を探す。無ければ None
            nxt = self._peek()
            if nxt is not None and nxt.level == level + 1:
                return self._parse_block(level + 1)
            return None
        if not after_colon.startswith(" "):
            self._issue(lineno, "':' の直後に空白が必要")
            raise _ErrorRecovery
        return self._parse_scalar_value(after_colon[1:], lineno, True)

    def _parse_block(self, level: int):
        nxt = self._peek()
        if nxt is not None and (nxt.text == "-" or nxt.text.startswith("- ")):
            return self._parse_list(level)
        return self._parse_mapping(level)

    def _parse_mapping(self, level: int, into: dict = None) -> dict:
        result = {} if into is None else into
        while True:
            ln = self._peek()
            if ln is None or ln.level < level:
                break
            if ln.level > level:
                self._issue(ln.lineno, "インデントが不正（+2 の増加のみ許可）")
                self.i += 1
                continue
            if ln.text == "-" or ln.text.startswith("- "):
                break  # リスト行はこの文脈のものでない（呼び出し側で扱う）
            self.i += 1
            try:
                self._parse_map_entry_into(ln.text, level, ln.lineno, result)
            except _ErrorRecovery:
                pass
        return result

    def _parse_map_entry_into(self, text: str, level: int, lineno: int, result: dict) -> None:
        m = KEY_RE.match(text)
        if m is None:
            self._issue(lineno, "マッピングのキー行として解釈できない")
            raise _ErrorRecovery
        key, after = m.group(1), m.group(2)
        if key in result:
            self._issue(lineno, f"重複キー: {key}（最初の定義を保持）")
            raise _ErrorRecovery
        result[key] = self._parse_value_or_block(after, level, lineno)

    def _parse_list(self, level: int) -> list:
        items = []
        while True:
            ln = self._peek()
            if ln is None or ln.level < level:
                break
            if ln.level > level:
                self._issue(ln.lineno, "インデントが不正（+2 の増加のみ許可）")
                self.i += 1
                continue
            if not ln.text.startswith("- "):
                if ln.text == "-":
                    self._issue(ln.lineno, "空のリスト要素は不可")
                    self.i += 1
                    continue
                break  # マッピング行はこの文脈のものでない（呼び出し側で扱う）
            self.i += 1
            rest = ln.text[2:]
            try:
                if KEY_RE.match(rest):
                    # リスト要素マッピング: 先頭エントリ + 継続行（level+1）
                    item = {}
                    try:
                        self._parse_map_entry_into(rest, level + 1, ln.lineno, item)
                    except _ErrorRecovery:
                        pass
                    self._parse_mapping(level + 1, into=item)
                    items.append(item)
                else:
                    if rest.strip(" ") == "":
                        self._issue(ln.lineno, "空のリスト要素は不可")
                        raise _ErrorRecovery
                    items.append(self._parse_scalar_value(rest, ln.lineno, False,
                                                          "リスト要素"))
            except _ErrorRecovery:
                pass
        return items


def _lex(raw_lines, first_lineno: int, issues):
    lines = []
    for offset, raw in enumerate(raw_lines):
        lineno = first_lineno + offset
        stripped = raw.lstrip(" \t")
        if stripped == "" or stripped.startswith("#"):
            continue  # blank-line / comment-line
        indent = raw[: len(raw) - len(stripped)]
        if "\t" in indent:
            issues.append(YamlIssue(lineno, "インデントにタブは不可"))
            continue
        if len(indent) % 2 != 0:
            issues.append(YamlIssue(lineno, "インデントは 2 スペース単位"))
            continue
        lines.append(_Line(lineno, len(indent) // 2, stripped))
    return lines


def parse_mapping_lines(raw_lines, first_lineno: int = 1):
    """行のリストをルートマッピングとして解析する。(dict, [YamlIssue]) を返す。"""
    issues: list = []
    lines = _lex(raw_lines, first_lineno, issues)
    parser = _Parser(lines, issues)
    result = parser._parse_mapping(0)
    while parser._peek() is not None:
        ln = parser._peek()
        issues.append(YamlIssue(ln.lineno, "ルートはマッピングであること"))
        parser.i += 1
        parser._parse_mapping(0, into=result)
    issues.sort(key=lambda x: x.line)
    return result, issues


def parse_document(text: str):
    """config.yml 全体（--- 区切りなし）を解析する。"""
    return parse_mapping_lines(text.split("\n"), 1)


def needs_quote(value: str) -> bool:
    """文字列を未引用 plain として書けないなら True（init/new の生成用）。"""
    if value == "" or value != value.strip(" "):
        return True
    if value[0] in PLAIN_FIRST_FORBIDDEN:
        return True
    if ": " in value or " #" in value or "," in value or "]" in value:
        return True
    if value in ("true", "false") or INT_RE.match(value) or DATE_RE.match(value):
        return True
    return False


def dump_scalar(value) -> str:
    """スカラーを本サブセットで安全に直列化する（init/new の生成用）。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, datetime.date):
        return value.isoformat()
    text = str(value)
    if needs_quote(text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text
