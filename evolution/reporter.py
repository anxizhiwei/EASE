"""EvolutionReporter — 进化可观测性写入txt。

每个 cycle 输出进化进度到 results/evolution_report.txt。
"""
import time, json
from pathlib import Path
from typing import Optional

class EvolutionReporter:
    """进化报告器 — 将当前状态写入可读txt文件。"""
    
    def __init__(self, report_dir: Optional[Path] = None):
        self.dir = report_dir or Path.home() / ".hermes" / "esae" / "results"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.line_written = 0
    
    def write_progress(self, cycle: int, generation: int, 
                       capabilities: dict[str, float],
                       elapsed: float, total_failed: int) -> None:
        """追加一行进化进度。"""
        path = self.dir / "evolution_report.txt"
        ts = time.strftime("%H:%M:%S")
        
        # 热力图：能力名 + 进度条
        bars = []
        for name, score in sorted(capabilities.items()):
            filled = int(score * 10)
            bar = "█" * filled + "░" * (10 - filled)
            bars.append(f"  {name:8s} [{bar}] {score:.2f}")
        
        status = ["=" * 40,
                  f"[{ts}] Cycle {cycle} | Gen {generation} | "
                  f"{elapsed:.0f}s | 失败测试: {total_failed}",
                  "─" * 40]
        status += bars
        status.append("")
        
        with open(path, "a") as f:
            f.write("\n".join(status) + "\n")
        
        self.line_written += len(status)
    
    def write_final(self, generation: int, elapsed: float,
                    passed: bool, target: str, code: str = "") -> None:
        """写入最终结果。"""
        path = self.dir / "evolution_report.txt"
        status = [
            "=" * 40,
            f"最终结果: {'✅ 通过' if passed else '❌ 未通过'}",
            f"目标: {target}",
            f"代数: {generation}",
            f"历时: {elapsed:.0f}s ({elapsed/60:.1f}min)",
        ]
        if code:
            status.append(f"\n进化出的代码:\n{code}")
        status.append("=" * 40 + "\n")
        
        with open(path, "a") as f:
            f.write("\n".join(status) + "\n")
