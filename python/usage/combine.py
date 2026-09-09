"""厂商用量为权威；厂商拿不到的维度用本机 JSONL 补上。"""

from __future__ import annotations

from typing import Any


def _as_int(v: Any) -> int:
	try:
		return int(v or 0)
	except (TypeError, ValueError):
		return 0


def point_has_usage(point: dict[str, Any] | None) -> bool:
	if not isinstance(point, dict):
		return False
	return (
		_as_int(point.get("requests")) > 0
		or _as_int(point.get("input_hit")) > 0
		or _as_int(point.get("input_miss")) > 0
		or _as_int(point.get("output")) > 0
		or _as_int(point.get("cache_hit")) > 0
		or _as_int(point.get("cache_miss")) > 0
	)


def report_has_usage(report: dict[str, Any] | None) -> bool:
	if not isinstance(report, dict):
		return False
	totals = report.get("totals") if isinstance(report.get("totals"), dict) else {}
	if (
		_as_int(totals.get("requests")) > 0
		or _as_int(totals.get("input_hit")) > 0
		or _as_int(totals.get("input_miss")) > 0
		or _as_int(totals.get("output")) > 0
	):
		return True
	for point in report.get("series") or []:
		if point_has_usage(point):
			return True
	return False


def compose_usage_report(
	vendor: dict[str, Any],
	local: dict[str, Any],
) -> dict[str, Any]:
	"""能拿到的厂商数据作权威；拿不到的（整表或按模型拆分）用本机。

	v4：无金额。source 只表达数据来源（vendor 官方接口 / local 本地账本），
	vendor_ok/vendor_error 供前端标注「本机记账 / 厂商口径」。
	"""
	vendor_ok = bool(vendor.get("vendor_ok"))
	use_vendor_core = vendor_ok and report_has_usage(vendor)
	vendor_models = list(vendor.get("models") or []) if vendor_ok else []
	local_models = list(local.get("models") or [])
	use_vendor_models = bool(vendor_models)

	core = vendor if use_vendor_core else local
	models = vendor_models if use_vendor_models else local_models
	source = "vendor" if use_vendor_core else "local"

	keys = sorted(
		{
			str(k)
			for k in list(vendor.get("keys") or []) + list(local.get("keys") or [])
			if k
		}
	)

	out = dict(core)
	out["models"] = models
	out["keys"] = keys
	out["source"] = source
	out["vendor_ok"] = vendor.get("vendor_ok")
	out["vendor_error"] = vendor.get("vendor_error")
	if "provider" not in out and vendor.get("provider"):
		out["provider"] = vendor.get("provider")
	return out
