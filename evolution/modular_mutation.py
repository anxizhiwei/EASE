"""模块化突变引擎 — 从代码AST中自动提取原子操作并类型安全组合。

核心流程：
  1. ExtractorLayer: 解析源码AST → 提取原子操作块（AtomicBlock）
     原子类型: method_call / attr_assign / condition / log / expression
  2. TypeIndexer: 分析 self.xxx 属性的类型签名
  3. ComposerLayer: 类型兼容的原子操作组合成新方法体
  4. Integration: 与 evolution/code_mutation.py 的 CodeMutationSelector 对接

参考:
  - ease_phase2_modular_mutation.md (Pro 设计方案)
  - modular_mutation_design.md (Kimi 设计)
  - evolution/atomic_op.py (现有 MVP)
  - evolution/code_mutation.py (现有选择器)

Design Philosophy:
  - 不求完美类型推导，只求大部分情况够用
  - 组合失败最多导致个体被淘汰，不会炸系统
  - 短序列优先（2-4 原子），搜索空间可控制
  - 全程操作 AST，最后 unparse 出文本
"""

from __future__ import annotations
import ast
import random
from dataclasses import dataclass, field
from typing import Optional

from .code_genome import CodeChange


# ═══════════════════════════════════════════════════════════
# 第1层 — 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class AtomicBlock:
    """从代码中提取的一个原子操作。

    原子类型:
      - method_call: self.xxx() 方法调用
      - attr_assign: self.xxx = y 属性赋值
      - condition: if ... 条件判断
      - log: self._log(...) 日志输出
      - expression: 运算/表达式语句
    """
    name: str                    # 操作名 (如 "_write_heartbeat_files")
    node: ast.AST                # AST 节点
    atom_type: str               # method_call / attr_assign / condition / log / expression
    type_signature: str          # 类型签名 (用于组合匹配)
    source_line: int = 0
    source_code: str = ""
    reads: set[str] = field(default_factory=set)   # 读取的 self.xxx 属性
    writes: set[str] = field(default_factory=set)   # 写入的 self.xxx 属性


@dataclass
class AtomicPattern:
    """一组可组合的原子操作模式。"""
    blocks: list[AtomicBlock]
    structure: str               # 组合结构描述 (sequence / if_guarded / instrumented)
    required_types: list[str]    # 所需的类型


# ═══════════════════════════════════════════════════════════
# 第2层 — 类型推导器
# ═══════════════════════════════════════════════════════════

