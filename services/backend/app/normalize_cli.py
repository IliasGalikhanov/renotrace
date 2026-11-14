"""Run structured history through normalization and the real ledger."""

import argparse
import json
from pathlib import Path

from .ledger import calculate
from .normalization import HistoryInput, normalize


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--case", help="Structured synthetic scenario, default FIN-01")
    choice.add_argument("--input", type=Path, help="HistoryInput JSON file")
    parser.add_argument("--fixtures", type=Path, default=Path("fixtures/normalization_cases.json"))
    args = parser.parse_args()
    try:
        if args.input is not None:
            payload = args.input.read_text(encoding="utf-8")
        else:
            data = json.loads(args.fixtures.read_text(encoding="utf-8"))
            if data.get("synthetic") is not True:
                parser.error("The example fixture must be explicitly synthetic")
            case_id = args.case or "FIN-01"
            case = next((row for row in data["cases"] if row["id"] == case_id), None)
            if case is None:
                parser.error(f"Unknown structured case: {case_id}")
            payload = json.dumps(case["input"])
        normalized = normalize(HistoryInput.model_validate_json(payload))
        result = calculate(normalized.ledger_input)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "normalization": normalized.model_dump(mode="json"),
                "calculation": result.model_dump(mode="json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
