"""Compatibility entry point for the Uptime Kuma skills Python modules."""

from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent)]

if __name__ == "__main__":
    import sys
    from importlib import import_module

    sys.exit(import_module("uptime_kuma_skills.cli").main())

from uptime_kuma_skills.client import UptimeKumaSkills
from uptime_kuma_skills.operations import coerce_params, normalize_result, validate_required
from uptime_kuma_skills.redact import REDACTED, redact, redacted_fields
from uptime_kuma_skills.registry import (
    MODULE_OPERATIONS,
    OPERATIONS,
    Effect,
    Operation,
    Param,
    cli_flag_for,
    describe_all,
    describe_operation,
    get_operation,
    list_operations,
    missing_required,
)

__version__ = "0.2.0"

__all__ = [
    "UptimeKumaSkills", "OPERATIONS", "MODULE_OPERATIONS", "Effect", "Operation", "Param",
    "get_operation", "list_operations", "describe_all", "describe_operation",
    "missing_required", "cli_flag_for", "coerce_params", "validate_required",
    "normalize_result", "redact", "redacted_fields", "REDACTED", "__version__",
]