class TypeIndexer:
    """分析 self.xxx 属性的类型签名。

    三级渐进策略（MVP 用级别 1）：
      1. 命名模式匹配：self.heartbeat.tick_count → "int"
      2. 赋值链跟踪：追踪 __init__ 中的初始化
      3. 运行时采样：通过运行实例获取实际类型（保留）
    """

    # 级别 1: 命名模式匹配
    _PATTERNS: dict[str, str] = {
        "heartbeat.tick_count": "int",
        "heartbeat.success_count": "int",
        "heartbeat.failed_count": "int",
        "heartbeat.last_tick_time": "float",
        "heartbeat.last_success_time": "float",
        "heartbeat.start_time": "float",
        "heartbeat.interval": "float",
        "heartbeat.state": "str",
        "heartbeat.pid": "int",
        "heartbeat": "HeartbeatState",
        # 泛化模式：任何 xxx_count → int
    }

    def __init__(self) -> None:
        self.type_map: dict[str, str] = {}  # "heartbeat.tick_count" → "int"
        self.init_map: dict[str, ast.stmt] = {}  # 初始赋值语句

    # ── 级别 1: 命名模式匹配 ────────────────────────────

    @classmethod
    def infer_by_name(cls, attr_path: str) -> str:
        """通过命名模式推断类型。"""
        if attr_path in cls._PATTERNS:
            return cls._PATTERNS[attr_path]
        # 泛化匹配
        if attr_path.endswith("_count"):
            return "int"
        if attr_path.endswith("_time"):
            return "float"
        if attr_path.startswith("heartbeat."):
            return "Heartbeat"
        return "unknown"

    # ── 级别 2: 从 __init__ 赋值链推导 ───────────────────

    def infer_from_class(self, tree: ast.AST, class_name: str) -> dict[str, str]:
        """从类的 __init__ 中推导属性类型。"""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                        self._scan_init(item)
        return self.type_map

    def _scan_init(self, init_func: ast.FunctionDef) -> None:
        """扫描 __init__ 中的 self.xxx = ... 赋值。"""
        for stmt in init_func.body:
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                for target in targets:
                    path = self._self_attr_path(target)
                    if path:
                        self.init_map[path] = stmt
                        self.type_map[path] = self._infer_literal_type(stmt.value)

    def infer_type(self, attr_path: str) -> str:
        """综合推断：先查 __init__ 推导，再 fallback 到命名模式。"""
        if attr_path in self.type_map:
            return self.type_map[attr_path]
        return self.infer_by_name(attr_path)

    # ── 工具方法 ────────────────────────────────────────

    @staticmethod
    def _self_attr_path(node: ast.AST) -> Optional[str]:
        """提取 self.heartbeat.tick_count → 'heartbeat.tick_count'"""
        if isinstance(node, ast.Attribute):
            parts = []
            while isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value  # type: ignore[assignment]
            if isinstance(node, ast.Name) and node.id == "self":
                return ".".join(reversed(parts))
        return None

    @staticmethod
    def _infer_literal_type(node: ast.AST) -> str:
        """从 AST 字面量节点推断类型。"""
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return "bool"
            elif isinstance(node.value, int):
                return "int"
            elif isinstance(node.value, float):
                return "float"
            elif isinstance(node.value, str):
                return "str"
            elif node.value is None:
                return "NoneType"
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return node.func.id  # HeartbeatState(...) → "HeartbeatState"
        elif isinstance(node, ast.Name) and node.id in ("True", "False"):
            return "bool"
        elif isinstance(node, ast.UnaryOp) and isinstance(node.operand, ast.Constant):
            return TypeIndexer._infer_literal_type(node.operand)
        elif isinstance(node, ast.List):
            return "list"
        elif isinstance(node, ast.Dict):
            return "dict"
        elif isinstance(node, ast.Name) and node.id in ("True", "False"):
            return "bool"
        return "unknown"


# ═══════════════════════════════════════════════════════════
# 第3层 — 原子操作提取器
# ═══════════════════════════════════════════════════════════

