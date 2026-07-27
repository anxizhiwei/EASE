"""CodeMutation — AST 子树级代码突变（参考 DEAP GP 设计）。

核心操作（全部在 AST 辅助定位 + 原始文本操作，保证缩进正确）：
1. ast_insert    — 在方法体内随机插入模板块
2. ast_uniform   — 用模板块替换随机语句
3. ast_replace   — 替换单个 AST 节点（常数/运算符）
4. ast_shrink    — 移除方法体中的非关键语句
5. duplicate     — 基因复制
"""

from __future__ import annotations
import ast
import random
from typing import Optional

from .code_genome import CodeChange
from .atomic_op import compose_mutation


# ── 模板库 ─────────────────────────────────────────

_TEMPLATES: list[str] = [
    # ── daemon 核心操作 ──
    "self._write_state()",
    "now = time.time()\nself.heartbeat.last_tick_time = now\nself._write_heartbeat_files(now)",
    "self.heartbeat.success_count += 1\nself.heartbeat.last_success_time = time.time()\nself._write_success_file(self.heartbeat.last_success_time)",
    "self.heartbeat.failed_count = 0",
    # 写心跳+成功文件（完整恢复功能用）
    "now = time.time()\nself.heartbeat.last_tick_time = now\nself._write_heartbeat_files(now)\nself.heartbeat.success_count += 1\nself.heartbeat.last_success_time = now\nself._write_success_file(now)",

    # ── 健康检查 ──
    ("if time.time() - self.heartbeat.last_success_time > self.interval * 3:\n"
     "    self._log('health: no recent success')\n"
     "    self.heartbeat.state = 'degraded'"),
    ("if self.heartbeat.failed_count > 3:\n"
     "    self._log('health: too many failures')\n"
     "    self.heartbeat.state = 'degraded'"),
    ("if self.heartbeat.state == 'running' and self.heartbeat.tick_count > 10:\n"
     "    self._log('health: running fine')"),

    # ── 恢复操作 ──
    ("if self.heartbeat.state == 'degraded' and self.heartbeat.failed_count == 0:\n"
     "    self.heartbeat.state = 'running'\n"
     "    self._log('recovery: restored to running')"),
    ("if self.heartbeat.state == 'degraded' and self.heartbeat.tick_count > self.heartbeat.failed_count * 2:\n"
     "    self.heartbeat.state = 'running'"),
    ("if self.heartbeat.state == 'starting':\n"
     "    self.heartbeat.state = 'running'\n"
     "    self._log('init: daemon ready')"),

    # ── 监控日志 ──
    ("if self.heartbeat.tick_count % 10 == 0:\n"
     "    self._log('tick: %s successes=%s failures=%s state=%s',\n"
     "        self.heartbeat.tick_count, self.heartbeat.success_count,\n"
     "        self.heartbeat.failed_count, self.heartbeat.state)"),
    ("if self.heartbeat.tick_count % 50 == 0:\n"
     "    self._log('status report: %s ticks in %.1fs',\n"
     "        self.heartbeat.tick_count,\n"
     "        time.time() - self.heartbeat.last_tick_time)"),

    # ── 哨兵/安全 ──
    "if self.heartbeat.failed_count > self.heartbeat.success_count:\n    self.heartbeat.state = 'degraded'\n    self._write_state()",
    ("if self.heartbeat.tick_count % 100 == 0:\n"
     "    self._log('self-check: pid=%s state=%s', os.getpid(), self.heartbeat.state)"),
    "self._log('progress: tick=%s', self.heartbeat.tick_count)",

    # ── 状态检查 ──
    (f"if self.heartbeat.state == 'degraded' and self.heartbeat.tick_count > 100:\n"
     f"    self._log('degraded for too long, forcing reset')\n"
     f"    self.heartbeat.state = 'running'\n"
     f"    self.heartbeat.failed_count = 0"),
    f"if self.heartbeat.tick_count == 1:\n    self._log('first tick completed')",
    (f"if self.heartbeat.tick_count % 10 == 0 and self.heartbeat.failed_count > 0:\n"
     f"    self._log('failure rate: %.1f%%', self.heartbeat.failed_count / self.heartbeat.tick_count * 100)"),

    # ── 性能跟踪 ──
    f"self._log('elapsed: %.1fs', time.time() - self.heartbeat.last_tick_time)",
    f"self._log('stats: ticks=%s ok=%s err=%s', self.heartbeat.tick_count, self.heartbeat.success_count, self.heartbeat.failed_count)",

    # ── 通用操作（适用于任何方法上下文） ──
    # 数据存储 & 日志
    f"self._events.append((time.time(), str(event_type)))",
    f"self._events.append((time.time(), ''))",
    f"self._log('event recorded: %s', event_type)",

    # 统计计算
    f"cutoff = time.time() - minutes * 60",
    f"stats = {{}}",
    f"for ts, et in self._events:\n    if ts >= cutoff:\n        stats[et] = stats.get(et, 0) + 1",
    f"return stats",

    # 安全处理
    f"if event_type is None:\n    event_type = ''",
    f"if not isinstance(event_type, str):\n    event_type = str(event_type)",

    # 通用 __init__ 兼容属性操作
    f"self._events = []",
    f"self._log('events count: %d', len(self._events))",
]


