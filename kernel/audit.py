"""审计日志 — append-only JSONL，写入失败=ESAE停止。

参考：Raven ToolAuditHook（但修复了 except OSError: pass 安全缺陷）。
"""
import json
import os
import fcntl
from datetime import datetime
from pathlib import Path
from typing import Optional


class ESAEError(Exception):
    """ESAE 模块异常基类。"""


class AuditError(ESAEError):
    """审计写入失败。ESAE 应停止。"""


class AuditLog:
    """append-only JSONL 审计日志。

    写入失败时抛出 AuditError，调用者应停止 ESAE。
    使用 fcntl 文件锁防止并发写入，每次写入后立即 fsync。
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = path or Path.home() / ".hermes" / "esae" / "logs" / "audit.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, action: str, result: str,
            target: str = "", detail: str = "") -> dict:
        """记录一条审计事件。写入失败抛出 AuditError。"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "result": result,
            "target": target,
            "detail": detail,
            "pid": os.getpid(),
        }
        self._write(entry)
        return entry

    def recent(self, n: int = 10) -> list[dict]:
        """读取最近 N 条审计记录。"""
        if not self.path.exists():
            return []
        records: list[dict] = []
        line_count = 0
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # 统计总行数，但只存最后 N 行
                    if line:
                        line_count += 1
                        if line_count <= n:
                            records.insert(0, json.loads(line))
                        else:
                            records.pop()
                            records.insert(0, json.loads(line))
        except (OSError, json.JSONDecodeError) as e:
            raise AuditError(f"读取审计日志失败：{e}") from e
        return records[-n:]

    def _write(self, entry: dict) -> None:
        """内部写入方法。带 fcntl 文件锁 + fsync。"""
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except (OSError, ValueError, TypeError) as e:
            raise AuditError(
                f"审计写入失败（ESAE 应停止）：{e}"
            ) from e
