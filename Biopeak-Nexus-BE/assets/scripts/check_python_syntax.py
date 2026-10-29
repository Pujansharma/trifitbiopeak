"""Check Python source syntax without importing application packages.

This catches existing Python errors even before Django dependencies or a database
are available. It is intentionally not a replacement for the Django test suite.
"""

import ast
from pathlib import Path


EXCLUDED_DIRECTORIES = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "build", "dist",
}


def main():
    repository = Path(__file__).resolve().parents[2]
    total = 0
    failures = []
    for source_file in sorted(repository.rglob("*.py")):
        relative_path = source_file.relative_to(repository)
        if any(part in EXCLUDED_DIRECTORIES for part in relative_path.parts):
            continue
        total += 1
        try:
            ast.parse(source_file.read_text(encoding="utf-8-sig"), filename=str(relative_path))
        except (SyntaxError, UnicodeError) as error:
            failures.append((relative_path, error))
    for relative_path, error in failures:
        print(f"ERROR {relative_path}: {error}")
    print(f"Python syntax: {total} files checked; {len(failures)} error(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
