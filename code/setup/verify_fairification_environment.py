#!/usr/bin/env python3
"""Verify the local FAIRification core analysis environment.

This script validates the Python interpreter and package imports only. It does
not access Dimensions, read project data, or run the FAIRification analysis.
"""

from __future__ import annotations

import importlib
import platform
import sys
from importlib.metadata import PackageNotFoundError, version

MIN_PYTHON = (3, 10)
MAX_PYTHON_EXCLUSIVE = (3, 13)
CORE_PACKAGES = {
    "numpy": "numpy",
    "pandas": "pandas",
    "scipy": "scipy",
    "sklearn": "scikit-learn",
    "statsmodels": "statsmodels",
    "patsy": "patsy",
    "matplotlib": "matplotlib",
    "openpyxl": "openpyxl",
}
OPTIONAL_PACKAGES = {
    "igraph": "igraph",
    "leidenalg": "leidenalg",
}


def package_status(module_name: str, distribution_name: str) -> tuple[bool, str]:
    try:
        importlib.import_module(module_name)
        try:
            return True, version(distribution_name)
        except PackageNotFoundError:
            return True, "imported; distribution version unavailable"
    except Exception as exc:  # noqa: BLE001 - report import causes for setup diagnosis.
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    print("FAIRification local environment preflight")
    print(f"Python: {platform.python_version()} ({sys.executable})")
    print(f"Platform: {platform.platform()}")
    py_ok = MIN_PYTHON <= sys.version_info[:2] < MAX_PYTHON_EXCLUSIVE
    print(f"Python supported range [3.10, 3.13): {'PASS' if py_ok else 'FAIL'}")

    print("\nCore packages:")
    core_ok = py_ok
    for module_name, distribution_name in CORE_PACKAGES.items():
        ok, detail = package_status(module_name, distribution_name)
        print(f"  {'PASS' if ok else 'FAIL'}  {distribution_name}: {detail}")
        core_ok = core_ok and ok

    print("\nOptional exploratory packages:")
    optional_ok = True
    for module_name, distribution_name in OPTIONAL_PACKAGES.items():
        ok, detail = package_status(module_name, distribution_name)
        print(f"  {'PASS' if ok else 'NOT INSTALLED'}  {distribution_name}: {detail}")
        optional_ok = optional_ok and ok

    print("\nResult:")
    if core_ok:
        print("CORE ENVIRONMENT READY")
        if not optional_ok:
            print("Optional community-analysis packages are absent; this does not block the core protocol.")
        return 0
    print("CORE ENVIRONMENT NOT READY")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
