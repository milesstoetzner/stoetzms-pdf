"""YAML loading that remembers line numbers and rejects duplicate keys.

PyYAML's safe loader silently keeps the last of two identical keys, which
would let a typo-duplicated ``file:`` quietly replace a document. Mappings
and sequences are loaded into ``dict``/``list`` subclasses that carry the
source line of each key and item so diagnostics can point at them.
"""

from __future__ import annotations

from typing import Any

import yaml


class YamlMap(dict):
    line: int | None = None

    def __init__(self) -> None:
        super().__init__()
        self.key_lines: dict[Any, int] = {}


class YamlList(list):
    line: int | None = None

    def __init__(self) -> None:
        super().__init__()
        self.item_lines: list[int] = []


class YamlLoadError(Exception):
    def __init__(self, message: str, line: int | None = None):
        super().__init__(message)
        self.message = message
        self.line = line


class _Loader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: _Loader, node: yaml.MappingNode) -> YamlMap:
    seen: dict[Any, int] = {}
    for key_node, _ in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            continue
        key = loader.construct_object(key_node, deep=True)
        line = key_node.start_mark.line + 1
        if key in seen:
            raise YamlLoadError(
                f"duplicate key {key!r} (first defined on line {seen[key]})", line
            )
        seen[key] = line
    loader.flatten_mapping(node)
    result = YamlMap()
    result.line = node.start_mark.line + 1
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        try:
            hash(key)
        except TypeError:
            raise YamlLoadError("mapping keys must be plain values", key_node.start_mark.line + 1)
        result[key] = loader.construct_object(value_node, deep=True)
        result.key_lines[key] = key_node.start_mark.line + 1
    return result


def _construct_sequence(loader: _Loader, node: yaml.SequenceNode) -> YamlList:
    result = YamlList()
    result.line = node.start_mark.line + 1
    for child in node.value:
        result.append(loader.construct_object(child, deep=True))
        result.item_lines.append(child.start_mark.line + 1)
    return result


_Loader.add_constructor("tag:yaml.org,2002:map", _construct_mapping)
_Loader.add_constructor("tag:yaml.org,2002:seq", _construct_sequence)


def load_yaml(text: str) -> Any:
    try:
        return yaml.load(text, Loader=_Loader)  # noqa: S506 - safe loader subclass
    except YamlLoadError:
        raise
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        line = mark.line + 1 if mark else None
        problem = exc.problem or str(exc)
        if exc.context:
            problem = f"{problem} ({exc.context})"
        raise YamlLoadError(f"invalid YAML: {problem}", line) from None
    except yaml.YAMLError as exc:
        raise YamlLoadError(f"invalid YAML: {exc}") from None
