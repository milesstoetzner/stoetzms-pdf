"""Typed parsing of YAML data into dataclasses.

The configuration schema is the set of dataclasses in :mod:`config`; this
module walks their type hints, checks every value, rejects unknown keys and
records where each object came from. Problems are collected in a
:class:`Diagnostics` so one run reports all of them.
"""

from __future__ import annotations

import dataclasses
import datetime
import difflib
import types
import typing
from typing import Any, Literal

from .errors import Diagnostics, Location
from .yamlload import YamlList, YamlMap

_INVALID = object()


def _type_name(value: Any) -> str:
    if value is None:
        return "nothing (null)"
    if isinstance(value, bool):
        return "true/false"
    if isinstance(value, int):
        return "an integer"
    if isinstance(value, float):
        return "a number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, dict):
        return "a mapping"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, datetime.date):
        return "a date"
    return type(value).__name__


def _expected_name(tp: Any) -> str:
    origin = typing.get_origin(tp)
    if origin is Literal:
        return "one of " + ", ".join(repr(a) for a in typing.get_args(tp))
    if origin in (typing.Union, types.UnionType):
        return " or ".join(_expected_name(a) for a in typing.get_args(tp) if a is not type(None))
    if origin is list:
        return "a list"
    if origin is dict or dataclasses.is_dataclass(tp):
        return "a mapping"
    return {
        bool: "true or false",
        int: "an integer",
        float: "a number",
        str: "text",
        datetime.date: "a date",
    }.get(tp, getattr(tp, "__name__", str(tp)))


