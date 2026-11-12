"""Prometheus Desktop: the desktop application around the existing Prometheus core.

The core (prometheus.py and its modules) stays the single source of truth. This package holds only
what a desktop application needs on top of it: start-up, platform integration and the window.
"""

APP_NAME = "Prometheus"
APP_ID = "Prometheus.Desktop"
__version__ = "0.1.0"