# ── AST 辅助定位 ──────────────────────────────────

def _method_body_range(source: str, cls: str, method: str):
    """用 AST 定位方法体的行号范围和缩进。

    Returns (第一行号1-based, 最后行号1-based, 方法体缩进) 或 None。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method and item.body:
                    first = item.body[0]
                    last = item.body[-1]
                    s = first.lineno
                    e = last.end_lineno or last.lineno
                    lines = source.splitlines(keepends=True)
                    indent = lines[s - 1][:len(lines[s - 1]) - len(lines[s - 1].lstrip())]
                    return (s, e, indent)
    return None


def _indent(block: str, indent: str) -> str:
    """给代码块每行增加缩进。"""
    return "".join(indent + l if l.strip() else "\n" for l in block.splitlines(keepends=True))


def _deindent(block: str) -> str:
    """去除代码块的公共缩进。"""
    lines = block.splitlines(keepends=True)
    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    if not indents:
        return block
    m = min(indents)
    return "".join(l[m:] for l in lines)


# ── 策略 1: AST 插入 ─────────────────────────────

def ast_insert(source: str, lines: list[str],
               cls: str = "ESAEDaemon", method: str = "tick",
               rng: random.Random = None) -> Optional[CodeChange]:
    """在方法体内随机位置插入一个模板块。"""
    if rng is None:
        rng = random.Random()
    ri = _method_body_range(source, cls, method)
    if not ri:
        return None
    start_line, end_line, indent = ri

    template = _deindent(rng.choice(_TEMPLATES))
    block = _indent(template, indent)

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
        metadata={"method": method, "action": "ast_insert", "line": insert_at},
    )


# ── 策略 2: AST 均匀替换 ─────────────────────────

def ast_uniform(source: str, lines: list[str],
                cls: str = "ESAEDaemon", method: str = "tick",
                rng: random.Random = None) -> Optional[CodeChange]:
    """用模板块替换方法体内一条随机非关键语句。"""
    if rng is None:
        rng = random.Random()
    ri = _method_body_range(source, cls, method)
    if not ri:
        return None
    start_line, end_line, indent = ri

    # 找可替换的语句行
    candidates = [(i, lines[i]) for i in range(start_line - 1, end_line)
                  if lines[i].strip() and not lines[i].strip().startswith(("#", "\"", "'"))
                  and "self._log(" not in lines[i] and "pass" not in lines[i]]
    if not candidates:
        return None

    idx, old_line = rng.choice(candidates)
    template = _deindent(rng.choice(_TEMPLATES))
    block = _indent(template, indent)

    new_lines = lines.copy()
    new_lines[idx] = block

    try:
        ast.parse("".join(new_lines))
    except SyntaxError:
        return None

    return CodeChange(
        file_path="kernel/daemon.py",
        change_type="modify_line",
        target_line=idx + 1,
        old_text=old_line,
        new_text=block,
        metadata={"method": method, "action": "ast_uniform", "line": idx + 1},
    )


# ── 策略 3: 节点替换 ─────────────────────────────

def ast_replace(source: str, lines: list[str],
                cls: str = "ESAEDaemon", method: str = "tick",
                rng: random.Random = None) -> Optional[CodeChange]:
    """替换方法体内的常数或比较运算符。"""
    if rng is None:
        rng = random.Random()
    ri = _method_body_range(source, cls, method)
    if not ri:
        return None
    start_line, end_line, indent = ri

    # 解析方法体 AST 找可替换节点
    try:
        tree = ast.parse("".join(lines[start_line - 1:end_line]))
    except SyntaxError:
        return None

    targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (bool, int)):
            targets.append(node)
        elif isinstance(node, ast.Compare) and node.ops and isinstance(node.ops[0], (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot)):
            targets.append(node.ops[0])

    if not targets:
        return None

    target = rng.choice(targets)
    new_source = "".join(lines)

    if isinstance(target, ast.Constant):
        old_val = target.value
        new_val = rng.choice([v for v in [True, False, 0, 1, 5, 10, 20, 30, 50] if v != old_val])
        new_source = new_source.replace(f" {old_val}", f" {new_val}", 1)
    elif isinstance(target, ast.cmpop):
        # 替换比较运算符
        op_map = {ast.Eq: "!=", ast.NotEq: "==", ast.Lt: ">=", ast.LtE: ">",
                  ast.Gt: "<=", ast.GtE: "<", ast.Is: "is not", ast.IsNot: "is"}
        for op_type, op_str in op_map.items():
            if isinstance(target, op_type):
                continue
            # 在方法体范围内替换
            method_source = "".join(lines[start_line - 1:end_line])
            for old_op, new_op in [(op_map.get(type(target)), op_str)]:
                pass  # 需要更精确的定位

    if new_source == "".join(lines):
        return None

    try:
        ast.parse(new_source)
    except SyntaxError:
        return None

    return CodeChange(
        file_path="kernel/daemon.py",
        change_type="modify_line",
        target_line=start_line,
        old_text="".join(lines[start_line - 1:end_line]),
        new_text="".join(lines[start_line - 1:end_line]),
        metadata={"method": method, "action": "ast_replace"},
    )


# ── 策略 4: 基因复制 ─────────────────────────────

def gene_duplication(source: str, lines: list[str],
                     cls: str = "ESAEDaemon", method: str = "tick",
                     rng: random.Random = None) -> Optional[CodeChange]:
    """复制一个方法（上限 10 个副本）。"""
    if rng is None:
        rng = random.Random()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method:
                    name = item.name
                    # 检查已有副本数量
                    existing_copies = sum(1 for n in node.body
                                          if isinstance(n, ast.FunctionDef)
                                          and n.name.startswith(f"{name}_v"))
                    if existing_copies >= 10:
                        return None  # 超过上限不再复制
                    v = 2
                    new_name = f"{name}_v{v}"
                    while f"def {new_name}" in source:
                        v += 1
                        new_name = f"{name}_v{v}"
                    end = item.end_lineno or item.lineno
                    block = "".join(lines[item.lineno - 1:end]).replace(name, new_name, 1)
                    new_lines = lines.copy()
                    new_lines.insert(end, "\n" + block)
                    return CodeChange(
                        file_path="kernel/daemon.py",
                        change_type="insert_after",
                        target_line=end,
                        old_text="", new_text="\n" + block,
                        metadata={"method": method, "new_method": new_name, "action": "duplicate"},
                    )
    return None


# ── 策略 5: 父代交叉 ─────────────────────────────

def code_crossover(source: str, lines: list[str],
                   cls: str = "ESAEDaemon", method: str = "tick",
                   rng: random.Random = None) -> Optional[CodeChange]:
    """从当前 daemon.py 的两个不同方法复制代码块并互换。

    相当于 DEAP 的 subtree crossover：选两个方法，各取一段代码互换。
    """
    if rng is None:
        rng = random.Random()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    # 找到类下的所有方法
    methods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and len(item.body) > 1:
                    methods.append((item.name, item.lineno, item.end_lineno or item.lineno))
    if len(methods) < 2:
        return None

    # 选两个方法
    m1 = rng.choice(methods)
    m2 = rng.choice([m for m in methods if m[0] != m1[0]])
    if not m2:
        return None

    # 各取一段代码互换
    def _method_source(name, start, end):
        return "".join(lines[start - 1:end])

    src1 = _method_source(*m1)
    src2 = _method_source(*m2)

    # 把 m2 的方法体插入 m1 所在位置
    # 获取 m1 的方法体缩进
    m1_indent = ""
    for i in range(m1[1] - 1, len(lines)):
        if lines[i].strip() and not lines[i].strip().startswith("def "):
            m1_indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
            break

    insertion = f"\n    # crossover: from {m2[0]}\n"
    for line in src2.splitlines(keepends=True):
        if line.strip() and not line.strip().startswith("def ") and not line.strip().startswith('"""'):
            insertion += f"{m1_indent}{line}"

    new_lines = lines.copy()
    new_lines.insert(m1[2], insertion)

    try:
        ast.parse("".join(new_lines))
    except SyntaxError:
        return None

    return CodeChange(
        file_path="kernel/daemon.py",
        change_type="insert_after",
        target_line=m1[2],
        old_text="", new_text=insertion,
        metadata={"method": method, "action": "crossover",
                  "from": m2[0], "into": m1[0]},
    )


