"""kg move: ページ/トピックの移動・全被参照書換・再開収束。

ファイル横断トランザクションは持たない。中断時は kg validate が不整合を検出し、
同コマンドの再実行で収束する。再開判定はページファイルの存在のみで行う
（manifest 等の中間状態に依存しない）。
"""

import os
import re
from pathlib import Path

from . import build as build_mod
from . import config as config_mod
from . import fsio, layers, oplog, refs
from . import pages as pages_mod
from .errors import KgError
from .output import Issue
from .scaffold import new_page_issues

TO_LINE_RE = re.compile(r"^(\s*(?:- )?to: )([\"']?)(.+?)\2(\s*)$")


# --- テキストレベルの参照書換 ---

def _rewrite_line_links(line: str, mapping: dict):
    """インラインコード外の [[old]] を書き換える。"""
    masked = pages_mod.mask_inline_code(line)
    out = []
    last = 0
    count = 0
    for m in pages_mod.LINK_RE.finditer(masked):
        target = m.group(1)
        if target in mapping:
            out.append(line[last:m.start()])
            out.append(f"[[{mapping[target]}]]")
            last = m.end()
            count += 1
    out.append(line[last:])
    return "".join(out), count


def rewrite_refs_text(text: str, mapping: dict):
    """frontmatter relations.to と本文 [[ref]]（コード領域外）を書き換える。"""
    fm_lines, body, fatal = pages_mod.split_frontmatter(text)
    count = 0
    if fatal is not None:
        # frontmatter 不成立ファイルは本文扱いで [[ref]] のみ書換
        new_lines = []
        for line, in_code in pages_mod.body_lines_flags(text):
            if in_code:
                new_lines.append(line)
                continue
            new_line, n = _rewrite_line_links(line, mapping)
            new_lines.append(new_line)
            count += n
        return "\n".join(new_lines), count

    new_fm = []
    for line in fm_lines:
        m = TO_LINE_RE.match(line)
        if m and m.group(3) in mapping:
            new_fm.append(f"{m.group(1)}{mapping[m.group(3)]}")
            count += 1
        else:
            new_fm.append(line)
    new_body = []
    for line, in_code in pages_mod.body_lines_flags(body):
        if in_code:
            new_body.append(line)
            continue
        new_line, n = _rewrite_line_links(line, mapping)
        new_body.append(new_line)
        count += n
    return "---\n" + "\n".join(new_fm) + "\n---\n" + "\n".join(new_body), count


def _update_own_frontmatter(text: str, new_type: str, new_slug: str) -> str:
    fm_lines, body, fatal = pages_mod.split_frontmatter(text)
    if fatal is not None:
        return text
    new_fm = []
    for line in fm_lines:
        if re.match(r"^type: ", line) or line == "type:":
            new_fm.append(f"type: {new_type}")
        elif re.match(r"^slug: ", line) or line == "slug:":
            new_fm.append(f"slug: {new_slug}")
        else:
            new_fm.append(line)
    return "---\n" + "\n".join(new_fm) + "\n---\n" + body


# --- 走査・適用 ---

def _scan_rewrites(layer_list, mapping, apply: bool):
    """全層・全ページを「層（global→project）→ ref 順」で走査し書換。

    [(layer, page_ref, count)] を返す。apply=False なら変更しない。
    """
    results = []
    for layer in layer_list:
        page_refs = layers.scan_page_refs(layer.root)
        for ref in sorted(page_refs):
            path = page_refs[ref]
            text = path.read_bytes().decode("utf-8", errors="replace")
            new_text, count = rewrite_refs_text(text, mapping)
            if count > 0:
                results.append((layer, ref, count))
                if apply:
                    fsio.atomic_write_text(path, new_text)
    return results


def _locate(layer_list, ref: str):
    """ref のページが存在する層（プロジェクト層優先）。無ければ None。"""
    found = None
    for layer in layer_list:  # global → project 順、後勝ち
        if layers.page_path(layer, ref).is_file():
            found = layer
    return found


def _existing_roots(layer_list):
    return [ly for ly in layer_list if Path(ly.root).is_dir()]


def _build_affected(layer_list, topics_by_layer, quiet):
    for layer in layer_list:
        topics = topics_by_layer.get(layer.kind) or set()
        if not topics:
            continue
        cfg, cfg_issues, exists = config_mod.load_config(layer.root)
        if not exists or cfg_issues or cfg is None:
            continue
        defined = [t for t in sorted(topics) if t in cfg.topic_names()]
        if defined:
            build_mod.build_layer(layer, topics_filter=defined)


