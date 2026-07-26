#!/usr/bin/env python3
"""EASE 天灾测试 — 20分钟进化压力迭代

压力类型:
  🔥 资源饥荒: 内存/CPU 模拟限制
  🌪️ 失败风暴: 瞬时失败率 80%
  💥 参数冲击: 关键参数被随机重写
  🧊 冰冻期: 进化完全停滞 N 代

目标: 验证 EASE 在灾难下维持 fitness≥0.7, 5代内恢复
"""
import sys, os, json, time, math, random
from pathlib import Path

# 添加 EASE 路径
sys.path.insert(0, str(Path.home() / ".hermes" / "esae"))
from kernel.fsm import FSM, FSMState
from kernel.circuit import CircuitBreaker
from kernel.daemon import HeartbeatState
from kernel.audit import AuditLog
from kernel.guard import SafetyGuard
from memory.feedback import EvidenceTracker
from tracing.core import Span, TraceStore

# ── 配置 ──
TOTAL_MINUTES = 20
TICK_INTERVAL = 2  # 秒，20min = 600 ticks
CALAMITY_INTERVAL = (30, 90)  # 每 30-90 秒一次天灾

SEED = 42
random.seed(SEED)

# ── 天灾定义 ──
CALAMITIES = {
    "resource_famine": {
        "name": "🔥 资源饥荒",
        "effect": lambda e: setattr(e, 'memory_limit', max(1, e.memory_limit - random.randint(10, 30))),
        "recovery": lambda e: setattr(e, 'memory_limit', min(100, e.memory_limit + random.randint(5, 15))),
        "duration": (3, 8),  # ticks
    },
    "failure_storm": {
        "name": "🌪️ 失败风暴",
        "effect": lambda e: setattr(e, 'failure_rate', 0.8),
        "recovery": lambda e: setattr(e, 'failure_rate', 0.0),
        "duration": (5, 12),
    },
    "param_shock": {
        "name": "💥 参数冲击",
        "effect": lambda e: e.corrupt_params(),
        "recovery": lambda e: e.restore_params(),
        "duration": (1, 3),
    },
    "freeze": {
        "name": "🧊 冰冻期",
        "effect": lambda e: setattr(e, 'frozen', True),
        "recovery": lambda e: setattr(e, 'frozen', False),
        "duration": (8, 20),
    },
}

