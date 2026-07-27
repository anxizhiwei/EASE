"""EASE CLI 输出格式化 — 类 Hermes 的 box drawing 和状态标记。"""
from __future__ import annotations

import shutil


def terminal_width() -> int:
    """获取终端宽度，默认 80。"""
    try:
        return shutil.get_terminal_size((80, 20)).columns
    except Exception:
        return 80


def box(title: str, *lines: str, style: str = "single") -> str:
    """画一个带标题的框。
       style="single": ┌──┐
       style="double": ╔══╗
    """
    c_tl, c_tr, c_bl, c_br = ("┌", "┐", "└", "┘") if style == "single" else ("╔", "╗", "╚", "╝")
    h = "─"
    v = "│" if style == "single" else "║"

    max_w = terminal_width() - 4  # padding for box borders
    if title:
        inner = f" {title} "
        top = f"  {c_tl}{h * 2}{inner}{h * (max_w - len(inner) - 2)}{c_tr}"
    else:
        top = f"  {c_tl}{h * (max_w)}{c_tr}"

    result = [top]
    for line in lines:
        padded = line[: max_w - 2] + ("…" if len(line) > max_w - 2 else "")
        result.append(f"  {v} {padded:<{max_w - 2}} {v}")
    result.append(f"  {c_bl}{h * max_w}{c_br}")
    return "\n".join(result)


def status_line(symbol: str, label: str, value: str) -> str:
    """格式化的状态行: ◆ EASE ◆  系统状态"""
    return f"  {symbol}  {label:<12} {value}"


def bullet(text: str, indent: int = 2) -> str:
    """带缩进的 bullet 点。"""
    return f"{' ' * indent}• {text}"


def heading(text: str) -> str:
    """带装饰的标题行。"""
    w = min(terminal_width() - 4, 60)
    sep = "─" * w
    return f"\n  ── {text} ──{sep[len(text) + 4:]}\n"


def key_value(key: str, value: str, width: int = 14) -> str:
    """格式化的 key: value 行。"""
    return f"  {key:<{width}} {value}"
