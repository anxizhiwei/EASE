"""ease evolve — 运行进化循环。"""
from __future__ import annotations

import sys
import time


def add_parser(subparsers) -> None:
    """向 argparse 注册 evolve 子命令。"""
    p = subparsers.add_parser("evolve", help="运行进化循环")
    p.add_argument("-g", "--generations", type=int, default=50,
                    help="进化代数（默认: 50）")
    p.add_argument("-q", "--quick", action="store_true",
                    help="快速模式（3 代）")
    p.add_argument("-v", "--verbose", action="store_true", default=True,
                    help="详细输出（默认）")
    p.add_argument("--quiet", action="store_true",
                    help="静默模式（覆盖 --verbose）")


def run(args) -> None:
    """执行 evolve 子命令。"""
    if args.quick:
        generations = 3
    else:
        generations = max(1, args.generations)

    verbose = not args.quiet if args.quiet else args.verbose

    try:
        from evolution.evolution_loop import run_evolution
    except ImportError:
        print("错误: 无法加载进化引擎 (evolution.evolution_loop)")
        print("请确保在 EASE 项目根目录运行。")
        sys.exit(1)

    print(f"⏳ 启动进化循环 — {generations} 代")
    print()

    start = time.time()
    loop = run_evolution(generations=generations, verbose=verbose)
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
