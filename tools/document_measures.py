"""Write docs/measures.md from the report's TMDL: every measure with its folder, description, format and DAX.

Run at every release, after the semantic model changes:
    .venv/bin/python -m tools.document_measures
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from pipeline import config

MEASURES_FILE = (
    config.ROOT / "powerbi" / "MarketRiskMonitor.SemanticModel" / "definition" / "tables" / "_Measures.tmdl"
)
OUTPUT = config.ROOT / "docs" / "measures.md"


@dataclass
class Measure:
    name: str
    folder: str = ""
    description: str = ""
    format_string: str = ""
    dax: str = ""


def unquote(name: str) -> str:
    return name[1:-1].replace("''", "'") if name.startswith("'") else name


def parse_measures(tmdl: str) -> list[Measure]:
    """Measures of a TMDL table in file order; descriptions come from the `///` lines above each one."""
    measures, description, current, dax_lines = [], "", None, []
    for line in tmdl.splitlines():
        if line.startswith("\t///"):
            description = line.removeprefix("\t///").strip()
        elif line.startswith("\tmeasure "):
            name = line.removeprefix("\tmeasure ").removesuffix("=").strip()
            current, dax_lines = Measure(unquote(name), description=description), []
            measures.append(current)
            description = ""
        elif current is not None and line.startswith("\t\t\t"):
            dax_lines.append(line.removeprefix("\t\t\t"))
        elif current is not None and line.startswith("\t\t"):
            key, _, value = line.strip().partition(": ")
            if key == "formatString":
                current.format_string = value
            elif key == "displayFolder":
                current.folder = value
            current.dax = current.dax or "\n".join(dax_lines).strip()
        elif not line.startswith("\t\t"):
            current = None
    return measures


def to_markdown(measures: list[Measure]) -> str:
    folders = sorted({measure.folder for measure in measures})
    lines = [
        "# Measure dictionary",
        "",
        (
            f"The {len(measures)} DAX measures of the Power BI report, by display folder, generated from the semantic "
            "model (`powerbi/MarketRiskMonitor.SemanticModel`) by `tools/document_measures.py`. Statistics such as "
            "QLIKE, Diebold-Mariano or Kupiec are computed in Python; the measures select and aggregate them."
        ),
        "",
    ]
    for folder in folders:
        in_folder = [measure for measure in measures if measure.folder == folder]
        lines += [f"## {folder or 'No folder'}", ""]
        for measure in in_folder:
            lines += [f"### {measure.name}", "", measure.description, ""]
            if measure.format_string:
                lines += [f"Format: `{measure.format_string}`", ""]
            lines += ["```dax", measure.dax, "```", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the measure dictionary from the TMDL files.")
    parser.add_argument("--measures", type=Path, default=MEASURES_FILE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    measures = parse_measures(args.measures.read_text(encoding="utf-8"))
    args.output.write_text(to_markdown(measures), encoding="utf-8")
    print(f"{len(measures)} measures written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
