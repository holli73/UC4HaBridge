"""Parsing of Automic static VARA exports. No Home Assistant imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Vara:
    """A static VARA: header row (key starting with "_") plus data rows.

    columns maps a header name (leading "_" and any "(...)" suffix stripped)
    to its 1-based column number, so the integration survives column reordering.
    """

    name: str
    columns: dict[str, int] = field(default_factory=dict)
    rows: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def from_export(cls, name: str, export: dict[str, Any]) -> Vara:
        vara = export["data"]["vara"]
        count = int(vara.get("variable_definitions", {}).get("column_count", 5))
        columns: dict[str, int] = {}
        rows: dict[str, tuple[str, ...]] = {}
        for entry in vara.get("static_values", []):
            key = entry["key"]
            values = tuple(
                str(entry.get(f"value{i}", "")).strip() for i in range(1, count + 1)
            )
            if key.startswith("_"):
                for i, header in enumerate(values, start=1):
                    header = header.lstrip("_").split("(", 1)[0].strip()
                    if header:
                        columns[header] = i
            else:
                rows[key] = values
        return cls(name, columns, rows)

    def raw(self, key: str, column: str) -> str | None:
        row = self.rows.get(key)
        index = self.columns.get(column)
        if row is None or index is None or index > len(row):
            return None
        return row[index - 1] or None

    def number(self, key: str, column: str) -> float | None:
        """Parse values like "22.5", " 21" or "+0000000000000022.5000000000000000"."""
        value = self.raw(key, column)
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def integer(self, key: str, column: str) -> int | None:
        value = self.number(key, column)
        return None if value is None else int(value)


@dataclass(frozen=True)
class HeatingData:
    """One coordinator snapshot. Equality drives change detection."""

    summary: Vara
    weekday: Vara
    weekend: Vara

    @property
    def rooms(self) -> list[str]:
        """Rooms are the keys configured in the weekday settings VARA."""
        return sorted(self.weekday.rows)