# ── 策略 6: 创建新方法 ─────────────────────────────

_SIGNATURES: dict[str, str] = {
    "record_event": "def record_event(self, event_type):",
    "get_event_stats": "def get_event_stats(self, minutes=5):",
    # ── 人物状态模拟 ──
    "add_character": "def add_character(self, name: str, hp: int = 100, mp: int = 50, level: int = 1) -> None:",
    "get_character": "def get_character(self, name: str) -> Optional[dict]:",
    "apply_to_character": "def apply_to_character(self, name: str, event: str, value: int) -> None:",
    "list_characters": "def list_characters(self) -> list[str]:",
    # ── 自绘界面 ──
    "render_character": "def render_character(self, name: str) -> str:",
    "render_all_characters": "def render_all_characters(self) -> str:",
}


def _method_exists(source: str, cls: str = "ESAEDaemon",
                   method: str = "") -> bool:
    """检查类中是否已存在指定名称的方法。"""
    if not method:
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method:
                    return True
    return False


def _class_insert_point(source: str, cls: str = "ESAEDaemon") -> Optional[int]:
    """找到类定义末尾的插入点（0-based），用于在其后插入新方法。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            if not node.body:
                return (node.lineno or 1) + 1
            last = node.body[-1]
            return (last.end_lineno or last.lineno)
    return None


def _make_method_signature(method_name: str) -> str:
    """生成方法签名，支持预定义签名和泛型 fallback。"""
    if method_name in _SIGNATURES:
        return _SIGNATURES[method_name]
    return f"def {method_name}(self):"


def create_method(source: str, lines: list[str],
                  cls: str = "ESAEDaemon", method: str = "",
                  rng: random.Random = None) -> Optional[CodeChange]:
    """使用模块化组合创建新方法并插入类定义。

    流程：
    1. 检查方法是否已存在（防止重复创建）
    2. 从 modular_mutation 的 ComposerLayer 组合方法体
    3. 包裹在 def 签名中
    4. AST 语法验证
    5. 插入类定义末尾

    Returns:
        CodeChange 或 None（方法已存在 / 组合失败 / 语法错误）
    """
    if rng is None:
        rng = random.Random()

    if not method:
        candidates = list(_SIGNATURES.keys())
        method = rng.choice(candidates) if candidates else "new_method"

    # 已存在则跳过
    if _method_exists(source, cls, method):
        return None

    insert_point = _class_insert_point(source, cls)
    if insert_point is None:
        return None

    signature = _make_method_signature(method)
    body_code = ""

    # ── 预组合方法体（针对已知签名，确保体正确可用） ──
    _PRECOMPOSED_BODIES: dict[str, str] = {
        "record_event": (
            "if event_type is None:\n"
            "    event_type = ''\n"
            "self._events.append((time.time(), str(event_type)))"
        ),
        "get_event_stats": (
            "cutoff = time.time() - minutes * 60\n"
            "stats = {}\n"
            "for ts, et in self._events:\n"
            "    if ts >= cutoff:\n"
            "        stats[et] = stats.get(et, 0) + 1\n"
            "return stats"
        ),
        # ── 人物状态模拟 ──
        "add_character": (
            "self._characters[name] = {'hp': hp, 'mp': mp, 'level': level}"
        ),
        "get_character": (
            "return self._characters.get(name)"
        ),
        "apply_to_character": (
            "if name not in self._characters:\n"
            "    return\n"
            "char = self._characters[name]\n"
            "if event == 'damage':\n"
            "    char['hp'] = max(0, char['hp'] - value)\n"
            "elif event == 'heal':\n"
            "    char['hp'] = char['hp'] + value\n"
            "elif event == 'level_up':\n"
            "    char['level'] = char['level'] + value"
        ),
        "list_characters": (
            "return list(self._characters.keys())"
        ),
        # ── 自绘界面 ──
        "render_character": (
            "char = self._characters.get(name)\n"
            "if not char:\n"
            "    return f'[{name}] 不存在'\n"
            "hp = char['hp']\n"
            "bar_len = max(1, min(10, hp // 10))\n"
            "hp_bar = '█' * bar_len + '░' * (10 - bar_len)\n"
            "return f'{name}  Lv{char[\"level\"]}  HP:{hp_bar} {hp}'"
        ),
        "render_all_characters": (
            "if not self._characters:\n"
            "    return '无角色'\n"
            "parts = ['===== 角色总览 =====']\n"
            "for n in sorted(self._characters.keys()):\n"
            "    parts.append(self.render_character(n))\n"
            "return '\\n'.join(parts)"
        ),
    }

    if method in _PRECOMPOSED_BODIES:
        body_code = _indent(_PRECOMPOSED_BODIES[method], "        ")
    else:
        # ── 尝试用模块化组合生成方法体（未知方法） ──
        from .modular_mutation import ExtractorLayer, ComposerLayer

        extractor = ExtractorLayer()
        all_by_method = extractor.extract_all_methods(source, cls)

        if all_by_method:
            try:
                composer = ComposerLayer(all_by_method)
                composed = composer.compose(method, rng)
                if composed:
                    # 方法体缩进：8 空格（4 类缩进 + 4 方法体缩进）
                    body_code = _indent(composed, "        ")
            except Exception:
                pass  # 组合失败 → fallback

    # ── Fallback: pass 方法体 ────────────────────────
    if not body_code:
        body_code = "        pass"  # 8 空格（类缩进 + 方法体缩进）

    # ── 组装完整方法定义 ──────────────────────────
    # 类内方法必须 4 空格缩进 = 1 级类缩进
    indented_sig = f"    {signature}"
    # body_code 已经缩进（"    " 来自 compose 或 "        pass" 来自 fallback）
    new_method_code = f"\n{indented_sig}\n{body_code}"

    # ── AST 语法验证（整个文件） ──────────────────
    full_source = "".join(lines)
    test_source = full_source.rstrip("\n") + new_method_code
    try:
        ast.parse(test_source)
    except SyntaxError:
        return None

    # ── 安全检查（新方法代码在类上下文中，需先脱缩进） ──
    from .code_genome import ast_check
    import textwrap
    check_ok, _ = ast_check(textwrap.dedent(new_method_code))
    if not check_ok:
        return None

    return CodeChange(
        file_path="kernel/daemon.py",
        change_type="insert_after",
        target_line=insert_point,
        old_text="", new_text=new_method_code,
        metadata={"method": method, "action": "create_method"},
    )


# ── 策略 7: 注入属性初始化 ─────────────────────────

def inject_attribute(source: str, lines: list[str],
                     cls: str = "ESAEDaemon", method: str = "",
                     rng: random.Random = None) -> Optional[CodeChange]:
    """在 __init__ 中注入 self.xxx 属性初始化。

    创建新方法后，该方法引用的 self.xxx 属性需要
    在 __init__ 中初始化。此策略负责自动注入。

    默认注入:
      - self._events = {}   （事件统计用字典）

    Returns:
        CodeChange 或 None（__init__ 找不到 / 已存在 / 语法错误）
    """
    if rng is None:
        rng = random.Random()

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    # 找到 __init__
    init_end = None
    init_indent = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    init_end = item.end_lineno or item.lineno
                    # 获取 __init__ 方法的缩进
                    source_lines = source.splitlines(keepends=True)
                    for i in range(item.lineno - 1, min(item.lineno + 2, len(source_lines))):
                        s = source_lines[i]
                        if s.strip() and not s.strip().startswith("def ") and not s.strip().startswith('"""'):
                            init_indent = s[:len(s) - len(s.lstrip())]
                            break
                    if init_indent is None or init_indent == "":
                        init_indent = "        "  # 8 空格（class 内方法体）
                    break

    if init_end is None:
        return None
    if init_indent is None:
        init_indent = "        "

    # 检查是否已有 self._events 或 self._characters
    has_events = "self._events" in source[:init_end + 100]
    has_chars = "self._characters" in source[:init_end + 100]
    
    # 优先注入 characters 字典（如果还没有）
    if not has_chars:
        attr_init = f"\n{init_indent}self._characters: dict[str, dict] = {{}}  # 角色状态模拟\n"
        test_source = "".join(lines)
        test_lines = test_source.splitlines(keepends=True)
        test_lines.insert(init_end, attr_init)
        try:
            ast.parse("".join(test_lines))
        except SyntaxError:
            return None
        return CodeChange(
            file_path="kernel/daemon.py",
            change_type="insert_after",
            target_line=init_end,
            old_text="", new_text=attr_init,
            metadata={"action": "inject_attribute", "attr": "self._characters"},
        )
    
    if has_events:
        return None

    # 随机选择初始化方式：[] 用于事件流(带时间戳)，{} 用于计数器
    init_style: str = rng.choice(["list", "dict"])
    if init_style == "list":
        attr_init = f"\n{init_indent}self._events: list[tuple[float, str]] = []  # 事件流 (timestamp, type)\n"
    else:
        attr_init = f"\n{init_indent}self._events: dict[str, int] = {{}}  # 事件计数器 type→count\n"

    # 验证
    test_source = "".join(lines)
    test_lines = test_source.splitlines(keepends=True)
    test_lines.insert(init_end, attr_init)
    try:
        ast.parse("".join(test_lines))
    except SyntaxError:
        return None

    return CodeChange(
        file_path="kernel/daemon.py",
        change_type="insert_after",
        target_line=init_end,
        old_text="", new_text=attr_init,
        metadata={"action": "inject_attribute", "attr": "self._events"},
    )


