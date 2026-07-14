"""argparse 構築・サブコマンド dispatch・exit code 変換。

サブコマンド実装は遅延 import（起動時間短縮）。
"""

import argparse
import datetime
import sys

from . import __version__
from .errors import (FeatureDisabledError, KgError, LockError, UsageError,
                     ValidationFailure)


class _ArgParser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(f"{message}\n{self.format_usage().rstrip()}")


def _add_common(p, write=False, limit_default=10, with_limit=True, with_json=True,
                layer_choices=("global", "project", "all")):
    p.add_argument("--root", metavar="PATH", help="グローバル層ルートの明示")
    p.add_argument("--layer", choices=list(layer_choices), default=None)
    p.add_argument("--topic", metavar="T[,T...]", default=None)
    if with_json:
        p.add_argument("--json", action="store_true")
    if with_limit:
        p.add_argument("--limit", type=int, default=limit_default, metavar="N")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--debug", action="store_true")
    if write:
        p.add_argument("--date", metavar="YYYY-MM-DD", default=None)


def build_parser():
    p = _ArgParser(prog="kg", allow_abbrev=False,
                   description="kg-wiki: Markdown 知識リポジトリ + 派生 KG")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="subcommand", metavar="<subcommand>",
                           parser_class=_ArgParser)

    sp = sub.add_parser("init", help="層の初期化（冪等）")
    sp.add_argument("--topic", action="append", default=[], metavar="NAME")
    sp.add_argument("--with-qmd", action="store_true", dest="with_qmd")
    sp.add_argument("--root", metavar="PATH")
    sp.add_argument("--layer", choices=["global", "project"], default=None)
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--quiet", action="store_true")
    sp.add_argument("--debug", action="store_true")
    sp.add_argument("--date", metavar="YYYY-MM-DD", default=None)

    sp = sub.add_parser("build", help="派生物の生成（増分）")
    sp.add_argument("--full", action="store_true")
    _add_common(sp, write=True, with_limit=False)

    sp = sub.add_parser("search", help="語彙検索")
    sp.add_argument("query")
    sp.add_argument("--no-body", action="store_true", dest="no_body")
    _add_common(sp)

    sp = sub.add_parser("traverse", help="n-hop 近傍の取得")
    sp.add_argument("ref")
    sp.add_argument("--hops", type=int, default=1, metavar="N")
    sp.add_argument("--rel", default=None, metavar="R[,R...]")
    sp.add_argument("--direction", choices=["out", "in", "both"], default="both")
    _add_common(sp)

    sp = sub.add_parser("path", help="2 ページ間の関係経路列挙")
    sp.add_argument("ref1")
    sp.add_argument("ref2")
    sp.add_argument("--max-paths", type=int, default=3, dest="max_paths", metavar="K")
    sp.add_argument("--max-hops", type=int, default=6, dest="max_hops", metavar="N")
    _add_common(sp, with_limit=False)

    sp = sub.add_parser("validate", help="構造・鮮度の検査")
    sp.add_argument("--quick", action="store_true")
    sp.add_argument("--skills", action="store_true")
    _add_common(sp, with_limit=False)

    sp = sub.add_parser("move", help="ページ/トピックの移動・改名")
    sp.add_argument("refs", nargs="*", metavar="<ref> <new-ref>")
    sp.add_argument("--rename-topic", nargs=2, dest="rename_topic",
                    metavar=("TOPIC", "NEW_TOPIC"), default=None)
    sp.add_argument("--to-layer", choices=["global", "project"], dest="to_layer",
                    default=None)
    sp.add_argument("--dry-run", action="store_true", dest="dry_run")
    _add_common(sp, write=True, with_limit=False)

    sp = sub.add_parser("new", help="テンプレートからページ生成")
    sp.add_argument("ref")
    sp.add_argument("--title", default=None)
    sp.add_argument("--summary", default=None)
    sp.add_argument("--keywords", default=None, metavar="a,b")
    _add_common(sp, write=True, with_limit=False)

    sp = sub.add_parser("vsearch", help="ベクトル検索（qmd 委譲）")
    sp.add_argument("query")
    _add_common(sp)

    sp = sub.add_parser("hybrid", help="ハイブリッド検索（qmd 委譲）")
    sp.add_argument("query")
    _add_common(sp)

    sp = sub.add_parser("community", help="所属コミュニティと要約の取得")
    sp.add_argument("ref", nargs="?", default=None)
    sp.add_argument("--query", dest="query", default=None, metavar="Q")
    _add_common(sp)

    # プロンプトは stdin の hook JSON からのみ読む（引数化しない）
    sp = sub.add_parser("hook-context", help="UserPromptSubmit hook 用の軽量注入")
    sp.add_argument("--root", metavar="PATH")
    sp.add_argument("--debug", action="store_true")

    sp = sub.add_parser("skillgen", help="生成 Skill の作成（staging）・配置")
    sp.add_argument("source", metavar="topic:<topic> | community:<id>")
    sp.add_argument("--name", default=None, metavar="N")
    sp.add_argument("--install", action="store_true")
    sp.add_argument("--dest", default=None, metavar="DIR")
    sp.add_argument("--dry-run", action="store_true", dest="dry_run")
    _add_common(sp, write=True, with_limit=False, with_json=False,
                layer_choices=("global", "project"))

    sp = sub.add_parser("pack", help="コンテキストパックの生成")
    sp.add_argument("args", nargs="*", metavar="<query> | <ref>...")
    sp.add_argument("--hops", type=int, default=1, metavar="N")
    sp.add_argument("--max-bytes", type=int, default=None, dest="max_bytes",
                    metavar="B")
    sp.add_argument("--out", default=None, metavar="FILE")
    _add_common(sp, with_json=False)

    sp = sub.add_parser("log", help="log.md への追記（ingest 記録）")
    sp.add_argument("op")
    sp.add_argument("ref")
    sp.add_argument("--source", required=True, metavar="URL|PATH")
    _add_common(sp, write=True, with_limit=False,
                layer_choices=("global", "project"))

    return p


