"""域6：评估与验证。

导入此包即注册默认实现到 registry。
"""
from conch.domains.eval.step_eval import StepEvaluator  # noqa: F401

__all__ = ["StepEvaluator"]
