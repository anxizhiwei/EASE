"""CodeSandbox — 代码级沙盒验证。

在 Docker 容器中验证代码修改：
1. AST 语法校验
2. SafetyGuard 安全检查
3. 运行全部 pytest 测试
4. 测试覆盖率 ≥90%
5. 通过 → 可以写入实际文件
"""

from __future__ import annotations
import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from .code_genome import CodeChange, CodeGenome, ast_check


# ── 安全名单（允许修改的文件） ─────────────────────

_ALLOWED_FILES = frozenset({
    "kernel/daemon.py",
    "kernel/fsm.py",
    "kernel/circuit.py",
    "kernel/guard.py",
    "kernel/audit.py",
})


class CodeSandbox:
    """代码沙盒：验证修改是否安全。"""

    def __init__(self, esae_home: Optional[Path] = None,
                 timeout: int = 30):
        self.esae_home = esae_home or Path.home() / ".hermes" / "esae"
        self.timeout = timeout

    def validate_change(self, change: CodeChange) -> tuple[bool, str]:
        """验证单次修改。

        Returns:
            (通过?, 原因)
        """
        # 1. 文件路径安全检查（支持相对路径和绝对路径）
        fp = change.file_path.replace("\\", "/")
        if self.esae_home:
            # 尝试转成相对路径
            try:
                rel = Path(fp).relative_to(self.esae_home)
                fp = str(rel)
            except (ValueError, TypeError):
                pass
        if fp not in _ALLOWED_FILES and not any(
            fp.startswith(allowed) for allowed in _ALLOWED_FILES
        ):
            return False, f"不允许修改此文件: {fp}（仅限 kernel/ 下的文件）"

        # 2. 在实际文件上应用变更
        full_path = self.esae_home / change.file_path
        if not full_path.exists():
            return False, f"文件不存在: {full_path}"

        lines = full_path.read_text().splitlines(keepends=True)
        line_idx = change.target_line - 1

        if line_idx < 0 or line_idx >= len(lines):
            return False, f"行号越界: {change.target_line}"

        if change.change_type == "modify_line":
            lines[line_idx] = change.new_text
        elif change.change_type == "delete_line":
            lines[line_idx] = ""
        elif change.change_type == "insert_after":
            lines.insert(line_idx + 1, change.new_text)
        elif change.change_type == "insert_before":
            lines.insert(line_idx, change.new_text)
        else:
            return False, f"未知修改类型: {change.change_type}"

        new_content = "".join(lines)

        # 3. AST 安全检查
        ok, reason = ast_check(new_content)
        if not ok:
            return False, f"AST 检查未通过: {reason}"

        return True, "通过"

    def validate_genome(self, genome: CodeGenome) -> tuple[bool, str]:
        """验证整个 genome（所有修改）。"""
        for i, change in enumerate(genome.changes):
            ok, reason = self.validate_change(change)
            if not ok:
                return False, f"修改 #{i} 验证失败: {reason}"
        return True, f"全部 {len(genome.changes)} 个修改通过"

    def run_tests_in_docker(self, genome: CodeGenome) -> dict:
        """（预留）在 Docker 中运行测试验证。

        需要 Docker 镜像 ease-sandbox 已构建。
        """
        # TODO: 实现 Docker 内测试运行
        return {"passed": 0, "failed": 0, "total": 0}