def run_move_page(all_layers, old_text: str, new_text: str, to_layer,
                  dry_run: bool, date, quiet=False):
    """単一ページの move。(issues, exit_code, stdout_lines)。"""
    issues = []
    for text in (old_text, new_text):
        if not refs.is_canonical(text):
            issues.append(Issue("error", "ref-format", text,
                                "ref が正準形 <topic>/<type>/<slug> でない"))
    if issues:
        return issues, 2, []
    old_ref = refs.parse_ref(old_text)
    new_ref = refs.parse_ref(new_text)

    src_layer = _locate(all_layers, old_text)
    if to_layer:
        dest_layer = next((ly for ly in all_layers if ly.kind == to_layer), None)
        if dest_layer is None:
            raise KgError(f"移動先の層が存在しない: {to_layer}")
    else:
        dest_layer = src_layer

    # 再開判定（ページファイルの存在のみで判定）
    if src_layer is None:
        resume_layer = _locate(all_layers, new_text)
        if resume_layer is None:
            raise KgError(f"対象ページが不在: {old_text}")
        dest_layer = resume_layer
        resumed = True
    else:
        resumed = False
        if old_text == new_text and dest_layer.kind == src_layer.kind:
            return [Issue("error", "ref-exists", new_text,
                          "移動元と移動先が同一（層間移動は --to-layer を指定）")], 2, []
        if layers.page_path(dest_layer, new_text).is_file():
            raise KgError(f"衝突: {new_text} が {dest_layer.kind} 層に既存"
                          "（旧ページの処置を確認して再実行する）")
        # 事前検証: 移動先 topic/type の config 定義
        cfg, cfg_issues, exists = config_mod.load_config(dest_layer.root)
        if not exists:
            raise KgError(f"config.yml がない: {dest_layer.root}（kg init で初期化する）")
        if cfg_issues:
            return cfg_issues, 2, []
        pre, _ref = new_page_issues(dest_layer, cfg, new_text)
        if pre:
            return pre, 2, []

    mapping = {} if old_text == new_text else {old_text: new_text}

    if dry_run:
        plan = []
        action = "書換のみ再開" if resumed else \
            f"{src_layer.kind} → {dest_layer.kind} へ移動"
        plan.append(Issue("info", "move-plan", old_text,
                          f"{old_text} → {new_text}（{action}）"))
        if mapping:
            for layer, page_ref, count in _scan_rewrites(all_layers, mapping, apply=False):
                plan.append(Issue("info", "move-plan", page_ref,
                                  f"{count} 箇所の参照を書換（{layer.kind} 層）"))
        return plan, 0, []

    # 適用（(3) ページ移動 → 被参照書換 → build 増分 → log）
    if not resumed:
        old_path = layers.page_path(src_layer, old_text)
        text = old_path.read_bytes().decode("utf-8", errors="replace")
        text = _update_own_frontmatter(text, new_ref.type, new_ref.slug)
        fsio.atomic_write_text(layers.page_path(dest_layer, new_text), text)
        os.unlink(old_path)

    rewrites = _scan_rewrites(all_layers, mapping, apply=True) if mapping else []
    counts = {}
    for layer, _ref, count in rewrites:
        counts[layer.kind] = counts.get(layer.kind, 0) + count

    topics_by_layer = {}
    for layer, page_ref, _count in rewrites:
        topics_by_layer.setdefault(layer.kind, set()).add(page_ref.split("/")[0])
    topics_by_layer.setdefault(dest_layer.kind, set()).update(
        {old_ref.topic, new_ref.topic})
    if src_layer is not None:
        topics_by_layer.setdefault(src_layer.kind, set()).update(
            {old_ref.topic, new_ref.topic})
    _build_affected(all_layers, topics_by_layer, quiet)

    logged = {dest_layer.kind: dest_layer}
    if src_layer is not None:
        logged[src_layer.kind] = src_layer
    for layer, _ref, _count in rewrites:
        logged[layer.kind] = layer
    total = sum(counts.values())
    for kind in sorted(logged):
        oplog.append(logged[kind].root,
                     oplog.format_line(date, "move",
                                       f"{old_text} → {new_text}（被参照 {total} 件書換）"))
    return [], 0, [f"moved {old_text} → {new_text}（被参照 {total} 件書換）"]


