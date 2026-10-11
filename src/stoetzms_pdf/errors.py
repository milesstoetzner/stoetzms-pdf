"""Diagnostics shared by every build stage.

Errors and warnings are collected rather than raised one at a time, so a
single run reports every problem in the configuration and inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Location:
    """Where a problem originates: a config file position or an input file."""

    file: str
    line: int | None = None
    path: str | None = None  # config path, e.g. "sections[1].documents[0].file"

    def __str__(self) -> str:
        where = self.file if self.line is None else f"{self.file}:{self.line}"
        return f"{where} ({self.path})" if self.path else where


@dataclass(frozen=True)
class Diagnostic:
    severity: str  # "error" | "warning"
    message: str
    location: Location | None = None

    def __str__(self) -> str:
        prefix = f"{self.location}: " if self.location else ""
        return f"{self.severity}: {prefix}{self.message}"


@dataclass
class Diagnostics:
    items: list[Diagnostic] = field(default_factory=list)

    def error(self, message: str, location: Location | None = None) -> None:
        self.items.append(Diagnostic("error", message, location))

    def warning(self, message: str, location: Location | None = None) -> None:
        diagnostic = Diagnostic("warning", message, location)
        if diagnostic not in self.items:
            self.items.append(diagnostic)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.items if d.severity == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.items if d.severity == "warning"]

    def raise_if_errors(self, exc_type: type[StoetzmsPdfError] | None = None) -> None:
        if self.errors:
            exc = (exc_type or ValidationError)(self.errors)
            exc.warnings = self.warnings
            raise exc


class StoetzmsPdfError(Exception):
    """Base class; ``exit_code`` is what the CLI returns."""

    exit_code = 1

    def __init__(self, problems: str | list[Diagnostic]):
        if isinstance(problems, str):
            problems = [Diagnostic("error", problems)]
        self.problems = problems
        self.warnings: list[Diagnostic] = []  # filled in by build() for reporting
        super().__init__("\n".join(str(p) for p in problems))


class ValidationError(StoetzmsPdfError):
    """The configuration or an input file is invalid; nothing was written."""

    exit_code = 2


class BuildError(StoetzmsPdfError):
    """Generation or output validation failed; the previous output is kept."""

    exit_code = 1


class StrictModeError(StoetzmsPdfError):
    """--strict was given and there were warnings; nothing was written."""

    exit_code = 3
