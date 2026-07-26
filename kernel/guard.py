"""安全门 — 敏感区域检测、黑名单按键、两阶段变异审批、参数边界检查。

参考：Hermes write_approval 两阶段提交 + Raven shell deny-list
"""
import json
import math
import os
import uuid
from pathlib import Path
from typing import Optional

from .audit import ESAEError


class GuardError(ESAEError):
    """安全门拒绝异常。"""
    pass


class SafetyGuard:
    """ESAE 安全门——所有危险操作必须通过此门。

    职责：
    - 屏幕敏感区域检测（check_coord）
    - 黑名单按键拦截（check_keys）
    - 代码变异两阶段审批（stage_mutation / approve_mutation）
    - 参数边界检查（check_param）
    """

    # ── 屏幕敏感区域（归一化坐标 0.0~1.0）────────────────────────
    SENSITIVE_ZONES: list[dict] = [
        {"name": "screen_top_left",     "x": 0,    "y": 0,   "w": 0.05, "h": 0.05},
        {"name": "screen_bottom_left",  "x": 0,    "y": 0.95,"w": 0.1,  "h": 0.05},
        {"name": "taskbar",             "x": 0,    "y": 0.93,"w": 1.0,  "h": 0.07},
        {"name": "system_tray",         "x": 0.85, "y": 0,   "w": 0.15, "h": 0.05},
    ]

    # ── 黑名单按键组合 ────────────────────────────────────────────
    BLACKLIST_KEYS: list[str] = [
        "ctrl+alt+del", "win+r", "alt+f4", "super_l", "super_r",
        "ctrl+shift+esc", "alt+tab", "win+l", "ctrl+alt+f2",
    ]

    # ── 代码 deny-list（不可修改的内置列表）────────────────────────
    DENY_LIST: list[str] = [
        "exec", "eval", "__import__", "compile",
        "setattr", "getattr", "delattr",
        "os.system", "os.popen", "subprocess.Popen",
        "open(", "file(", "io.open",
        "shutil.rmtree", "os.remove", "os.unlink",
        "__builtins__", "__dict__", "__class__", "__subclasses__",
    ]

    # ── 敏感路径（内核自身保护）───────────────────────────────────
    SENSITIVE_PATHS: list[str] = [
        "/etc/", "/usr/", "/boot/", "/sys/", "/proc/",
        str(Path.home() / ".ssh"),
        str(Path.home() / ".hermes" / "config.yaml"),
        str(Path.home() / ".hermes" / "esae" / "kernel"),
    ]

    def __init__(self, pending_dir: Optional[Path] = None):
        self.pending_dir = pending_dir or (
            Path.home() / ".hermes" / "esae" / "mutations" / "pending"
        )
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        # 用户自定义 deny 模式（运行时追加，不影响内置列表）
        self._user_deny: list[str] = []

    # ── 屏幕坐标检测 ──────────────────────────────────────────────

    def check_coord(self, screen_w: int, screen_h: int,
                    x: int, y: int) -> tuple[bool, str]:
        """检查坐标是否在敏感区域。

        Returns:
            (True, "允许") | (False, "拒绝原因")
        """
        nx = x / screen_w
        ny = y / screen_h
        for zone in self.SENSITIVE_ZONES:
            if (zone["x"] <= nx <= zone["x"] + zone["w"]
                    and zone["y"] <= ny <= zone["y"] + zone["h"]):
                return False, f"坐标({x},{y})在敏感区域: {zone['name']}"
        return True, "允许"

    # ── 按键黑名单检测 ────────────────────────────────────────────

    def check_keys(self, keys: str) -> tuple[bool, str]:
        """检查按键组合是否在黑名单。"""
        normalized = keys.lower().replace(" ", "")
        for bk in self.BLACKLIST_KEYS:
            if normalized == bk:
                return False, f"按键黑名单: {bk}"
        return True, "允许"

    # ── 两阶段变异审批 ────────────────────────────────────────────

    def check_code(self, code: str) -> tuple[bool, str]:
        """阶段一：静态代码扫描。检查 deny-list 和敏感路径引用。

        Returns:
            (True, "") | (False, "拒绝原因")
        """
        for pattern in self.DENY_LIST:
            if pattern in code:
                return False, f"代码包含 deny 模式: {pattern}"
        for pat in self._user_deny:
            if pat in code:
                return False, f"代码包含用户自定义 deny 模式: {pat}"
        # 检查敏感路径引用
        for s_path in self.SENSITIVE_PATHS:
            if s_path in code:
                return False, f"代码引用敏感路径: {s_path}"
        return True, ""

    def stage_mutation(self, strategy_id: str,
                       old_code: str, new_code: str) -> str:
        """阶段二-提交：生成变异提案，存入 pending 队列。

        Args:
            strategy_id: 变异策略标识。
            old_code: 变异前代码。
            new_code: 变异后代码。

        Returns:
            proposal_id: 提案 UUID，用于后续 approve/reject。
        """
        # 先做静态检查
        ok, reason = self.check_code(new_code)
        if not ok:
            raise GuardError(f"变异被拒绝：{reason}")

        proposal_id = str(uuid.uuid4())
        proposal = {
            "proposal_id": proposal_id,
            "strategy_id": strategy_id,
            "old_code": old_code,
            "new_code": new_code,
            "status": "pending",
            "old_len": len(old_code),
            "new_len": len(new_code),
        }
        proposal_path = self.pending_dir / f"{proposal_id}.json"
        try:
            with open(proposal_path, "w", encoding="utf-8") as f:
                json.dump(proposal, f, ensure_ascii=False, indent=2)
        except OSError as e:
            raise GuardError(f"写入提案文件失败：{e}") from e
        return proposal_id

    def approve_mutation(self, proposal_id: str) -> tuple[bool, str]:
        """阶段二-审批：验证并批准变异提案。

        验证通过后，提案状态从 pending → approved。
        验证失败则提案被标记为 rejected。

        Returns:
            (True, "执行摘要") | (False, "拒绝原因")
        """
        proposal_path = self.pending_dir / f"{proposal_id}.json"
        if not proposal_path.exists():
            return False, f"提案不存在: {proposal_id}"

        try:
            with open(proposal_path, "r", encoding="utf-8") as f:
                proposal: dict = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            return False, f"读取提案失败：{e}"

        if proposal.get("status") != "pending":
            return False, f"提案状态不是 pending: {proposal.get('status')}"

        new_code: str = proposal.get("new_code", "")

        # 二次扫描——变异过程中代码可能已被修改
        ok, reason = self.check_code(new_code)
        if not ok:
            proposal["status"] = "rejected"
            proposal["reject_reason"] = reason
            self._save_proposal(proposal_path, proposal)
            return False, reason

        proposal["status"] = "approved"
        self._save_proposal(proposal_path, proposal)

        summary = (
            f"strategy={proposal['strategy_id']}, "
            f"size={proposal['old_len']}→{proposal['new_len']}B"
        )
        return True, summary

    def reject_mutation(self, proposal_id: str,
                        reason: str = "手动拒绝") -> bool:
        """拒绝变异提案。"""
        proposal_path = self.pending_dir / f"{proposal_id}.json"
        if not proposal_path.exists():
            return False
        try:
            with open(proposal_path, "r", encoding="utf-8") as f:
                proposal: dict = json.load(f)
        except (OSError, json.JSONDecodeError):
            return False
        proposal["status"] = "rejected"
        proposal["reject_reason"] = reason
        self._save_proposal(proposal_path, proposal)
        return True

    # ── 参数边界检查 ──────────────────────────────────────────────

    def check_param(self, value: float, min_val: Optional[float] = None,
                    max_val: Optional[float] = None) -> tuple[bool, str]:
        """参数边界检查：拒绝 NaN、INF 和越界值。

        Args:
            value: 待检查的值。
            min_val: 最小值（含），None 表示无下限。
            max_val: 最大值（含），None 表示无上限。

        Returns:
            (True, "允许") | (False, "拒绝原因")
        """
        if isinstance(value, (int, float)):
            if math.isnan(value):
                return False, "参数值为 NaN"
            if math.isinf(value):
                return False, f"参数值为无穷大: {value}"
        if min_val is not None and value < min_val:
            return False, f"参数 {value} 低于最小值 {min_val}"
        if max_val is not None and value > max_val:
            return False, f"参数 {value} 超过最大值 {max_val}"
        return True, "允许"

    # ── 用户自定义 deny 模式 ──────────────────────────────────────

    def add_user_deny(self, pattern: str) -> bool:
        """添加用户自定义 deny 模式（运行时不可修改内置列表）。"""
        if pattern in self.DENY_LIST or pattern in self._user_deny:
            return False
        self._user_deny.append(pattern)
        return True

    # ── 内部工具 ──────────────────────────────────────────────────

    @staticmethod
    def _save_proposal(path: Path, proposal: dict) -> None:
        """覆写提案文件。"""
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(proposal, f, ensure_ascii=False, indent=2)
        except OSError as e:
            raise GuardError(f"写入提案文件失败：{e}") from e

    @staticmethod
    def is_safe_path(path_str: str) -> tuple[bool, str]:
        """检查路径是否在敏感区域外。"""
        resolved = os.path.realpath(path_str)
        for s_path in SafetyGuard.SENSITIVE_PATHS:
            if resolved.startswith(s_path):
                return False, f"路径在敏感区域内: {s_path}"
        return True, "允许"
