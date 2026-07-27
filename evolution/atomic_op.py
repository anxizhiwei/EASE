"""EASE_MVP — 模块化突变引擎（Atomic Operation Composer）。

核心能力：
1. 从 Python 方法中自动提取原子操作（赋值、调用、条件、表达式）
2. 基于类型匹配自由组合原子操作成新方法体
3. 与现有模板方案并行运行（渐进式过渡）

设计参考：Phase 2 四模型联合评审结论
- 类型系统用命名模式匹配（MVP 够用）
- 搜索空间用类型链 + 短序列（2-4 原子）控制
- 安全护栏用 AST + 运行时双重验证
"""

from __future__ import annotations
import ast
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── 原子操作 ──────────────────────────────────────

@dataclass
class AtomicOp:
    """一个不可拆分的原子代码操作。"""
    op_type: str          # assign / call / if / log / expression
    code: str              # 实际代码文本
    reads: list[str]       # 读取的变量/属性
    writes: list[str]      # 写入的变量/属性
    call_name: str = ""    # 调用的方法名（如果是call类型）
    source_line: int = 0   # 来源行号


# ── 原子操作提取器 ────────────────────────────────

class AtomicExtractor:
    """从 Python 源码中提取原子操作。

    用 AST 解析方法体 → 分解为原子操作 → 标记读写类型。
    类型推断使用命名模式匹配（self.heartbeat.xxx → Heartbeat 类型）。
    """

    _TYPE_PATTERNS: dict[str, str] = {
        "heartbeat": "Heartbeat",
        "tick_count": "int",
        "success_count": "int",
        "failed_count": "int",
        "last_tick_time": "float",
        "last_success_time": "float",
        "interval": "float",
        "state": "str",
        "pid": "int",
    }

    @classmethod
    def from_method(cls, source: str, class_name: str = "ESAEDaemon",
                    method_name: str = "tick") -> list[AtomicOp]:
        """从方法中提取原子操作。"""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        ops = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == method_name:
                        lines = source.splitlines(keepends=True)
                        for stmt in item.body:
                            op = cls._stmt_to_op(stmt, lines)
                            if op:
                                ops.append(op)
        return ops

    @classmethod
    def from_file(cls, file_path: str, class_name: str = "ESAEDaemon",
                  method_name: str = "tick") -> list[AtomicOp]:
        """从文件中提取原子操作。"""
        path = Path(file_path)
        if not path.exists():
            return []
        return cls.from_method(path.read_text(), class_name, method_name)

    @classmethod
    def _stmt_to_op(cls, stmt: ast.AST, lines: list[str]) -> Optional[AtomicOp]:
        """将 AST 语句转为原子操作。"""
        start = stmt.lineno - 1
        end = stmt.end_lineno if stmt.end_lineno else start + 1
        code = "".join(lines[start:end]).strip()

        reads: list[str] = []
        writes: list[str] = []
        op_type = "expression"
        call_name = ""

        if isinstance(stmt, ast.Assign):
            op_type = "assign"
            for target in stmt.targets:
                writes.append(cls._extract_name(target))
            for val_node in ast.walk(stmt.value):
                r = cls._extract_name(val_node)
                if r and r not in writes:
                    reads.append(r)

        elif isinstance(stmt, ast.Expr):
            if isinstance(stmt.value, ast.Call):
                op_type = "call"
                call_name = cls._extract_call_name(stmt.value)
                for arg in stmt.value.args:
                    r = cls._extract_name(arg)
                    if r and r not in reads:
                        reads.append(r)
                for kw in stmt.value.keywords:
                    r = cls._extract_name(kw.value)
                    if r and r not in reads:
                        reads.append(r)

        elif isinstance(stmt, ast.If):
            op_type = "if"
            for node in ast.walk(stmt.test):
                r = cls._extract_name(node)
                if r and r not in reads:
                    reads.append(r)

        elif isinstance(stmt, ast.Pass):
            return None

        return AtomicOp(
            op_type=op_type,
            code=code,
            reads=reads,
            writes=writes,
            call_name=call_name,
            source_line=start + 1,
        )

    @classmethod
    def _extract_name(cls, node: ast.AST) -> str:
        """从 AST 节点提取变量/属性名。"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name):
                return f"{node.value.id}.{node.attr}"
            elif isinstance(node.value, ast.Attribute):
                return f"{cls._extract_name(node.value)}.{node.attr}"
        return ""

    @classmethod
    def _extract_call_name(cls, call: ast.Call) -> str:
        """从 AST 调用节点提取方法名。"""
        if isinstance(call.func, ast.Attribute):
            return f"{cls._extract_name(call.func.value)}.{call.func.attr}"
        elif isinstance(call.func, ast.Name):
            return call.func.id
        return ""


# ── 类型匹配器 ────────────────────────────────────

class TypeMatcher:
    """基于命名模式的类型匹配器。

    规则：
    - self.heartbeat.xxx → 类型为 Heartbeat
    - self.heartbeat.tick_count → 类型为 int
    - 如果 A 的 writes 包含 B 的 reads → 类型兼容
    """

    @classmethod
    def is_compatible(cls, producer: AtomicOp, consumer: AtomicOp) -> bool:
        """检查 producer 的输出是否兼容 consumer 的输入。"""
        # producer 写了什么 → consumer 读了什么
        shared = set(producer.writes) & set(consumer.reads)
        if shared:
            return True
        # 类型模式匹配
        for w in producer.writes:
            for r in consumer.reads:
                if cls._type_match(w, r):
                    return True
        return False

    @classmethod
    def _type_match(cls, write_var: str, read_var: str) -> bool:
        """检查两个变量是否类型兼容。"""
        # 同一个变量的读写
        if write_var == read_var:
            return True
        # 同一个上下文的属性
        w_parts = write_var.split(".")
        r_parts = read_var.split(".")
        if len(w_parts) >= 2 and len(r_parts) >= 2:
            # self.heartbeat.xxx → self.heartbeat.yyy 兼容
            if w_parts[:-1] == r_parts[:-1]:
                return True
        return False


# ── 组合器 ────────────────────────────────────────

class AtomicComposer:
    """将原子操作组合成连续代码块。

    组合规则：
    1. 类型链约束：A 的 writes 必须匹配 B 的 reads
    2. 短序列优先：2-4 个原子
    3. 同方法优先：优先来自同一方法的原子
    """

    def __init__(self, atomic_pool: list[AtomicOp]):
        self.pool = atomic_pool

    def compose(self, rng: random.Random, max_length: int = 3) -> Optional[str]:
        """从原子池中组合一段代码。

        随机选起始原子 → 按类型匹配链式追加 → 生成代码。
        """
        if not self.pool:
            return None

        length = rng.randrange(2, min(max_length + 1, len(self.pool) + 1))
        selected: list[AtomicOp] = []

        # 选起始原子（优先选 assign 或 if 类型）
        starters = [op for op in self.pool if op.op_type in ("assign", "if", "call")]
        if not starters:
            starters = self.pool
        current = rng.choice(starters)
        selected.append(current)

        # 链式匹配
        for _ in range(length - 1):
            candidates = [op for op in self.pool
                          if op is not current
                          and TypeMatcher.is_compatible(current, op)]
            if not candidates:
                # 无匹配时随机选一个同类型原子
                candidates = [op for op in self.pool if op is not current]
            if not candidates:
                break
            current = rng.choice(candidates)
            selected.append(current)

        # 生成代码
        code = "\n".join(op.code for op in selected)
        return code

    def validate(self, code: str) -> bool:
        """验证组合代码语法正确。"""
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False


# ── 组成变异策略 ──────────────────────────────────

def compose_mutation(source: str, lines: list[str],
                     cls: str = "ESAEDaemon", method: str = "tick",
                     rng: random.Random = None) -> Optional:
    """模块化组合变异：替代模板插入。

    从现有代码提取原子操作 → 随机组合 → 插入方法体。
    """
    if rng is None:
        rng = random.Random()

    from .code_mutation import _method_body_range, _indent

    ri = _method_body_range(source, cls, method)
    if not ri:
        return None

    start_line, end_line, indent = ri

    # 提取原子操作
    ops = AtomicExtractor.from_method(source, cls, method)
    if len(ops) < 3:
        return None

    # 组合
    composer = AtomicComposer(ops)
    code = composer.compose(rng, max_length=3)
    if not code or not composer.validate(code):
        return None

    # 缩进
    block = _indent(code, indent)

    # 插入
    insert_at = rng.randrange(start_line - 1, end_line)
    new_lines = lines.copy()
    new_lines.insert(insert_at, block)

    try:
        ast.parse("".join(new_lines))
    except SyntaxError:
        return None

    from .code_genome import CodeChange
    return CodeChange(
        file_path="kernel/daemon.py",
        change_type="insert_after",
        target_line=insert_at,
        old_text="", new_text=block,
        metadata={"method": method, "action": "compose",
                  "op_count": len(code.splitlines()), "source": "mvp"},
    )