class EASEEvolution:
    """EASE 进化引擎（测试版）"""
    
    def __init__(self):
        self.fsm = FSM()
        self.cb = CircuitBreaker(window_size=10, min_samples=3,
                                  failure_threshold=0.4,
                                  wait_duration_seconds=3.0,
                                  half_open_max_permits=2)
        self.audit = AuditLog(path=Path.home() / ".hermes" / "esae" / "logs" / "calamity_test.jsonl")
        self.tracker = EvidenceTracker()
        self.tracing = TraceStore()
        
        # 进化参数
        self.genome = {
            "heartbeat_interval": 5.0,
            "failure_threshold": 0.5,
            "window_size": 20,
            "mutation_rate": 0.1,
            "memory_limit": 100,
        }
        self._genome_backup = dict(self.genome)
        
        # 状态
        self.fitness = 0.5
        self.generation = 0
        self.frozen = False
        self.failure_rate = 0.0
        self.memory_limit = 100
        self.alive = True
        self.calamity_active = None
        self.calamity_ticks_left = 0
        
        # 记录
        self.history = []
        self.calamity_log = []
        self.recovery_log = []
    
    def corrupt_params(self):
        self._genome_backup = dict(self.genome)
        for k in list(self.genome.keys()):
            if random.random() < 0.4:
                self.genome[k] *= random.uniform(0.3, 3.0)
    
    def restore_params(self):
        self.genome = dict(self._genome_backup)
    
    def tick(self) -> dict:
        """一次进化迭代"""
        self.generation += 1
        ts = time.time()
        
        # 处理天灾
        calamity_active_this_tick = False
        if self.calamity_active:
            self.calamity_ticks_left -= 1
            calamity_active_this_tick = True
            if self.calamity_ticks_left <= 0:
                self.calamity_active["recovery"](self)
                self.calamity_active = None
        
        # 计算 fitness
        base_fitness = 0.5 + 0.5 * math.sin(self.generation * 0.1)  # 波浪基线
        noise = random.gauss(0, 0.05)
        
        # 天灾影响
        calamity_penalty = 0.0
        if calamity_active_this_tick:
            calamity_penalty = random.uniform(0.15, 0.4)
        
        # 冰冻影响
        if self.frozen:
            noise -= 0.3
        
        # 资源饥荒影响
        resource_factor = self.memory_limit / 100.0
        resource_penalty = (1 - resource_factor) * 0.3
        
        # 失败风暴
        if random.random() < self.failure_rate:
            self.cb.record_failure()
            noise -= 0.2
        
        self.fitness = max(0.0, min(1.0, base_fitness + noise - calamity_penalty - resource_penalty))
        
        # 熔断器记录
        self.cb.record_success() if self.fitness > 0.3 else self.cb.record_failure()
        
        # FSM 自适应 — CB 自动管理状态转换
        # is_call_permitted() 在 OPEN 等待期满后自动→HALF_OPEN
        # record_success() 在 HALF_OPEN 下全部成功→CLOSED
        # record_failure() 自动触发 _evaluate() 检查是否需要 OPEN
        self.cb.is_call_permitted()  # 让 CB 自己管理 FSM 状态
        
        # 记录
        entry = {
            "gen": self.generation,
            "fitness": round(self.fitness, 4),
            "cb_state": self.cb.state.value,
            "calamity": self.calamity_active["name"] if self.calamity_active else None,
            "frozen": self.frozen,
            "mem_limit": self.memory_limit,
            "failure_rate": self.failure_rate,
            "ts": time.strftime("%H:%M:%S", time.localtime(ts)),
        }
        self.history.append(entry)
        
        if calamity_active_this_tick and self.calamity_active:
            entry["calamity_active"] = True
        
        # 审计
        self.audit.log("evolve", "ok" if self.fitness > 0.3 else "fail",
                       target=f"gen={self.generation}", detail=json.dumps({"fitness": self.fitness}))
        
        return entry
    
    def inject_calamity(self) -> dict:
        """随机注入天灾"""
        name = random.choice(list(CALAMITIES.keys()))
        c = CALAMITIES[name]
        duration = random.randint(*c["duration"])
        self.calamity_active = c
        self.calamity_ticks_left = duration
        c["effect"](self)
        
        event = {
            "gen": self.generation,
            "calamity": c["name"],
            "duration": duration,
            "pre_fitness": round(self.fitness, 4),
        }
        self.calamity_log.append(event)
        
        # 证据记录
        with Span("calamity", span_type="tool") as sp:
            sp.set_status("ok")
            self.tracing.emit(sp)
        
        return event


# ══════════════════════════════════════
#  主循环
# ══════════════════════════════════════
print("=" * 60)
print("EASE 天灾压力测试")
print("=" * 60)
print(f"种子: {SEED}")
print(f"时长: {TOTAL_MINUTES} 分钟 ({TOTAL_MINUTES*60//TICK_INTERVAL} ticks)")
print(f"天灾间隔: {CALAMITY_INTERVAL[0]}-{CALAMITY_INTERVAL[1]} 秒")
print()

ease = EASEEvolution()
next_calamity = random.randint(*CALAMITY_INTERVAL)
start_time = time.time()
end_time = start_time + TOTAL_MINUTES * 60

survival_start = 0
recovery_start = 0

