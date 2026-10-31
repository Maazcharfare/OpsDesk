# Contributing

Thanks for helping improve OpsDesk.

## Local setup

Use Python 3.12 or newer, create a virtual environment, and install development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

On Windows PowerShell, activate with `./.venv/Scripts/Activate.ps1`.

## Before opening a pull request

Run the same checks as CI:

```bash
ruff check .
pip-audit -r requirements-dev.txt
python -m py_compile main.py test_main.py test_database_tools.py scripts/backup_db.py scripts/restore_db.py scripts/seed_demo.py
python -m pytest -v
```

Keep changes focused, add regression tests for bug fixes, and describe the user-visible behavior and security impact. Never commit `.env` files, credentials, database files, TLS keys, or production data. Do not enable production service checks without tested outbound network restrictions.
