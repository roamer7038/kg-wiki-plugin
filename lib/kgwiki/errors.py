"""例外階層と exit code への写像。"""


class KgError(Exception):
    """汎用的な実行エラー → exit 1。"""

    exit_code = 1


class ValidationFailure(KgError):
    """検証での問題検出 → exit 2。"""

    exit_code = 2


class UsageError(KgError):
    """引数・使用法エラー → exit 3。"""

    exit_code = 3


class FeatureDisabledError(KgError):
    """機能無効（qmd 不在など）→ exit 4。"""

    exit_code = 4


class RefFormatError(KgError):
    """ref の正準形逸脱（parse_ref）。CLI 層で文脈に応じ変換する。"""

    exit_code = 1


class LockError(KgError):
    """ロック取得失敗 → exit 1。"""

    exit_code = 1
