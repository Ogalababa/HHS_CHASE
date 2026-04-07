"""
Backend package entry point.

Rationale: Declare `backend` as an explicit Python package to make imports
stable across different execution contexts (tests, CLI, IDE), avoiding
implicit namespace-package behavior.
"""

