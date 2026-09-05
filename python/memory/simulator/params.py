"""§4.7 v6.1 frozen defaults. Calibration may overlay values, not formulas."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BJ = timezone(timedelta(hours=8))
# 2026-08-17 00:00 北京时间：空闲档，测试确定性
DEFAULT_TS = datetime(2026, 8, 17, 0, 0, tzinfo=BJ).timestamp()

_OVERLAY_PATH = Path(__file__).with_name("params_overlay.json")

# (max_age_seconds, survival s). age 落入第一个 age <= max 的桶。
DEFAULT_RHO_AGE_TABLE: tuple[tuple[float, float], ...] = (
	(0.0, 1.0),
	(60.0, 1.0),
	(300.0, 1.0),
	(600.0, 0.8),
	(1800.0, 0.5),
	(3600.0, 0.2),
	(7200.0, 0.05),
	(float("inf"), 0.0),
)


@dataclass(frozen=True)
class Params:
	g: int = 64
	alpha_hit: float = 0.95
	kappa: float = 0.8  # P2 默认检索档；推理档 0.4 仅校准扫描
	theta: float = 0.35
	tau_switch: float = 0.85
	beta: int = 8
	alpha_win: float = 0.55
	t_k_count: int = 3
	r_orig: float = 1.0
	r_stub: float = 0.25
	r_summary: float = 0.6
	r_cap: int = 24
	horizons: tuple[int, ...] = (4, 8, 16)
	window_tokens: int = 128_000
	reserve_tokens: int = 2_048
	o_mean: float = 800.0
	eps_d: float = 1e-9
	j_round_ndigits: int = 9
	provider: str = "deepseek"
	model: str = "deepseek-v4-flash"
	price_slot: str = "offpeak"
	lambda_q: float = 2.0  # 丢信息换成钱：约几轮补救的代价（C_qual = λ_q·p_o·o_mean·(D/|M|)）
	default_ts: float = DEFAULT_TS
	invoice_w_phys_zero: bool = True
	c_cmp: float = 0.0  # P0 stub
	min_middle_edit_gap: int = 4
	c2_min_gain_chars: int = 4000  # C2 收益门：待压缩区比摘要文本至少大这么多字符才压缩
	c2_min_save_ratio: float = 0.25  # C2 收益门：压缩后投影必须比全量至少小这么多比例（否则拒绝压缩）
	# 扩展闸：新区 ≥ 已冻区的 25%（不再要求整段等量）；剩余轮次 ≥8；2× 安全边际
	c2_extend_ratio: float = 0.25
	c2_extend_min_remaining_turns: int = 8
	c2_extend_price_ratio: float = 30.0  # miss/hit 价比（DeepSeek ≈30x）
	c2_extend_safety_margin: float = 2.0
	# 压缩态扩展与 θ 门解耦：首压后 Q 常 <θ，不解耦则扩展永不触发、省幅封顶
	c2_extend_decouple: bool = True
	# Path A 压力门「输出预留」：给本轮输出预留的 token，保证「离硬顶 l_hard_send 留够
	# 输出余量才压缩」。压力门 = (l_hard_send − c2_output_reserve − tail_budget) / window，
	# **窗口自适应**（l_hard_send 随窗口变），切换模型/窗口大小不一致时结果不串味。
	# 默认 0 = 不预留（兼容旧行为，压力门退化为 (l_hard_send − tail)/window）。
	c2_output_reserve: int = 0
	rho_age_table: tuple[tuple[float, float], ...] = DEFAULT_RHO_AGE_TABLE
	# A1（优化4）：缓存冷却平滑因子 ω(Δt)=max(ω_floor, e^(−Δt/T½))——age 衰减交给 ω 的
	# 平滑下包络，TTL 硬跳闸不再把预测命中打到 0（消除「挂机后短问候被误压缩」）。
	# **已固化开启**（原 XEYO_CACHE_COOLDOWN_OMEGA 键已删，cache_model.cooldown_enabled 恒 True）。
	omega_half_life_min: float = 60.0
	omega_floor: float = 0.4

	@property
	def l_max(self) -> int:
		return min(
			self.window_tokens - self.reserve_tokens,
			int(self.alpha_win * self.window_tokens),
		)

	@property
	def l_hard_send(self) -> int:
		return self.window_tokens - self.reserve_tokens


def _parse_table(raw: Any) -> tuple[tuple[float, float], ...]:
	if not raw:
		return DEFAULT_RHO_AGE_TABLE
	out: list[tuple[float, float]] = []
	for row in raw:
		age, s = row[0], row[1]
		age_f = float("inf") if age in ("inf", None) else float(age)
		out.append((age_f, float(s)))
	out.sort(key=lambda x: x[0])
	return tuple(out)


def overlay_path() -> Path:
	return _OVERLAY_PATH


def load_overlay(path: Path | None = None) -> dict[str, Any]:
	p = path or _OVERLAY_PATH
	if not p.is_file():
		return {}
	try:
		data = json.loads(p.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return {}
	return data if isinstance(data, dict) else {}


def load_params(path: Path | None = None, **overrides: Any) -> Params:
	base = Params()
	data = load_overlay(path)
	allowed = {f.name for f in fields(Params)}
	kwargs: dict[str, Any] = {}
	for key, val in data.items():
		if key not in allowed:
			continue
		if key == "horizons":
			kwargs[key] = tuple(int(x) for x in val)
		elif key == "rho_age_table":
			kwargs[key] = _parse_table(val)
		else:
			kwargs[key] = val
	kwargs.update({k: v for k, v in overrides.items() if k in allowed})
	return replace(base, **kwargs) if kwargs else base


def write_overlay(updates: dict[str, Any], path: Path | None = None) -> Path:
	"""Calibration only. Does not edit formula modules."""
	p = path or _OVERLAY_PATH
	cur = load_overlay(p)
	cur.update(updates)
	p.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	return p


def params_dict(p: Params) -> dict[str, Any]:
	d = asdict(p)
	d["rho_age_table"] = [
		["inf" if a == float("inf") else a, s] for a, s in p.rho_age_table
	]
	d["horizons"] = list(p.horizons)
	d["l_max"] = p.l_max
	return d