# --- 引数ユーティリティ ---

def _parse_date(text):
    if text is None:
        return datetime.date.today()
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise UsageError(f"--date は YYYY-MM-DD 形式であること: {text}") from None


def _topics(args):
    if getattr(args, "topic", None):
        return [t for t in args.topic.split(",") if t]
    return None


def _read_layers(args):
    from . import layers
    return layers.select_layers(args.layer or "all", cli_root=args.root,
                                quiet=args.quiet)


def _write_layer(args):
    from . import layers
    selected = layers.select_layers(args.layer or "", cli_root=args.root,
                                    for_write=True, quiet=args.quiet)
    return selected[0]


def _check_ref_arg(text):
    from . import refs
    if not refs.is_canonical(text):
        raise UsageError(f"ref が正準形 <topic>/<type>/<slug> でない: {text}")


def _print_issues(issues, as_json):
    from . import output
    for issue in issues:
        print(output.jsonl(issue.record()) if as_json else issue.line())


# --- ハンドラ ---

def cmd_init(args):
    from . import config as config_mod
    from . import fsio, refs, scaffold
    if args.with_qmd:
        from . import qmdfacade
        if qmdfacade.qmd_path() is None:
            raise FeatureDisabledError(
                "qmd が PATH に見つからない。導入: npm install -g @tobilu/qmd"
                "（Node.js 22+）")
    for name in args.topic:
        if not refs.is_slug(name):
            raise UsageError(f"--topic は [a-z0-9-]+ であること: {name}")
    layer = _write_layer(args)
    date = _parse_date(args.date)
    with fsio.RootLock(layer.root, "init"):
        scaffold.run_init(layer, args.topic, date, quiet=args.quiet)
        if args.with_qmd:
            from . import qmdfacade
            config_path = layer.root / config_mod.CONFIG_NAME
            version_range = (qmdfacade.VERIFIED_VERSION_RANGE
                             or qmdfacade.version() or "")
            fsio.atomic_write_text(config_path, config_mod.enable_qmd_text(
                config_path.read_text(encoding="utf-8"), version_range))
            if not args.quiet:
                print(f"kg init: qmd 連携を有効化（version_range: {version_range}）",
                      file=sys.stderr)
            try:
                name = qmdfacade.register_collection(layer)
                if not args.quiet:
                    print(f"kg init: qmd コレクション: {name}", file=sys.stderr)
                qmdfacade.sync(layer.root)
            except Exception as e:
                print(f"kg init: 警告: qmd 登録・同期に失敗（次回 build で再同期）: {e}",
                      file=sys.stderr)
    return 0


