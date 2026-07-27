"""DaemonRunner — 基于真实 FSM + CircuitBreaker 的评估器。

在隔离 subprocess 中加载真实的 kernel 模块进行评估。
确定性：同一 genome 在同一环境下总是产生相同分数。
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

from .genome import Genome
from .fitness import FitnessReport


# ── 评测脚本（写入临时文件，在子进程中运行） ──────────────────

_EVAL_SCRIPT = r'''#!/usr/bin/env python3
"""Evaluate genome using real FSM + CircuitBreaker."""
import json, os, sys, random
from pathlib import Path

sys.path.insert(0, SRC)
from kernel.fsm import FSM, FSMState
from kernel.circuit import CircuitBreaker
from kernel.daemon import ESAEDaemon

# 重定向 daemon 日志到 stderr，避免和 JSON 输出混在一起
import os as _os
_devnull = _os.open(_os.devnull, _os.O_WRONLY)
_old_stdout = _os.dup(1)
_os.dup2(_devnull, 1)
_os.close(_devnull)

cfg = json.loads(Path(CFG).read_text())
params = cfg["params"]
num_cycles = cfg["num_cycles"]
genome_id = cfg["genome_id"]

interval, threshold, window = params[0], params[1], params[2]
relax, tighten = params[3], params[4]
wait_duration, half_open_max = params[5], params[6]

cb = CircuitBreaker(
    window_size=int(window),
    min_samples=max(3, int(window * 0.3)),
    failure_threshold=threshold,
    wait_duration_seconds=wait_duration,
    half_open_max_permits=int(half_open_max),
    slow_call_threshold_seconds=999,
    slow_call_rate_threshold=1.0,
)
daemon = ESAEDaemon(interval=interval)

open_count = half_open_count = closed_count = 0
success_calls = fail_calls = 0
recovery_times = []
open_tick = None
rng = random.Random(42)

for tick in range(num_cycles):
    daemon.tick()
    fail_prob = (1.0 - threshold) * 0.4
    failed = rng.random() < fail_prob
    if failed:
        cb.record_failure(duration=0.1)
        fail_calls += 1
    else:
        cb.record_success(duration=0.05)
        success_calls += 1
    state = cb.state
    if state == FSMState.OPEN:
        open_count += 1
        if open_tick is None:
            open_tick = tick
    elif state == FSMState.HALF_OPEN:
        half_open_count += 1
    else:
        closed_count += 1
        if open_tick is not None:
            recovery_times.append(tick - open_tick)
            open_tick = None

total = max(num_cycles, 1)
stability = closed_count / total
health = 1.0 - (open_count / total)
success_rate = success_calls / total
if recovery_times:
    avg_rec = sum(recovery_times) / len(recovery_times)
    efficiency = 1.0 - min(1.0, avg_rec / max(total * 0.5, 1))
else:
    efficiency = 0.8 if open_count == 0 else 0.2

passed = stability >= 0.7
overall = stability * 0.40 + health * 0.30 + success_rate * 0.20 + efficiency * 0.10
if not passed:
    overall = 0.0

result = dict(genome_id=genome_id, overall=round(overall,4),
    stability=round(stability,4), health=round(health,4),
    failure_metric=round(success_rate,4), efficiency=round(efficiency,4),
    passed=passed)
_os.dup2(_old_stdout, 1)
_os.close(_old_stdout)
print(json.dumps(result, ensure_ascii=False))
sys.exit(0)
'''


class DaemonRunner:
    """基于真实 FSM + CircuitBreaker 的评估器。

    确定性：同一 genome 在同一环境下总是产生相同分数（无随机噪声）。
    """

    def __init__(self, timeout: int = 30, num_cycles: int = 200,
                 esae_home: Optional[Path] = None):
        self.timeout = timeout
        self.num_cycles = num_cycles
        self.esae_home = esae_home or Path.home() / ".hermes" / "esae"

    def evaluate(self, genome: Genome) -> FitnessReport:
        sandbox_id = uuid.uuid4().hex[:8]
        sandbox_dir = Path(tempfile.gettempdir()) / f"esae_real_{sandbox_id}"
        sandbox_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 写入配置
            config = {
                "genome_id": genome.genome_id,
                "params": genome.params,
                "num_cycles": self.num_cycles,
            }
            config_path = sandbox_dir / "config.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

            # 写入评测脚本（注入路径）
            script = _EVAL_SCRIPT.replace("SRC", repr(str(self.esae_home)))
            script = script.replace("CFG", repr(str(config_path)))
            script_path = sandbox_dir / "eval.py"
            script_path.write_text(script, encoding="utf-8")

            # 隔离子进程
            result = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True, timeout=self.timeout,
                cwd=str(sandbox_dir),
                env={"PATH": "/usr/bin:/bin"},
            )

            if result.returncode != 0:
                return FitnessReport(genome_id=genome.genome_id, overall=0.0, passed=False)

            data = json.loads(result.stdout.decode())
            return FitnessReport(
                genome_id=data.get("genome_id", genome.genome_id),
                overall=data.get("overall", 0.0),
                stability=data.get("stability", 0.0),
                health=data.get("health", 0.0),
                failure_metric=data.get("failure_metric", 0.0),
                efficiency=data.get("efficiency", 0.0),
                passed=data.get("passed", False),
            )

        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            return FitnessReport(genome_id=genome.genome_id, overall=0.0, passed=False)
        except Exception:
            return FitnessReport(genome_id=genome.genome_id, overall=0.0, passed=False)
        finally:
            shutil.rmtree(sandbox_dir, ignore_errors=True)
