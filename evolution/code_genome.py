"""CodeGenome — 代码级基因组。

一个 CodeGenome = 一组对 .py 文件的修改方案。
每个修改是原子性的：改一行 / 插一行 / 删一行。
"""

from __future__ import annotations
import ast
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CodeChange:
    """一次原子性的代码修改。"""
    file_path: str            # kernel/daemon.py 等
    change_type: str          # modify_line / insert_line / delete_line / insert_after / insert_before
    target_line: int          # 修改的行号
    old_text: str = ""        # 原代码（modify_line/delete_line 需要）
    new_text: str = ""        # 新代码（modify_line/insert_line 需要）
    context_before: str = ""  # 目标行前一行（用于定位）
    context_after: str = ""   # 目标行后一行（用于定位）
    metadata: dict = None     # 额外信息（策略类型等）

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "change_type": self.change_type,
            "target_line": self.target_line,
            "old_text": self.old_text,
            "new_text": self.new_text,
            "context_before": self.context_before,
            "context_after": self.context_after,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CodeChange":
        return cls(**d)


@dataclass
class CodeGenome:
    """代码基因组 = 一组修改 + 元信息。"""
    genome_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    changes: list[CodeChange] = field(default_factory=list)
    version: int = 0
    fitness: float = 0.0
    parent_ids: list[str] = field(default_factory=list)
    generation: int = 0
    stable: bool = True

    def to_dict(self) -> dict:
        return {
            "genome_id": self.genome_id,
            "changes": [c.to_dict() for c in self.changes],
            "version": self.version,
            "fitness": self.fitness,
            "parent_ids": self.parent_ids,
            "generation": self.generation,
            "stable": self.stable,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CodeGenome":
        return cls(
            genome_id=d.get("genome_id", ""),
            changes=[CodeChange.from_dict(c) for c in d.get("changes", [])],
            version=d.get("version", 0),
            fitness=d.get("fitness", 0.0),
            parent_ids=d.get("parent_ids", []),
            generation=d.get("generation", 0),
            stable=d.get("stable", True),
        )

    @classmethod
    def empty(cls) -> "CodeGenome":
        """空基因组：无任何修改。用于第 0 代基线。"""
        return cls()

    def describe(self) -> str:
        parts = [
            f"CodeGenome v{self.version}",
            f"fitness={self.fitness:.4f}",
            f"gen={self.generation}",
            f"changes={len(self.changes)}",
        ]
        if self.parent_ids:
            parts.append(f"parents={self.parent_ids[:2]}")
        return " | ".join(parts)


# ── AST 安全检查 ──────────────────────────────────

_DANGEROUS_FUNCTIONS = frozenset({
    "exec", "eval", "compile",
    "__import__",
    "os.system", "os.popen", "subprocess.Popen",
    "subprocess.call", "subprocess.run",
})

_DANGEROUS_MODULES = frozenset({
    "ctypes", "socket", "fcntl", "pty",
    "crypt", "grp", "spwd",
})


def ast_check(code: str) -> tuple[bool, str]:
    """AST 安全检查：拒绝危险代码模式。

    Returns:
        (通过?, 原因)
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"语法错误: {e}"

    for node in ast.walk(tree):
        # exec/eval/compile
        if isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = f"{ast.dump(node.func.value)}.{node.func.attr}"

            if func_name in ("exec", "eval", "compile"):
                return False, f"禁止运行时代码生成: {func_name}"

            # __import__
            if func_name == "__import__":
                return False, "禁止动态导入: __import__"

        # os.system 等（通过 Name 调用）
        if isinstance(node, ast.Attribute):
            if (isinstance(node.value, ast.Name) and node.value.id == "os"
                    and node.attr in ("system", "popen")):
                return False, f"禁止系统调用: os.{node.attr}"

            if (isinstance(node.value, ast.Name) and node.value.id == "subprocess"
                    and node.attr in ("Popen", "call", "run")):
                return False, f"禁止子进程: subprocess.{node.attr}"

    return True, "通过"


def simple_ast_check(code: str) -> bool:
    """简化版安全检查（用于快速过滤）。"""
    ok, _ = ast_check(code)
    return ok
