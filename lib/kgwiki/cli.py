"""argparse 構築・サブコマンド dispatch・exit code 変換（詳細設計 04 §1.3〜1.4）。

サブコマンド実装は遅延 import（起動時間短縮。A-15）。
"""

import argparse
import datetime
import sys

from . import __version__
from .errors import (FeatureDisabledError, KgError, LockError, UsageError,
                     ValidationFailure)

CURRENT_PHASE = 1
PHASE_GATE = {
    "vsearch": (2, "qmd 委譲のベクトル検索は Phase 2 で提供予定"),
    "hybrid": (2, "qmd 委譲のハイブリッド検索は Phase 2 で提供予定"),
    "community": (2, "コミュニティ検索は Phase 2 で提供予定"),
    "pack": (3, "コンテキストパックは Phase 3 で提供予定"),
    "skillgen": (3, "Corpus2Skill 生成は Phase 3 で提供予定"),
    "hook-context": (3, "hook 注入は Phase 3 で提供予定"),
}


class _ArgParser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(f"{message}\n{self.format_usage().rstrip()}")


def _add_common(p, write=False, limit_default=10, with_limit=True,
                layer_choices=("global", "project", "all")):
    p.add_argument("--root", metavar="PATH", help="グローバル層ルートの明示")
    p.add_argument("--layer", choices=list(layer_choices), default=None)
    p.add_argument("--topic", metavar="T[,T...]", default=None)
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

    sp = sub.add_parser("log", help="log.md への追記（ingest 記録）")
    sp.add_argument("op")
    sp.add_argument("ref")
    sp.add_argument("--source", required=True, metavar="URL|PATH")
    _add_common(sp, write=True, with_limit=False,
                layer_choices=("global", "project"))

    for name in PHASE_GATE:
        sp = sub.add_parser(name)
        sp.add_argument("args", nargs=argparse.REMAINDER)

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
    from . import fsio, refs, scaffold
    if args.with_qmd:
        raise FeatureDisabledError(
            "--with-qmd は Phase 2 で提供予定（qmd 導入後に有効化できる）")
    for name in args.topic:
        if not refs.is_slug(name):
            raise UsageError(f"--topic は [a-z0-9-]+ であること: {name}")
    layer = _write_layer(args)
    date = _parse_date(args.date)
    with fsio.RootLock(layer.root, "init"):
        scaffold.run_init(layer, args.topic, date, quiet=args.quiet)
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
    if args.skills:
        raise FeatureDisabledError("--skills（生成 Skill 検査）は Phase 3 で提供予定")
    if args.quick:
        try:
            print(validate.run_quick(_read_layers(args), cli_root=args.root))
        except Exception:  # hook 用: 常に exit 0（03 §4.1）
            pass
        return 0
    issues = validate.run_validate(_read_layers(args), topics=_topics(args),
                                   cli_root=args.root)
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


def cmd_log(args):
    from . import fsio, layers, oplog
    if args.op != "ingest":
        raise UsageError("kg log の op は ingest のみ（03 §4.10）")
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
        if sub_name in PHASE_GATE:
            phase, message = PHASE_GATE[sub_name]
            raise FeatureDisabledError(
                f"{message}（現行 Phase {CURRENT_PHASE}）。"
                "有効化: プラグインの更新を待つか、リポジトリの Phase 対応版を導入する")
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
    except Exception as e:  # 予期しない例外 → exit 1（04 §1.3）
        print(f"{prefix}: error: 予期しないエラー: {e}", file=sys.stderr)
        if debug:
            import traceback
            traceback.print_exc()
        return 1