class ExtractorLayer:
    """从方法体中提取原子操作块。

    提取规则：
    - 每个 Expr( Call ) → method_call (含 log 检测)
    - 每个 Assign/AnnAssign → attr_assign
    - 每个 AugAssign → expression
    - 每个 If → condition
    - 忽略: Pass, docstring, Return(无副作用的)
    """

    def __init__(self, type_indexer: Optional[TypeIndexer] = None) -> None:
        self.indexer = type_indexer or TypeIndexer()

    # ── 公开接口 ────────────────────────────────────────

    def extract_atomics(self, source: str,
                        class_name: str = "ESAEDaemon",
                        method_name: str = "tick") -> list[AtomicBlock]:
        """从指定类方法的源码中提取所有原子操作。"""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        # 先运行类型推导
        self.indexer.infer_from_class(tree, class_name)

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == method_name:
                        source_lines = source.splitlines(keepends=True)
                        return self._extract_body(item.body, source_lines, method_name)
        return []

    def extract_all_methods(self, source: str,
                            class_name: str = "ESAEDaemon") -> dict[str, list[AtomicBlock]]:
        """提取类中所有方法的原子操作。"""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return {}

        self.indexer.infer_from_class(tree, class_name)
        source_lines = source.splitlines(keepends=True)
        result: dict[str, list[AtomicBlock]] = {}

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        blocks = self._extract_body(item.body, source_lines, item.name)
                        if blocks:
                            result[item.name] = blocks
        return result

    def extract_types(self, source: str,
                      class_name: str = "ESAEDaemon") -> dict[str, str]:
        """提取类中所有 self.xxx 属性的类型签名。"""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return {}
        indexer = TypeIndexer()
        return indexer.infer_from_class(tree, class_name)

    # ── 内部提取逻辑 ────────────────────────────────────

    def _extract_body(self, body: list[ast.stmt],
                      source_lines: list[str],
                      method_name: str = "") -> list[AtomicBlock]:
        blocks: list[AtomicBlock] = []
        for i, stmt in enumerate(body):
            block = self._stmt_to_block(stmt, source_lines, method_name, i)
            if block:
                blocks.append(block)
        return blocks

    def _stmt_to_block(self, stmt: ast.stmt,
                       lines: list[str],
                       method_name: str,
                       idx: int) -> Optional[AtomicBlock]:
        """将单个 AST 语句转为 AtomicBlock。"""
        start = getattr(stmt, "lineno", 0) - 1
        end = getattr(stmt, "end_lineno", start + 1) or (start + 1)
        raw = "".join(lines[start:end]) if start >= 0 else ast.unparse(stmt)
        if not raw.strip():
            return None

        # 去除公共缩进：以第一非空行的缩进为准
        norm_lines = raw.splitlines(keepends=True)
        first_indent = ""
        for l in norm_lines:
            if l.strip():
                first_indent = l[:len(l) - len(l.lstrip())]
                break
        if first_indent:
            prefix_len = len(first_indent)
            code = "".join(l[prefix_len:] if l.strip() else "\n" for l in norm_lines)
        else:
            code = raw
        code = code.strip()

        reads: set[str] = set()
        writes: set[str] = set()
        atom_type = "expression"

        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            atom_type = "method_call"
            self._extract_io(stmt, reads, writes)
            # 检测 log
            call_name = self._call_name(stmt.value)
            if call_name and "log" in call_name.lower():
                atom_type = "log"

        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            atom_type = "attr_assign"
            self._extract_io(stmt, reads, writes)

        elif isinstance(stmt, ast.AugAssign):
            atom_type = "expression"
            self._extract_io(stmt, reads, writes)

        elif isinstance(stmt, ast.If):
            atom_type = "condition"
            self._extract_io(stmt, reads, writes)

        elif isinstance(stmt, (ast.Pass, ast.Raise, ast.Return)):
            # 忽略无副作用的语句
            if isinstance(stmt, ast.Return):
                if stmt.value is None:
                    return None
                # 带返回值的 return 当作 expression
                self._extract_io(stmt, reads, writes)
            else:
                return None

        block_name = self._name_for(stmt)
        type_sig = self._compute_type_signature(atom_type, reads, writes)

        return AtomicBlock(
            name=block_name or f"stmt_{idx}",
            node=stmt,
            atom_type=atom_type,
            type_signature=type_sig,
            source_line=start + 1,
            source_code=code,
            reads=reads,
            writes=writes,
        )

    # ── 辅助方法 ────────────────────────────────────────

    @staticmethod
    def _call_name(call: ast.Call) -> str:
        """提取方法调用的名字。"""
        if isinstance(call.func, ast.Attribute):
            if isinstance(call.func.value, ast.Name):
                return f"{call.func.value.id}.{call.func.attr}"
            return call.func.attr
        elif isinstance(call.func, ast.Name):
            return call.func.id
        return ""

    def _name_for(self, stmt: ast.stmt) -> str:
        """为语句生成一个可读的名称。"""
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            return self._call_name(stmt.value)
        if isinstance(stmt, ast.Assign):
            parts = []
            for t in stmt.targets:
                p = self._attr_path_str(t)
                if p:
                    parts.append(p)
            return " = ".join(parts) if parts else "assign"
        if isinstance(stmt, ast.AugAssign):
            p = self._attr_path_str(stmt.target)
            return f"{p} {type(stmt.op).__name__}=" if p else "aug_assign"
        if isinstance(stmt, ast.If):
            return f"if_{type(stmt.test).__name__}"
        return ""

    def _extract_io(self, node: ast.AST, reads: set[str], writes: set[str]) -> None:
        """递归提取 self.xxx 的读写依赖。"""
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name) and child.value.id == "self":
                path = self._attr_path_str(child)
                if path:
                    if self._is_write_context(child, node):
                        writes.add(path)
                    else:
                        reads.add(path)

    @staticmethod
    def _attr_path_str(node: ast.AST) -> str:
        """提取 self.heartbeat.tick_count → 'heartbeat.tick_count'"""
        if isinstance(node, ast.Attribute):
            parts = []
            while isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value  # type: ignore[assignment]
            if isinstance(node, ast.Name) and node.id == "self":
                return ".".join(reversed(parts))
            return ".".join(reversed(parts))
        return ""

    @staticmethod
    def _is_write_context(attr: ast.Attribute, root: ast.AST) -> bool:
        """判断这个 Attribute 是否在赋值左侧。"""
        for node in ast.walk(root):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Attribute):
                        if ast.dump(attr) == ast.dump(target):
                            return True
            elif isinstance(node, ast.AugAssign):
                if isinstance(node.target, ast.Attribute):
                    if ast.dump(attr) == ast.dump(node.target):
                        return True
        return False

    def _compute_type_signature(self, atom_type: str,
                                reads: set[str],
                                writes: set[str]) -> str:
        """计算类型签名（用于组合匹配）。"""
        parts: list[str] = [atom_type]
        for r in sorted(reads):
            t = self.indexer.infer_type(r)
            parts.append(f"r:{r}:{t}")
        for w in sorted(writes):
            t = self.indexer.infer_type(w)
            parts.append(f"w:{w}:{t}")
        return "|".join(parts)