class SchemaParser:
    def __init__(self, filename: str, diagnostics: Diagnostics):
        self.filename = filename
        self.diag = diagnostics

    def loc(self, path: str, line: int | None) -> Location:
        return Location(self.filename, line, path or None)

    def error(self, message: str, path: str, line: int | None) -> None:
        self.diag.error(message, self.loc(path, line))

    # -- entry point -------------------------------------------------------

    def parse(self, cls: type, data: Any, path: str = "", line: int | None = None) -> Any:
        value = self._value(cls, data, path, line)
        return None if value is _INVALID else value

    # -- dispatch ----------------------------------------------------------

    def _value(self, tp: Any, value: Any, path: str, line: int | None) -> Any:
        origin = typing.get_origin(tp)
        args = typing.get_args(tp)

        if origin in (typing.Union, types.UnionType):
            options = [a for a in args if a is not type(None)]
            if value is None:
                if type(None) in args:
                    return None
                self.error(f"expected {_expected_name(tp)}, got nothing (null)", path, line)
                return _INVALID
            chosen = self._choose_union_member(options, value)
            if chosen is None:
                self.error(f"expected {_expected_name(tp)}, got {_type_name(value)}", path, line)
                return _INVALID
            return self._value(chosen, value, path, line)

        if origin is Literal:
            if value in args and not isinstance(value, bool):
                return value
            choices = ", ".join(repr(a) for a in args)
            hint = ""
            if isinstance(value, str):
                close = difflib.get_close_matches(value, [str(a) for a in args], n=1)
                if close:
                    hint = f" (did you mean {close[0]!r}?)"
            self.error(f"invalid value {value!r}; expected one of {choices}{hint}", path, line)
            return _INVALID

        if origin is list:
            if not isinstance(value, list):
                self.error(f"expected a list, got {_type_name(value)}", path, line)
                return _INVALID
            item_type = args[0] if args else Any
            lines = value.item_lines if isinstance(value, YamlList) else [line] * len(value)
            items = []
            for index, item in enumerate(value):
                parsed = self._value(item_type, item, f"{path}[{index}]", lines[index])
                if parsed is not _INVALID:
                    items.append(parsed)
            return items

        if origin is dict:
            if not isinstance(value, dict):
                self.error(f"expected a mapping, got {_type_name(value)}", path, line)
                return _INVALID
            value_type = args[1] if len(args) == 2 else Any
            result = {}
            for key, item in value.items():
                key_line = value.key_lines.get(key, line) if isinstance(value, YamlMap) else line
                if not isinstance(key, str):
                    self.error(f"keys must be text, got {_type_name(key)}", path, key_line)
                    continue
                parsed = self._value(value_type, item, f"{path}.{key}", key_line)
                if parsed is not _INVALID:
                    result[key] = parsed
            return result

        if dataclasses.is_dataclass(tp):
            return self._dataclass(tp, value, path, line)

        return self._scalar(tp, value, path, line)

    @staticmethod
    def _choose_union_member(options: list[Any], value: Any) -> Any:
        def accepts(tp: Any) -> bool:
            origin = typing.get_origin(tp)
            if origin is Literal:
                return value in typing.get_args(tp)
            if origin is list:
                return isinstance(value, list)
            if origin is dict:
                return isinstance(value, dict)
            if dataclasses.is_dataclass(tp):
                return isinstance(value, dict) or (
                    hasattr(tp, "from_shorthand") and tp.from_shorthand(value) is not None
                )
            if tp is bool:
                return isinstance(value, bool)
            if tp is int:
                return isinstance(value, int) and not isinstance(value, bool)
            if tp is float:
                return isinstance(value, (int, float)) and not isinstance(value, bool)
            if tp is datetime.date:
                return isinstance(value, datetime.date)
            if tp is str:
                return isinstance(value, (str, int, float)) and not isinstance(value, bool)
            return False

        for option in options:
            if accepts(option):
                return option
        return None

    def _scalar(self, tp: Any, value: Any, path: str, line: int | None) -> Any:
        ok = False
        if tp is Any:
            return value
        if tp is bool:
            ok = isinstance(value, bool)
        elif tp is int:
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif tp is float:
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
            if ok:
                value = float(value)
        elif tp is str:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value = str(value)
            elif isinstance(value, datetime.date):
                value = value.isoformat()
            ok = isinstance(value, str)
        elif tp is datetime.date:
            ok = isinstance(value, datetime.date)
        if not ok:
            self.error(f"expected {_expected_name(tp)}, got {_type_name(value)}", path, line)
            return _INVALID
        return value

    def _dataclass(self, cls: type, value: Any, path: str, line: int | None) -> Any:
        if not isinstance(value, dict):
            shorthand = cls.from_shorthand(value) if hasattr(cls, "from_shorthand") else None
            if shorthand is None:
                self.error(f"expected {_expected_name(cls)}, got {_type_name(value)}", path, line)
                return _INVALID
            value = shorthand

        hints = typing.get_type_hints(cls)
        known = {f.name: f for f in dataclasses.fields(cls) if f.init}
        key_lines = value.key_lines if isinstance(value, YamlMap) else {}
        obj_line = getattr(value, "line", None) or line

        for key in value:
            if key not in known:
                key_line = key_lines.get(key, obj_line)
                close = difflib.get_close_matches(str(key), list(known), n=1)
                hint = f" (did you mean {close[0]!r}?)" if close else ""
                where = f"{path}.{key}" if path else str(key)
                self.error(f"unsupported option {key!r}{hint}", where, key_line)

        kwargs: dict[str, Any] = {}
        field_locs: dict[str, Location] = {}
        ok = True
        for name, f in known.items():
            child_path = f"{path}.{name}" if path else name
            if name in value:
                child_line = key_lines.get(name, obj_line)
                field_locs[name] = self.loc(child_path, child_line)
                parsed = self._value(hints[name], value[name], child_path, child_line)
                if parsed is _INVALID:
                    ok = False
                    continue
                kwargs[name] = parsed
            elif f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
                self.error(f"missing required option {name!r}", path or "<top level>", obj_line)
                ok = False

        if not ok:
            return _INVALID
        obj = cls(**kwargs)
        obj._loc = self.loc(path, obj_line)
        obj._field_locs = field_locs
        obj._given = set(kwargs)
        return obj


def loc_of(obj: Any, field: str | None = None) -> Location | None:
    """Location of a parsed object, or of one of its fields if it was given."""
    if field is not None:
        found = getattr(obj, "_field_locs", {}).get(field)
        if found is not None:
            return found
    return getattr(obj, "_loc", None)


def was_given(obj: Any, field: str) -> bool:
    return field in getattr(obj, "_given", set())