def cmd_build(args):
    from . import build, fsio, output
    layer = _write_layer(args)
    with fsio.RootLock(layer.root, "build"):
        results = build.build_layer(layer, topics_filter=_topics(args),
                                    full=args.full)
    failed = False
    for result in results:
        if result.ok:
            print(output.jsonl(result.summary_record()) if args.json
                  else result.summary_line())
        else:
            failed = True
            _print_issues(result.issues, args.json)
    if not failed:
        # (6) qmd 側 index の同期（有効時のみ。失敗は警告にとどめ exit 0）
        from . import qmdfacade
        if qmdfacade.enabled_by_config([layer]) and qmdfacade.qmd_path() is not None:
            try:
                qmdfacade.sync(layer.root)
            except Exception as e:
                print(f"kg build: 警告: qmd 同期に失敗（次回 build で再同期）: {e}",
                      file=sys.stderr)
    return 2 if failed else 0


def cmd_search(args):
    from . import search
    if args.limit < 1:
        raise UsageError("--limit は 1 以上であること")
    hits = search.run_search(args.query, _read_layers(args), _topics(args),
                             args.limit, args.no_body)
    from . import output
    for score, rec in hits:
        print(output.jsonl(search.hit_record(score, rec)) if args.json
              else search.format_hit(score, rec))
    return 0


def cmd_traverse(args):
    from . import output, traverse
    _check_ref_arg(args.ref)
    if not 1 <= args.hops <= 6:
        raise UsageError("--hops は 1〜6 であること")
    if args.limit < 1:
        raise UsageError("--limit は 1 以上であること")
    rel_filter = set(args.rel.split(",")) if args.rel else None
    rows, merged_index = traverse.run_traverse(
        args.ref, _read_layers(args), _topics(args), args.hops, rel_filter,
        args.direction, args.limit)
    for row in rows:
        print(output.jsonl(traverse.row_record(row, merged_index)) if args.json
              else traverse.format_row(row, merged_index))
    return 0


def cmd_path(args):
    from . import output, pathfind
    _check_ref_arg(args.ref1)
    _check_ref_arg(args.ref2)
    if not 1 <= args.max_hops <= 6:
        raise UsageError("--max-hops は 1〜6 であること")
    if args.max_paths < 1:
        raise UsageError("--max-paths は 1 以上であること")
    paths = pathfind.run_path(args.ref1, args.ref2, _read_layers(args),
                              _topics(args), args.max_paths, args.max_hops)
    if paths is None:
        print(f"kg path: 経路なし（上限 {args.max_hops} hop）", file=sys.stderr)
        return 0
    for steps in paths:
        print(output.jsonl(pathfind.path_record(args.ref1, steps)) if args.json
              else pathfind.format_path(args.ref1, steps))
    return 0


def cmd_validate(args):
    from . import validate
    if args.quick:
        try:
            print(validate.run_quick(_read_layers(args), cli_root=args.root))
        except Exception:  # hook 用: 常に exit 0
            pass
        return 0
    issues = validate.run_validate(_read_layers(args), topics=_topics(args),
                                   cli_root=args.root, skills=args.skills)
    _print_issues(issues, args.json)
    return 2 if any(i.severity == "error" for i in issues) else 0


