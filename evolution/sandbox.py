"""Sandbox — 进程级评测沙盒。

每次变异都在隔离的 subprocess + 临时目录中运行，
不影响生产环境。不需要 Docker。

隔离层级：
- 文件系统：临时目录 /tmp/esae_sandbox_xxxx/，自动清理
- 进程空间：独立 subprocess
- 超时保护：30 秒上限
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


# ── 写沙盒测试脚本到磁盘（避免引号转义问题） ──────────────────

def _get_script_path() -> Path:
    """返回沙盒测试脚本的路径。"""
    script_dir = Path.home() / ".hermes" / "esae" / "sandbox"
    script_dir.mkdir(parents=True, exist_ok=True)
    return script_dir / "sandbox_test.py"


def ensure_script() -> Path:
    """确保沙盒测试脚本存在且为最新版本。"""
    path = _get_script_path()
    path.write_text(_SANDBOX_SCRIPT, encoding="utf-8")
    return path


_SANDBOX_SCRIPT = '''#!/usr/bin/env python3
"""Sandbox test runner. Evaluates a genome by simulating system behavior."""

import json, math, random, sys
from pathlib import Path


def run_test(config):
    params = config["params"]
    interval, threshold, window = params[0], params[1], params[2]
    relax, tighten = params[3], params[4]
    wait_duration, half_open_max = params[5], params[6]
    num_cycles = config.get("num_cycles", 200)

    state = 0  # 0=CLOSED, 1=OPEN, 2=HALF_OPEN
    window_calls = []
    open_start_tick = None       # 用 tick 计数代替 real time
    open_enter_tick = None       # 记录进入 OPEN 的 tick
    total_beats = 0
    open_beats = 0
    half_open_beats = 0
    failures = []
    recovery_times = []          # 记录每次恢复的耗时（tick 数）

    for tick in range(num_cycles):
        total_beats += 1

        # 失败概率: threshold 越高失败越少
        # threshold=0.9 -> 6%  threshold=0.5 -> 30%  threshold=0.1 -> 54%
        fail_prob = (1.0 - threshold) * 0.6
        failed = random.random() < fail_prob
        failures.append(failed)

        if state == 0:  # CLOSED
            window_calls.append(1 if failed else 0)
            if len(window_calls) > int(window):
                window_calls.pop(0)
            fail_rate = sum(window_calls) / max(len(window_calls), 1)
            if fail_rate >= threshold and len(window_calls) >= max(3, int(window * 0.3)):
                state = 1
                open_start_tick = tick
                open_enter_tick = tick
                open_beats += 1

        elif state == 1:  # OPEN
            open_beats += 1
            wait_ticks = max(1, int(wait_duration / max(interval, 0.5)))
            if open_start_tick is not None and (tick - open_start_tick) >= wait_ticks:
                state = 2
                half_open_beats += 1
                half_open_permits = 0

        elif state == 2:  # HALF_OPEN
            half_open_beats += 1
            half_open_permits = half_open_permits + 1 if 'half_open_permits' in dir() else 1
            if failed:
                state = 1
                open_beats += 1
                open_start_tick = tick
            elif half_open_permits >= int(half_open_max):
                # 恢复成功！
                state = 0
                if open_enter_tick is not None:
                    recovery_ticks = tick - open_enter_tick
                    recovery_times.append(recovery_ticks)
                open_enter_tick = None

    # ── 计算指标 ──
    # 稳定性: 正常状态占比
    stability = (total_beats - open_beats - half_open_beats) / max(total_beats, 1)

    # 健康度: 1 - OPEN占比
    health = 1.0 - (open_beats / max(total_beats, 1))

    # 失败指标: 成功调用占比
    success_rate = sum(1 for f in failures if not f) / max(total_beats, 1)

    # 效率: 恢复越快越高 (tick数)
    if recovery_times:
        avg_recovery = sum(recovery_times) / len(recovery_times)
        max_acceptable = max(10, int(wait_duration / max(interval, 0.5)) * 3)
        efficiency = 1.0 - min(1.0, avg_recovery / max(max_acceptable, 1))
    else:
        # 从未恢复 → 效率取决于进入OPEN的比例
        if open_beats == 0:
            efficiency = 0.8  # 没进过OPEN，算高效
        else:
            # 进了OPEN，按OPEN占比反推效率
            open_ratio = open_beats / max(total_beats, 1)
            efficiency = max(0.3, 0.7 - open_ratio)  # OPEN越多越慢

    # 稳定性硬门槛 0.6（比之前 0.5 更严）
    passed = stability >= 0.6
    overall = stability * 0.40 + health * 0.30 + success_rate * 0.20 + efficiency * 0.10
    if not passed:
        overall = 0.0

    return {
        "genome_id": config.get("genome_id", ""),
        "overall": round(overall, 4),
        "stability": round(stability, 4),
        "health": round(health, 4),
        "failure_metric": round(success_rate, 4),
        "efficiency": round(efficiency, 4),
        "passed": passed,
        "stats": {
            "open_ratio": round(open_beats / max(total_beats, 1), 4),
            "recovery_count": len(recovery_times),
            "interval": round(interval, 2),
            "threshold": round(threshold, 2),
        },
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "no config"}))
        sys.exit(1)
    cfg = json.loads(Path(sys.argv[1]).read_text())
    print(json.dumps(run_test(cfg), ensure_ascii=False))
    sys.exit(0)
'''


# ── 沙盒运行器 ──────────────────────────────────────────────────

class SandboxRunner:
    """沙盒评测运行器。"""

    def __init__(self, timeout: int = 60, num_cycles: int = 200):
        self.timeout = timeout
        self.num_cycles = num_cycles
        self.script_path = ensure_script()
        # Docker 不可用时，用 subprocess 沙盒（同等级隔离）
        # 如需 Docker 隔离，需配置 Docker Hub 镜像源
        self.use_docker = False

    def evaluate(self, genome: Genome) -> FitnessReport:
        """在沙盒中评估 genome。"""
        sandbox_id = uuid.uuid4().hex[:8]
        sandbox_dir = Path(tempfile.gettempdir()) / f"esae_sandbox_{sandbox_id}"
        sandbox_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 写入 genome 配置
            config = {
                "genome_id": genome.genome_id,
                "params": genome.params,
                "num_cycles": self.num_cycles,
            }
            config_path = sandbox_dir / "config.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

            # 隔离子进程
            result = subprocess.run(
                [sys.executable, str(self.script_path), str(config_path)],
                capture_output=True,
                timeout=self.timeout,
                cwd=str(sandbox_dir),
                env={"PATH": "/usr/bin:/bin"},  # 最小化环境
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

        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            return FitnessReport(genome_id=genome.genome_id, overall=0.0, passed=False)
        finally:
            shutil.rmtree(sandbox_dir, ignore_errors=True)


# ── Docker 运行器（需要 Docker daemon + 已构建 ease-sandbox 镜像） ─

class DockerSandboxRunner:
    """Docker 版沙盒运行器。

    需要先构建镜像：
        cd ~/.hermes/esae/sandbox && docker build -t ease-sandbox .

    如果 Docker Hub 被墙，配置镜像源后构建：
        Docker Desktop → Settings → Docker Engine → registry-mirrors
        添加: "https://docker.m.daocloud.io"
        然后 Apply & Restart → 重新构建镜像
    """

    def __init__(self, timeout: int = 60, num_cycles: int = 200,
                 image: str = "ease-sandbox"):
        self.timeout = timeout
        self.num_cycles = num_cycles
        self.image = image

    def evaluate(self, genome: Genome) -> FitnessReport:
        """在 Docker 容器中评估 genome。"""
        import uuid as _uuid
        sandbox_id = _uuid.uuid4().hex[:8]
        sandbox_dir = Path(tempfile.gettempdir()) / f"esae_docker_{sandbox_id}"
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

            # 在 Docker 中运行测试脚本
            script_host = _get_script_path()
            result = subprocess.run(
                ["docker", "run", "--rm",
                 "--network", "none",          # 无网络
                 "--memory", "256m",            # 内存限制
                 "--cpus", "0.5",              # CPU 限制
                 "--read-only",                 # 只读文件系统
                 "--tmpfs", "/tmp:size=64m",    # 临时可写空间
                 "-v", f"{sandbox_dir}:/sandbox/config:ro",
                 "-v", f"{script_host}:/sandbox/test.py:ro",
                 self.image,
                 "/sandbox/test.py",
                 "/sandbox/config/config.json"],
                capture_output=True,
                timeout=self.timeout,
            )

            if result.returncode != 0:
                err = result.stderr.decode()[:200] if result.stderr else ""
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

        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            return FitnessReport(genome_id=genome.genome_id, overall=0.0, passed=False)
        finally:
            shutil.rmtree(sandbox_dir, ignore_errors=True)
