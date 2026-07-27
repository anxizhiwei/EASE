"""ease evolve — 运行进化循环。"""
from __future__ import annotations
import sys
import time
from pathlib import Path


class CmdEvolve:
    """ease evolve — 运行进化循环。

    用法:
        ease evolve [--generations N] [--verbose] [--quick]
    """

    def __init__(self, args: list[str]) -> None:
        self.args = args
        self.generations = 50
        self.verbose = True

    def run(self) -> None:
        self._parse_args()
        self._run_evolution()

    def _parse_args(self) -> None:
        i = 0
        while i < len(self.args):
            arg = self.args[i]
            if arg in ("-g", "--generations") and i + 1 < len(self.args):
                try:
                    self.generations = max(1, int(self.args[i + 1]))
                    i += 2
                except ValueError:
                    print(f"无效的代数值: {self.args[i+1]}")
                    sys.exit(1)
            elif arg in ("-q", "--quick"):
                self.generations = 3
                i += 1
            elif arg in ("-v", "--verbose"):
                self.verbose = True
                i += 1
            elif arg in ("--quiet",):
                self.verbose = False
                i += 1
            else:
                print(f"未知选项: {arg}")
                print("用法: ease evolve [--generations N] [--quick] [--quiet]")
                sys.exit(1)

    def _run_evolution(self) -> None:
        try:
            from evolution.evolution_loop import EvolutionLoop, run_evolution
        except ImportError:
            print("错误: 无法加载进化引擎 (evolution.evolution_loop)")
            print("请确保在 EASE 项目根目录运行。")
            sys.exit(1)

        print(f"⏳ 启动进化循环 — {self.generations} 代")
        print()

        start = time.time()
        loop = run_evolution(generations=self.generations, verbose=self.verbose)
        elapsed = time.time() - start

        print()
        print(f"✅ 进化完成 — 用时 {elapsed:.1f}s")
        print(f"   总代数:     {len(loop.history) - 1}")
        accepted = sum(1 for h in loop.history[1:] if h.accepted)
        rolled = sum(1 for h in loop.history[1:] if h.rolled_back)
        best = max(loop.history, key=lambda h: h.report.overall) if loop.history else None
        if best:
            print(f"   接受:       {accepted}")
            print(f"   回退:       {rolled}")
            print(f"   最佳适应度: {best.report.overall:.4f} (第 {best.generation} 代)")