def cmd_move(args):
    from . import fsio, layers, move
    date = _parse_date(args.date)
    all_layers = layers.select_layers("all", cli_root=args.root, quiet=True)
    existing = [ly for ly in all_layers if ly.root.is_dir()]
    if args.rename_topic:
        if args.refs:
            raise UsageError("--rename-topic と ref 引数は同時に指定できない")
        target = _write_layer(args)
        locks = [] if args.dry_run else fsio.acquire_locks(
            [ly.root for ly in existing], "move")
        try:
            issues, code, lines = move.run_rename_topic(
                existing, target, args.rename_topic[0], args.rename_topic[1],
                args.dry_run, date, quiet=args.quiet)
        finally:
            for lock in reversed(locks):
                lock.release()
    else:
        if len(args.refs) != 2:
            raise UsageError("usage: kg move <ref> <new-ref>（または --rename-topic）")
        candidates = existing
        if args.layer in ("global", "project"):
            candidates = [ly for ly in existing if ly.kind == args.layer]
        locks = [] if args.dry_run else fsio.acquire_locks(
            [ly.root for ly in existing], "move")
        try:
            issues, code, lines = move.run_move_page(
                candidates or existing, args.refs[0], args.refs[1],
                args.to_layer, args.dry_run, date, quiet=args.quiet)
        finally:
            for lock in reversed(locks):
                lock.release()
    _print_issues(issues, args.json)
    for line in lines:
        print(line)
    return code


def cmd_new(args):
    from . import fsio, scaffold
    layer = _write_layer(args)
    date = _parse_date(args.date)
    keywords = [k for k in (args.keywords or "").split(",") if k]
    with fsio.RootLock(layer.root, "new"):
        issues, path = scaffold.run_new(layer, args.ref, args.title,
                                        args.summary, keywords, date)
    if issues:
        _print_issues(issues, args.json)
        return 2
    print(path)
    return 0


def _cmd_qmd_search(args, mode):
    from . import layers, output, qmdfacade
    if args.limit < 1:
        raise UsageError("--limit は 1 以上であること")
    layer_list = _read_layers(args)
    qmdfacade.require_enabled(layer_list)
    results = qmdfacade.search(mode, args.query, layer_list, _topics(args),
                               args.limit)
    layer_records = [(ly.kind, layers.load_index_records(ly, _topics(args)))
                     for ly in layer_list]
    merged, _shadow = layers.merge_index(layer_records)
    for score, ref, kind in results:
        rec = merged.get(ref)
        if args.json:
            data = dict(rec) if rec else {"layer": kind, "ref": ref}
            data["score"] = output.score_json(score)
            print(output.jsonl(data))
        else:
            title = rec.get("title", "") if rec else ""
            summary = rec.get("summary", "") if rec else ""
            print(output.hit_line(output.fmt_score(score), ref, title, summary))
    return 0


def cmd_vsearch(args):
    return _cmd_qmd_search(args, "vsearch")


def cmd_hybrid(args):
    return _cmd_qmd_search(args, "hybrid")


