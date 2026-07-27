#!/usr/bin/env python3
"""EASE V0.1.0 — 300 代进化挑战

目标能力: 自主停滞检测 + 参数自适应
──── 当前 daemon.py 不具备的能力 ────

要求:
  ESAEDaemon 类上出现 _detect_stagnation() 方法:
    - 监控自身上一次的 fitness/心跳变化
    - 若 N 代无改进 → 自动调整一个参数
    - 调整后继续监控

评估方式:
  - pytest test_evolution_daemon.py 中新增的停滞检测用例
  - 检测方法是否存在（雏形阶段）
  - 方法是否能被调用且不抛异常

通过条件（300 代内）:
  必备: _detect_stagnation 方法出现在 daemon.py 的 AST 中
  进阶: 方法体内有参数调整逻辑
  理想: 方法被 run() 主循环调用

运行方式:
  python3 evolution/self_evolver.py --target stagnation --max-gen 300
"""
import sys, os, time, json, ast
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".hermes" / "esae"))
from evolution.self_evolver import SelfEvolver
from evolution.code_genome import CodeChange, CodeGenome
from evolution.code_fitness import CodeFitness

TARGET_METHOD = "_detect_stagnation"
MAX_GENERATIONS = 300
DAEMON_PATH = Path.home() / ".hermes" / "esae" / "kernel" / "daemon.py"

def check_prototype(source: str) -> dict:
    """检查 daemon.py 是否出现了目标能力的雏形。"""
    result = {
        "method_exists": False,
        "has_body": False,
        "has_adjustment": False,
        "called_in_run": False,
        "ast_nodes": 0,
    }
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == TARGET_METHOD:
                result["method_exists"] = True
                result["has_body"] = len(node.body) > 1  # 除了 pass/docstring 外有内容
                result["ast_nodes"] = len(node.body)
                # 检查是否有参数调整逻辑
                for child in ast.walk(node):
                    if isinstance(child, ast.Attribute) and "param" in child.attr.lower():
                        result["has_adjustment"] = True
            # 检查主循环是否调用了此方法
            if isinstance(node, ast.FunctionDef) and node.name == "run":
                source_lines = source.splitlines()
                for lineno in range(node.lineno-1, min(node.end_lineno or len(source_lines), len(source_lines))):
                    if lineno < len(source_lines) and TARGET_METHOD in source_lines[lineno]:
                        result["called_in_run"] = True
    except SyntaxError:
        pass
    return result

if __name__ == "__main__":
    print("=" * 60)
    print("EASE V0.1.0 — 300 代进化挑战")
    print("目标: daemon.py 自主进化出 _detect_stagnation()")
    print("=" * 60)
    print()
    print(f"当前 daemon.py: {DAEMON_PATH.stat().st_size} 字节, {len(DAEMON_PATH.read_text().splitlines())} 行")
    print()

    # 检查当前状态
    current_source = DAEMON_PATH.read_text()
    baseline = check_prototype(current_source)
    print(f"基线检查: method_exists={baseline['method_exists']}")
    print(f"  (应为 False — 能力应不存在)")
    assert not baseline["method_exists"], f"目标方法 {TARGET_METHOD} 已存在！"
    print("  ✅ 能力不存在，可以开始进化")
    print()

    # 运行进化
    print(f"开始进化: 最大 {MAX_GENERATIONS} 代")
    print()

    evolver = SelfEvolver(timeout=15)
    # 确保 pytest 可用（通过 venv）
    os.environ.setdefault("PYTHONPATH",
        "/tmp/venv_ease/lib/python3.12/site-packages")
    t_start = time.time()
    results = evolver.loop(
        max_cycles=1,
        gens_per_goal=MAX_GENERATIONS,
        time_budget=600,  # 10分钟上限
        verbose=True,
    )
    elapsed = time.time() - t_start

    # 最终检查
    final_source = DAEMON_PATH.read_text()
    final_check = check_prototype(final_source)

    print()
    print("=" * 60)
    print("进化结果")
    print("=" * 60)
    print(f"历时: {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"总代数: {evolver.generation}")
    print()
    print(f"雏形检测:")
    print(f"  method_exists:   {final_check['method_exists']}")
    print(f"  has_body:        {final_check['has_body']} ({final_check['ast_nodes']} AST节点)")
    print(f"  has_adjustment:  {final_check['has_adjustment']}")
    print(f"  called_in_run:   {final_check['called_in_run']}")
    print()

    # 如果出现了雏形，输出相关代码
    if final_check["method_exists"]:
        tree = ast.parse(final_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == TARGET_METHOD:
                start = node.lineno - 1
                end = node.end_lineno or start + 1
                lines = final_source.splitlines()[start:end]
                print(f"进化出的代码 ({TARGET_METHOD}):")
                for i, line in enumerate(lines):
                    print(f"  {start+i+1:4d}| {line}")
                print()

    # 报告
    passed = final_check["method_exists"]
    print(f"结果: {'✅ 通过' if passed else '❌ 未通过'} — "
          f"{'出现雏形' if passed else '300代内未出现雏形'}")
    print(f"代际: {evolver.generation} 代 ({elapsed:.0f}s)")

    # 保存结果
    result_data = {
        "version": "0.1.0",
        "target": TARGET_METHOD,
        "generations": evolver.generation,
        "elapsed_seconds": elapsed,
        "passed": passed,
        "details": final_check,
        "timestamp": time.time(),
    }
    out_path = Path.home() / ".hermes" / "esae" / "results" / "v010_challenge_result.json"
    with open(out_path, "w") as f:
        json.dump(result_data, f, indent=2)
    print(f"\n结果保存到: {out_path}")