# ═══════════════════════════════════════════════════════════
# 第4层 — 结构守卫
# ═══════════════════════════════════════════════════════════

class StructureGuard:
    """语法正确性保护。

    规则：
    - 不能两个 return 串行（return 后不能跟其他可执行语句）
    - if 后的原子操作不能是 condition（不允许嵌套 if 在 if 体内）
    - 写操作必须在读操作之前
    """

    @staticmethod
    def validate(ordered: list[AtomicBlock]) -> bool:
        """验证组合顺序的语法正确性。"""
        for i in range(len(ordered) - 1):
            curr = ordered[i]
            nxt = ordered[i + 1]

            # 规则 1: return 后不能跟可执行语句
            if isinstance(curr.node, ast.Return):
                if not isinstance(nxt.node, (ast.Pass, ast.Raise)):
                    return False

            # 规则 2: condition 后跟 condition = 扁平 if 链（允许）
            # 但 condition 后不能是另一个 condition 的顶层，除非是 or else

        # 规则 3: 写操作必须在读操作之前
        written_so_far: set[str] = set()
        for block in ordered:
            needed = block.reads - written_so_far
            # 允许缺失（用默认值兜底），但严重缺失警告
            if needed and not block.writes:
                # 如果这个块只读不写且依赖未提供的属性，标记为可疑但不拒绝
                pass
            written_so_far.update(block.writes)

        return True

    @staticmethod
    def topological_sort(blocks: list[AtomicBlock]) -> list[AtomicBlock]:
        """简单拓扑排序：写者在读者前（贪心相邻交换）。"""
        sorted_blocks = list(blocks)
        changed = True
        while changed:
            changed = False
            for i in range(len(sorted_blocks) - 1):
                for j in range(i + 1, len(sorted_blocks)):
                    # 如果 j 的写入在 i 的读取中，需要交换
                    if sorted_blocks[j].writes & sorted_blocks[i].reads:
                        sorted_blocks[i], sorted_blocks[j] = sorted_blocks[j], sorted_blocks[i]
                        changed = True
        return sorted_blocks


# ═══════════════════════════════════════════════════════════
# 第5层 — 类型匹配器
# ═══════════════════════════════════════════════════════════

