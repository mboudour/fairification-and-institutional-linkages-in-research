# Core environment validation

The pinned core package set in `requirements-core.txt` was import-tested on 2026-10-24 in a clean CPython 3.12.3 virtual environment on Linux x86_64.

Validated versions:

- numpy 1.26.4
- pandas 2.2.3
- scipy 1.13.1
- scikit-learn 1.5.2
- statsmodels 0.14.4
- patsy 1.0.1
- matplotlib 3.9.2
- openpyxl 3.1.5

This confirms the core stack imports together. It is not a substitute for the local macOS preflight check, and it does not validate Dimensions access, source-to-Dimensions matching, the FAIRification data schema, or FAIR-specific analytical code.