def run_rename_topic(all_layers, target_layer, old_topic: str, new_topic: str,
                     dry_run: bool, date, quiet=False):
    """topic 一括改名。(issues, exit_code, stdout_lines)。"""
    issues = []
    for name in (old_topic, new_topic):
        if not refs.is_slug(name):
            issues.append(Issue("error", "ref-format", name,
                                "topic 名は [a-z0-9-]+ であること"))
    if issues:
        return issues, 2, []

    cfg, cfg_issues, exists = config_mod.load_config(target_layer.root)
    if not exists:
        raise KgError(f"config.yml がない: {target_layer.root}（kg init で初期化する）")
    if cfg_issues:
        return cfg_issues, 2, []
    names = cfg.topic_names()
    if old_topic not in names and new_topic not in names:
        raise KgError(f"対象 topic が config に不在: {old_topic}")
    if old_topic in names and new_topic in names:
        return [Issue("error", "ref-exists", new_topic,
                      f"config に {new_topic} が既存（改名の衝突）")], 2, []

    # 対象ページと mapping（既移動分も含めて書換対象にする = 再開収束）
    mapping = {}
    moves = []  # (old_ref, new_ref, path)
    for type_dir, slug, path in layers.iter_page_paths(target_layer.root, old_topic):
        old_ref = f"{old_topic}/{type_dir}/{slug}"
        new_ref = f"{new_topic}/{type_dir}/{slug}"
        mapping[old_ref] = new_ref
        moves.append((old_ref, new_ref, path))
    for type_dir, slug, _path in layers.iter_page_paths(target_layer.root, new_topic):
        mapping.setdefault(f"{old_topic}/{type_dir}/{slug}",
                           f"{new_topic}/{type_dir}/{slug}")

    if dry_run:
        plan = [Issue("info", "move-plan", f"topic:{old_topic}",
                      f"topic:{old_topic} → topic:{new_topic}"
                      f"（{len(moves)} ページ移動・{target_layer.kind} 層）")]
        for old_ref, new_ref, _path in moves:
            plan.append(Issue("info", "move-plan", old_ref, f"→ {new_ref}"))
        for layer, page_ref, count in _scan_rewrites(all_layers, mapping, apply=False):
            plan.append(Issue("info", "move-plan", page_ref,
                              f"{count} 箇所の参照を書換（{layer.kind} 層）"))
        return plan, 0, []

    # ページ単位の状態判定・移動（一部移動済みでも残りから続行）
    for old_ref, new_ref, path in moves:
        new_path = layers.page_path(target_layer, new_ref)
        if new_path.is_file():
            raise KgError(f"衝突: {new_ref} が既存（旧ページの処置を確認）")
        fsio.atomic_write_text(new_path, path.read_bytes().decode("utf-8",
                                                                  errors="replace"))
        os.unlink(path)

    rewrites = _scan_rewrites(all_layers, mapping, apply=True)
    total = sum(c for _l, _r, c in rewrites)

    # 旧 topic ディレクトリの掃除（pages が空なら _derived ごと削除）
    old_dir = Path(target_layer.root) / "topics" / old_topic
    remaining = list(layers.iter_page_paths(target_layer.root, old_topic))
    if not remaining and old_dir.is_dir():
        import shutil
        shutil.rmtree(old_dir)

    # config 更新は全ページ移動完了後
    if old_topic in names:
        config_path = Path(target_layer.root) / config_mod.CONFIG_NAME
        text = config_path.read_text(encoding="utf-8")
        new_text = text.replace(f"- name: {old_topic}\n", f"- name: {new_topic}\n", 1)
        if new_text == text:
            new_text = text.replace(f"- name: {old_topic}", f"- name: {new_topic}", 1)
        fsio.atomic_write_text(config_path, new_text)

    topics_by_layer = {target_layer.kind: {new_topic}}
    for layer, page_ref, _count in rewrites:
        topics_by_layer.setdefault(layer.kind, set()).add(page_ref.split("/")[0])
    _build_affected(all_layers, topics_by_layer, quiet)

    logged = {target_layer.kind: target_layer}
    for layer, _ref, _count in rewrites:
        logged[layer.kind] = layer
    for kind in sorted(logged):
        oplog.append(logged[kind].root,
                     oplog.format_line(
                         date, "move",
                         f"topic:{old_topic} → topic:{new_topic}"
                         f"（{len(moves)} ページ移動, 被参照 {total} 件書換）"))
    return [], 0, [f"renamed topic:{old_topic} → topic:{new_topic}"
                   f"（{len(moves)} ページ移動, 被参照 {total} 件書換）"]