class TypeMatcher:
    """类型兼容性检查。

    规则：
    1. A 的 writes 与 B 的 reads 有交集 → 类型兼容
    2. 同属性名的 reads/writes 视为同类型兼容
    3. 空 reads/writes 可以匹配任何位置
    """

    @classmethod
    def is_compatible(cls, producer: AtomicBlock, consumer: AtomicBlock) -> bool:
        """检查 producer 的输出是否兼容 consumer 的输入。

        规则：空 reads/writes 可以匹配任何位置（无副作用的原子兼容一切）。
        """
        # 消费者无 reads → 不依赖前置原子 → 兼容一切
        if not consumer.reads:
            return True
        # producer 写了什么 → consumer 读了什么
        if producer.writes & consumer.reads:
            return True
        # 类型签名匹配
        if producer.type_signature and consumer.type_signature:
            p_types = set(cls._extract_types(producer.type_signature, "w:"))
            c_types = set(cls._extract_types(consumer.type_signature, "r:"))
            if p_types & c_types:
                return True
        return False

    @classmethod
    def chain_compatible(cls, chain: list[AtomicBlock]) -> bool:
        """验证整个链的类型兼容性。"""
        if len(chain) < 2:
            return True
        for i in range(len(chain) - 1):
            if not cls.is_compatible(chain[i], chain[i + 1]):
                return False
        return True

    @staticmethod
    def _extract_types(type_sig: str, prefix: str) -> list[str]:
        """从类型签名中提取指定前缀的字段类型。"""
        types: list[str] = []
        for part in type_sig.split("|"):
            if part.startswith(prefix):
                # r:heartbeat.tick_count:int → int
                segments = part.split(":")
                if len(segments) >= 3:
                    types.append(segments[-1])  # 最后一个 segment 是类型
        return types


# ═══════════════════════════════════════════════════════════
# 第6层 — 组合器
# ═══════════════════════════════════════════════════════════

class ComposerLayer:
    """将原子操作组合成新方法体。

    组合规则：
    1. 类型链约束：A 的 writes 必须匹配 B 的 reads
    2. 短序列优先：2-4 个原子（权重递减）
    3. 同方法优先：优先来自同一方法的原子
    4. 结构保护：使用 StructureGuard 验证
    """

    _LENGTH_WEIGHTS: dict[int, float] = {
        2: 0.50,
        3: 0.30,
        4: 0.15,
        5: 0.05,
    }

    def __init__(self, atomic_pool: dict[str, list[AtomicBlock]]) -> None:
        # atomic_pool: method_name → [AtomicBlock, ...]
        self.pool = atomic_pool
        self.flat_pool: list[AtomicBlock] = []
        for blocks in atomic_pool.values():
            self.flat_pool.extend(blocks)

    def compose(self, method_name: str = "tick",
                rng: Optional[random.Random] = None) -> Optional[str]:
        """从原子池中组合一段新代码。"""
        if not self.flat_pool:
            return None
        if rng is None:
            rng = random.Random()

        length = self._pick_length(rng)
        if length < 2:
            return None

        # 从同一方法中优先选取原子
        pool = self.pool.get(method_name, self.flat_pool)
        if len(pool) < 2:
            pool = self.flat_pool
        if len(pool) < 2:
            return None

        # 多次尝试寻找有效组合
        for _ in range(30):
            chain = self._try_compose(pool, length, rng)
            if chain and self._validate_composition(chain):
                return self._render_chain(chain)

        return None

    def _try_compose(self, pool: list[AtomicBlock],
                     length: int,
                     rng: random.Random) -> Optional[list[AtomicBlock]]:
        """尝试一次组合。"""
        # 起始原子（优先选有 writes 的操作）
        starters = [a for a in pool if a.writes and a.atom_type in ("attr_assign", "method_call")]
        if not starters:
            starters = pool
        if not starters:
            return None

        selected: list[AtomicBlock] = [rng.choice(starters)]
        used: set[int] = {id(selected[0])}

        for _ in range(length - 1):
            prev = selected[-1]
            # 找类型兼容且未使用的原子
            candidates = [a for a in pool
                          if id(a) not in used
                          and TypeMatcher.is_compatible(prev, a)]
            if not candidates:
                # 放宽：同类型即可
                candidates = [a for a in pool
                              if id(a) not in used
                              and a.atom_type != prev.atom_type]
            if not candidates:
                break
            chosen = rng.choice(candidates)
            selected.append(chosen)
            used.add(id(chosen))

        if len(selected) < 2:
            return None
        return selected

    def _validate_composition(self, chain: list[AtomicBlock]) -> bool:
        """验证组合的有效性。"""
        # 1. 长度检查
        if len(chain) < 2 or len(chain) > 5:
            return False
        # 2. 类型链检查
        if not TypeMatcher.chain_compatible(chain):
            return False
        # 3. 结构保护
        ordered = StructureGuard.topological_sort(chain)
        if not StructureGuard.validate(ordered):
            return False
        return True

    @staticmethod
    def _render_chain(chain: list[AtomicBlock]) -> str:
        """将原子操作链渲染成代码文本。

        每个原子块的 source_code 需要先去除公共缩进，
        确保所有原子从 0 列开始，再由调用方统一添加缩进。
        """
        ordered = StructureGuard.topological_sort(chain)

        def _deindent(block: str) -> str:
            lines = block.splitlines(keepends=True)
            indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
            if not indents:
                return block
            m = min(indents)
            return "".join(l[m:] for l in lines)

        return "\n".join(_deindent(a.source_code) for a in ordered if a.source_code)

    def _pick_length(self, rng: random.Random) -> int:
        """按权重选择组合长度。"""
        lengths = list(self._LENGTH_WEIGHTS.keys())
        weights = list(self._LENGTH_WEIGHTS.values())
        return rng.choices(lengths, weights=weights)[0]


