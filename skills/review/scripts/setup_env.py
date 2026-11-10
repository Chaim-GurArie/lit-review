#!/usr/bin/env python3
"""Check (and optionally install) the Python packages the pipeline needs.

Usage:
    python3 setup_env.py            # check only, print JSON
    python3 setup_env.py --install  # try to install what is missing

Prints a JSON object:
    {"python": "3.12.1", "ok": true, "missing": [], "installed": [], "errors": []}
"""
import importlib
import json
import subprocess
import sys

REQUIRED = {
    # import name: pip package
    "pdfplumber": "pdfplumber",
    "docx": "python-docx",
    "yaml": "pyyaml",
}


def missing_packages():
    missing = []
    for mod, pkg in REQUIRED.items():
        try:
            importlib.import_module(mod)
        except Exception:
            missing.append(pkg)
    return missing


def try_install(pkgs):
    errors = []
    attempts = [
        [sys.executable, "-m", "pip", "install", "--user", "--quiet"],
        [sys.executable, "-m", "pip", "install", "--quiet"],
        [sys.executable, "-m", "pip", "install", "--user", "--quiet", "--break-system-packages"],
    ]
    for base in attempts:
        res = subprocess.run(base + pkgs, capture_output=True, text=True)
        if res.returncode == 0:
            importlib.invalidate_caches()
            return []
        errors.append((res.stderr or res.stdout).strip()[-600:])
    return errors


def main():
    result = {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "ok": False,
        "missing": [],
        "installed": [],
        "errors": [],
    }
    if sys.version_info < (3, 9):
        result["errors"].append("Python 3.9 or newer is required.")
        print(json.dumps(result, ensure_ascii=False))
        return 1

    missing = missing_packages()
    if missing and "--install" in sys.argv:
        errs = try_install(missing)
        still = missing_packages()
        result["installed"] = [p for p in missing if p not in still]
        result["errors"] = errs if still else []
        missing = still

    result["missing"] = missing
    result["ok"] = not missing
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
