"""
OMNIplus ON infrastructure adapter package.

Rationale: Vendor-specific clients/config live in infrastructure to keep the
core independent from external APIs and credentials management.
"""

from __future__ import annotations

from .client import OmniplusAuthConfig, OmniplusOnClient
from .constants import SIGNAL_ID_TO_NAME, SIGNAL_IDS_DEFAULT

__all__ = [
    "OmniplusOnClient",
    "OmniplusAuthConfig",
    "SIGNAL_ID_TO_NAME",
    "SIGNAL_IDS_DEFAULT",
]

