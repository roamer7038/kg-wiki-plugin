"""アトミック書き込み・root ロック。"""

import atexit
import datetime
import os
from pathlib import Path

from .errors import LockError

LOCK_NAME = ".kg-lock"


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """同一ディレクトリの tmp（.<name>.tmp-<pid>）に書き os.replace。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp-{os.getpid()}"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


class RootLock:
    """root 単位のロックファイル <root>/.kg-lock。

    O_CREAT|O_EXCL による排他作成。取得失敗は即 LockError（exit 1）で、自動奪取は
    しない。解放は try/finally と atexit の二重化。
    """

    def __init__(self, root: Path, subcommand: str):
        self.root = Path(root)
        self.subcommand = subcommand
        self.path = self.root / LOCK_NAME
        self._held = False

    def acquire(self) -> "RootLock":
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            info = ""
            try:
                info = self.path.read_text(encoding="utf-8").strip()
            except OSError:
                pass
            raise LockError(
                f"ロックを取得できない: {self.path}（{info or '内容不明'}）。"
                "実行中プロセスの終了を確認のうえ手動削除すること"
            ) from None
        content = (
            f"pid={os.getpid()}\nsubcommand={self.subcommand}\n"
            f"time={datetime.datetime.now().isoformat(timespec='seconds')}\n"
        )
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        self._held = True
        atexit.register(self.release)
        return self

    def release(self) -> None:
        if self._held:
            self._held = False
            try:
                os.unlink(self.path)
            except OSError:
                pass

    def __enter__(self) -> "RootLock":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()


def acquire_locks(roots, subcommand: str):
    """複数 root のロックを与えられた順に取得する。

    両層に書き込む操作はグローバル → プロジェクトの順で取得する
    （デッドロック回避規約。呼び出し側がその順で渡す）。
    """
    locks = []
    try:
        for root in roots:
            locks.append(RootLock(root, subcommand).acquire())
    except LockError:
        for lock in reversed(locks):
            lock.release()
        raise
    return locks