# ═══════════════════════════════════════════════════════════
# 第7层 — 集成接口
# ═══════════════════════════════════════════════════════════

def compose_mutation(source: str, lines: list[str],
                     cls: str = "ESAEDaemon", method: str = "tick",
                     rng: Optional[random.Random] = None) -> Optional[CodeChange]:
    """模块化组合变异 — 与 CodeMutationSelector 对接。

    从代码 AST 中提取原子操作 → 类型安全组合 → 插入目标方法体。
    如果 AST 提取失败自动 fallback 到 None（由上层选择器回退到模板方案）。

    Returns:
        CodeChange 或 None（组合失败/语法错误）
    """
    if rng is None:
        rng = random.Random()

    # 引用 code_mutation 的工具函数（延迟导入避免循环依赖）
    from .code_mutation import _method_body_range, _indent

    ri = _method_body_range(source, cls, method)
    if not ri:
        return None

    start_line, end_line, indent = ri

    # 提取原子操作（自动 fallback）
    extractor = ExtractorLayer()
    atomics = extractor.extract_atomics(source, cls, method)

    # 如果提取失败或原子太少，fallback
    if len(atomics) < 3:
        # 尝试从所有方法提取
        all_by_method = extractor.extract_all_methods(source, cls)
        flat_all: list[AtomicBlock] = []
        for blks in all_by_method.values():
            flat_all.extend(blks)
        if len(flat_all) < 3:
            return None
        composer = ComposerLayer(all_by_method)
    else:
        composer = ComposerLayer({method: atomics})

    code = composer.compose(method, rng)
    if not code:
        return None

    # AST 语法验证
    try:
        ast.parse(code)
    except SyntaxError:
        return None

    # 安全检查
    from .code_genome import ast_check
    ok, _ = ast_check(code)
    if not ok:
        return None

    # 缩进并插入
    block = _indent(code, indent)

    insert_at = rng.randrange(start_line - 1, end_line)
    new_lines = lines.copy()
    new_lines.insert(insert_at, block)

    try:
        ast.parse("".join(new_lines))
    except SyntaxError:
        return None

    return CodeChange(
        file_path="kernel/daemon.py",
        change_type="insert_after",
        target_line=insert_at,
        old_text="", new_text=block,
        metadata={"method": method, "action": "modular_compose",
                  "op_count": len(code.splitlines()),
                  "op_types": list(set(a.atom_type for a in
                    composer.pool.get(method, composer.flat_pool)[:5]))},
    )


# ═══════════════════════════════════════════════════════════
# 第8层 — 便捷引导
# ═══════════════════════════════════════════════════════════

def bootstrap(source: str, class_name: str = "ESAEDaemon") -> ComposerLayer:
    """从源码一键启动模块化突变引擎。

    1. 提取所有方法的原子操作
    2. 构建类型索引
    3. 返回 ComposerLayer 实例

    Usage:
        source = Path("kernel/daemon.py").read_text()
        composer = bootstrap(source)
        new_code = composer.compose("tick")
    """
    extractor = ExtractorLayer()
    pool = extractor.extract_all_methods(source, class_name)
    return ComposerLayer(pool)