def cmd_community(args):
    from . import community, layers, output
    if (args.ref is None) == (args.query is None):
        raise UsageError("usage: kg community (<ref> | --query <q>)")
    layer_list = _read_layers(args)
    if args.query is not None:
        if args.limit < 1:
            raise UsageError("--limit は 1 以上であること")
        rows = community.run_community_query(args.query, layer_list,
                                             _topics(args), args.limit)
        for count, cid, topic, size in rows:
            if args.json:
                print(output.jsonl({"community": cid, "count": count,
                                    "pages": size, "topic": topic}))
            else:
                print(f"{count}\t{cid}\t{topic}（{size} pages）")
        return 0

    _check_ref_arg(args.ref)
    cid, layer, members, summary, stale = community.run_community_ref(
        args.ref, layer_list, _topics(args))
    topic = args.ref.split("/")[0]
    has_summary = bool(summary) and any(line.strip() for line in summary)
    if args.json:
        print(output.jsonl({
            "community": cid,
            "layer": layer.kind,
            "pages": len(members),
            "stale": stale,
            "summary": "\n".join(summary).strip("\n") if has_summary else "",
            "topic": topic,
        }))
        return 0
    for line in output.TRUST_NOTICE:  # 俯瞰供給 = 本文非返却の例外
        print(line)
    if stale:
        print("[kg-wiki] 警告: この要約は stale（ソース変更後に再執筆されていない）。"
              "kg build と要約の再執筆を検討すること。")
    print(f"community: {cid}（topic: {topic}, {len(members)} pages, "
          f"layer: {layer.kind}）")
    if has_summary:
        print("\n".join(summary).strip("\n"))
    else:
        records = layers.load_index_records(layer, [topic])
        for ref in members:
            rec = records.get(ref, {})
            print(f"- [[{ref}]] — {rec.get('summary', '')}".rstrip())
        print("kg community: summary 未執筆（骨格の所属一覧のみ表示）。"
              "/kg-wiki:kg-build の要約執筆ワークフローで執筆する", file=sys.stderr)
    return 0


def cmd_hook_context(args):
    """hook 専用: 常に exit 0（空出力で正常終了する）。"""
    import time
    start = time.monotonic()
    try:
        from . import hookctx
        text = hookctx.run(sys.stdin.read(), cli_root=args.root, start=start)
    except Exception as e:  # 内部エラーも空出力 exit 0（stderr に診断のみ）
        print(f"kg hook-context: 診断: {e}", file=sys.stderr)
        if args.debug:
            import traceback
            traceback.print_exc()
        return 0
    if text:
        sys.stdout.write(text)
    return 0


def cmd_skillgen(args):
    from . import fsio, layers, oplog, refs, skillgen, validate
    if args.dry_run and not args.install:
        raise UsageError("--dry-run は --install と併用すること")
    # --name はパス結合に使うため slug と同じ厳格さで検証する（トラバーサル防止）
    if args.name is not None and not refs.is_slug(args.name):
        raise UsageError(f"--name は [a-z0-9-]+ であること: {args.name!r}")
    kind, value = skillgen.parse_source(args.source)
    layer = _write_layer(args)
    date = _parse_date(args.date)

    with fsio.RootLock(layer.root, "skillgen"):
        path, name, topic = skillgen.generate(layer, kind, value, args.name)
        if not args.install:
            oplog.append(layer.root, oplog.format_line(
                date, "skillgen",
                f"{kind}:{value} → {path.parent.relative_to(layer.root)}"))
            print(path)
            return 0

        # --install: 当該 Skill の事前検証（エラーがあれば exit 2）
        loaded = [layers.load_layer(layer, topics=[topic])]
        target = f"{layer.kind}:{topic}/skills/{name}"
        issues = validate.skill_file_issues(path, name, target, loaded)
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            _print_issues(validate.sort_issues(issues), False)
            raise ValidationFailure(
                "生成 Skill の検証に失敗（LLM 執筆領域を埋めてから再実行する）")

        diff, changed = skillgen.install(path, name, args.dest, args.dry_run)
        for line in diff:
            print(line)
        if args.dry_run:
            if not args.quiet:
                print("kg skillgen: --dry-run のため変更していない"
                      "（差分を承認のうえ --install で配置する）", file=sys.stderr)
            return 0
        installed = skillgen.dest_dir(args.dest) / name
        if changed:
            oplog.append(layer.root, oplog.format_line(
                date, "skill-install", f"{name} → {installed}"))
        elif not args.quiet:
            print("kg skillgen: 配置先は staging と同一（変更なし）", file=sys.stderr)
        if not args.quiet:
            print(f"kg skillgen: {installed} に配置した", file=sys.stderr)
        return 0


