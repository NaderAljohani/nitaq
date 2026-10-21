# Development

Use Python 3.13 and a fresh virtual environment. Install `requirements-lock.txt`
to reproduce the tested dependencies, or `requirements-dev.txt` for development
within the declared version ranges.

Run `python scripts/check_release.py` and `python -m pytest -q` before a change.
Tests run without API credentials. Keep generated caches, credentials, and local
environment files out of version control. Update the documented results when
changing data processing or evaluation.