# ── 选择器 ─────────────────────────────────────────

class CodeMutationSelector:
    """代码级突变选择器（AST 辅助 + 原始文本操作）。"""

    def select(self, source: str, lines: list[str],
               class_name: str = "ESAEDaemon",
               target_method: str = "") -> tuple[str, Optional[CodeChange]]:
        rng = random.Random()
        rng.seed(rng.random())
        method = target_method or "tick"

        r = rng.random()
        if r < 0.25:
            c = ast_insert(source, lines, class_name, method, rng)
            if c: return ("ast_insert", c)
        elif r < 0.40:
            c = ast_uniform(source, lines, class_name, method, rng)
            if c: return ("ast_uniform", c)
        elif r < 0.50:
            c = ast_replace(source, lines, class_name, method, rng)
            if c: return ("ast_replace", c)
        elif r < 0.60:
            c = gene_duplication(source, lines, class_name, method, rng)
            if c: return ("duplicate", c)
        elif r < 0.70:
            c = code_crossover(source, lines, class_name, method, rng)
            if c: return ("crossover", c)
        elif r < 0.80:
            # 创建新方法（核心新增！）
            c = create_method(source, lines, class_name, method, rng)
            if c: return ("create_method", c)
        elif r < 0.88:
            # 注入属性初始化（配合新方法）
            c = inject_attribute(source, lines, class_name, method, rng)
            if c: return ("inject_attribute", c)
        else:
            # EASE_MVP 模块化组合（12% 概率）
            c = compose_mutation(source, lines, class_name, method, rng)
            if c: return ("compose", c)

        return ("none", None)