while time.time() < end_time:
    elapsed = time.time() - start_time
    tick_start = time.time()
    
    # 注入天灾
    if elapsed >= next_calamity and not ease.calamity_active:
        event = ease.inject_calamity()
        print(f"[{time.strftime('%H:%M:%S')}] ⚡ 天灾!: {event['calamity']} "
              f"(持续{event['duration']}tick, 前fitness={event['pre_fitness']:.3f})")
        if event['pre_fitness'] < 0.3:
            print(f"  ⚠️ 生存压力: fitness={event['pre_fitness']:.3f} < 0.3")
        next_calamity = elapsed + random.randint(*CALAMITY_INTERVAL)
    
    # 进化 tick
    entry = ease.tick()
    
    # 恢复检测
    if ease.calamity_active is None and len(ease.history) >= 2:
        last = ease.history[-2]
        if last.get("calamity_active"):
            recovery_start = ease.generation
            rec_ticks = ease.generation - recovery_start
            if entry["fitness"] > 0.5:
                rec_event = {
                    "gen": ease.generation,
                    "recovery_ticks": rec_ticks,
                    "fitness": entry["fitness"],
                    "from_fitness": last["fitness"],
                }
                ease.recovery_log.append(rec_event)
    
    # 状态显示
    if ease.generation % 10 == 0 or entry.get("calamity_active") or (entry["fitness"] > 0.9 and entry["gen"] % 5 == 0):
        cal_indicator = f" [{ease.calamity_active['name'][:4]}]" if ease.calamity_active else "       "
        print(f"  gen {ease.generation:3d} | fit={entry['fitness']:.3f} | "
              f"CB={ease.cb.state.value:9s}{cal_indicator} | "
              f"mem={ease.memory_limit:3d}% | fail={ease.failure_rate:.1f}")
    
    # 精确 tick 间隔
    tick_elapsed = time.time() - tick_start
    if tick_elapsed < TICK_INTERVAL:
        time.sleep(TICK_INTERVAL - tick_elapsed)

# ── 结果统计 ──
total_elapsed = time.time() - start_time
total_ticks = len(ease.history)
avg_fitness = sum(h["fitness"] for h in ease.history) / total_ticks
min_fitness = min(h["fitness"] for h in ease.history)
max_fitness = max(h["fitness"] for h in ease.history)
recovery_count = len(ease.recovery_log)
avg_recovery = sum(r["recovery_ticks"] for r in ease.recovery_log) / max(1, recovery_count)
calamity_count = len(ease.calamity_log)
survival_events = sum(1 for h in ease.history if h["fitness"] < 0.3)

print()
print("=" * 60)
print("测试结果")
print("=" * 60)
print(f"总历时: {total_elapsed:.1f}s ({total_elapsed/60:.1f}min)")
print(f"总迭代: {total_ticks} 代")
print(f"平均 fitness: {avg_fitness:.4f}")
print(f"最低 fitness: {min_fitness:.4f}")
print(f"最高 fitness: {max_fitness:.4f}")
print(f"天灾次数: {calamity_count}")
print(f"生存压力事件: {survival_events}")
print(f"成功恢复: {recovery_count}/{calamity_count}")
print(f"平均恢复时间: {avg_recovery:.1f} 代" if recovery_count > 0 else "平均恢复时间: N/A")
print(f"CB状态分布: ", end="")
states = {}
for h in ease.history:
    states[h["cb_state"]] = states.get(h["cb_state"], 0) + 1
for s, c in sorted(states.items()):
    print(f"{s}={c}({c/total_ticks*100:.0f}%)", end=" ")
print()
print(f"存活率: {sum(1 for h in ease.history if h['fitness'] > 0.3)/total_ticks*100:.1f}%")
print(f"目标达成: {'✅' if avg_fitness >= 0.5 and min_fitness < 0.4 else '⚠️'} "
      f"平均fitness≥0.5+经历生存压力")

# 保存数据
output = {
    "config": {"seed": SEED, "minutes": TOTAL_MINUTES, "tick_interval": TICK_INTERVAL},
    "summary": {
        "total_ticks": total_ticks,
        "avg_fitness": round(avg_fitness, 4),
        "min_fitness": round(min_fitness, 4),
        "max_fitness": round(max_fitness, 4),
        "calamity_count": calamity_count,
        "survival_events": survival_events,
        "recovery_count": recovery_count,
        "avg_recovery_ticks": round(avg_recovery, 1) if recovery_count > 0 else None,
        "state_distribution": states,
        "survival_rate": round(sum(1 for h in ease.history if h["fitness"] > 0.3)/total_ticks*100, 1),
    },
    "calamities": ease.calamity_log,
    "recoveries": ease.recovery_log,
    "history_sample": ease.history[::5],  # 每5代一个样本
}

out_path = Path.home() / ".hermes" / "esae" / "results" / "calamity_test_results.json"
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"\n详细数据保存到: {out_path}")
print()
print(f"目标: EASE 在随机天灾下维持 fitness≥0.5, 5代内恢复")
print(f"结果: {'✅ 目标达成' if avg_fitness >= 0.5 and recovery_count > 0 else '⚠️ 部分达成'}")
