"""Diagnostic model emitted by all Scopify rules."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Severity = Literal["error", "warning", "hint"]


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    file: Path
    line: int
    column: int
    severity: Severity = "error"
    # Name of the offending symbol; used by the LSP layer to widen the
    # underline to the full identifier instead of a single character.
    symbol: str | None = None

    def format(self) -> str:
        sev = self.severity.upper()
        return f"{self.file}:{self.line}:{self.column}: {sev} {self.code} {self.message}"