def cmd_pack(args):
    from . import fsio, pack
    if not args.args:
        raise UsageError("usage: kg pack (<query> | <ref>...)")
    if not 1 <= args.hops <= 6:
        raise UsageError("--hops は 1〜6 であること")
    if args.limit < 1:
        raise UsageError("--limit は 1 以上であること")
    if args.max_bytes is not None and args.max_bytes < 1:
        raise UsageError("--max-bytes は 1 以上であること")

    text, _omitted, over_budget = pack.run_pack(
        args.args, _read_layers(args), _topics(args), args.hops, args.limit,
        args.max_bytes)
    if text is None:
        raise KgError("収集対象が 0 件（クエリ・ref を見直す）")
    if over_budget:
        # 省略一覧のバイトも計上するため、極端に小さい上限では最小出力が上限を超える。
        # 打ち切らずに出力し警告のみとする（決定論を優先）
        print(f"kg pack: 警告: 出力が上限超過（--max-bytes {args.max_bytes} に対し "
              f"{len(text.encode('utf-8'))} バイト）。省略一覧のバイト計上のため打ち切らない",
              file=sys.stderr)
    if args.out:
        from pathlib import Path
        fsio.atomic_write_text(Path(args.out).expanduser(), text)
        if not args.quiet:
            print(f"kg pack: {args.out} に書き出した", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


def cmd_log(args):
    from . import fsio, layers, oplog
    if args.op != oplog.LOG_CMD_OP:
        others = ", ".join(op for op in oplog.OPS if op != oplog.LOG_CMD_OP)
        raise UsageError(
            f"kg log の op は {oplog.LOG_CMD_OP} のみ"
            f"（{others} は各コマンドが自身で記録する）")
    _check_ref_arg(args.ref)
    date = _parse_date(args.date)
    if args.layer in ("global", "project"):
        layer_list = layers.select_layers(args.layer, cli_root=args.root,
                                          quiet=args.quiet)
    else:
        layer_list = layers.select_layers("all", cli_root=args.root, quiet=True)
    existing = [ly for ly in layer_list if ly.root.is_dir()]
    locks = fsio.acquire_locks([ly.root for ly in existing], "log")
    try:
        oplog.run_log_ingest(existing, args.ref, args.source, date)
    finally:
        for lock in reversed(locks):
            lock.release()
    return 0


HANDLERS = {
    "init": cmd_init,
    "build": cmd_build,
    "search": cmd_search,
    "traverse": cmd_traverse,
    "path": cmd_path,
    "validate": cmd_validate,
    "move": cmd_move,
    "new": cmd_new,
    "log": cmd_log,
    "pack": cmd_pack,
    "skillgen": cmd_skillgen,
    "hook-context": cmd_hook_context,
    "vsearch": cmd_vsearch,
    "hybrid": cmd_hybrid,
    "community": cmd_community,
}


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass
    sub_name = ""
    debug = False
    prefix = "kg"
    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        sub_name = args.subcommand or ""
        prefix = f"kg {sub_name}" if sub_name else "kg"
        debug = bool(getattr(args, "debug", False))
        if not sub_name:
            raise UsageError(f"サブコマンドが必要\n{parser.format_usage().rstrip()}")
        return HANDLERS[sub_name](args)
    except UsageError as e:
        print(f"{prefix}: error: {e}", file=sys.stderr)
        return 3
    except FeatureDisabledError as e:
        print(f"{prefix}: error: {e}", file=sys.stderr)
        return 4
    except ValidationFailure as e:
        if str(e):
            print(f"{prefix}: error: {e}", file=sys.stderr)
        return 2
    except (LockError, KgError) as e:
        print(f"{prefix}: error: {e}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 1
    except Exception as e:  # 予期しない例外 → exit 1
        print(f"{prefix}: error: 予期しないエラー: {e}", file=sys.stderr)
        if debug:
            import traceback
            traceback.print_exc()
        return 1
