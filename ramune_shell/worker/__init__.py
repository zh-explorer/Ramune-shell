"""Ramune-shell remote worker daemon.

Exports for feature developers:
- register_feature: register a worker-side handler
- get_state: access per-session state dict from within a handler
"""

from ramune_shell.worker.dispatch import register_feature, get_state

__all__ = ["register_feature", "get_state"]
