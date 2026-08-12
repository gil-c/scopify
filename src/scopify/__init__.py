"""Scopify — strict accessibility linter for Python.

Public surface kept intentionally small for the POC: only the visibility
markers are re-exported. Everything else lives in submodules and is
consumed via the CLI or the :mod:`scopify.engine` orchestrator.
"""

from scopify.markers import Visibility, dynamic, internal, private, public

__all__ = ["Visibility", "public", "internal", "private", "dynamic"]
__version__ = "0.0.1"

