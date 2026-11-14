"""Run a synthetic reference case or an explicit normalized JSON input."""

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from .ledger import LedgerInput, calculate
from .reference_cases import reference_input


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--case", help="Synthetic case id (default FIN-01)")
    source.add_argument("--input", type=Path, help="Normalized LedgerInput JSON file")
    parser.add_argument("--fixtures", type=Path, default=Path("fixtures/ledger_cases.json"))
    args = parser.parse_args()
    try:
        if args.input is not None:
            history = LedgerInput.model_validate_json(args.input.read_text(encoding="utf-8"))
        else:
            data = json.loads(args.fixtures.read_text(encoding="utf-8"))
            case_id = args.case or "FIN-01"
            case = next((row for row in data["cases"] if row["id"] == case_id), None)
            if case is None:
                parser.error(f"Unknown reference case: {case_id}")
            history = reference_input(case)
        result = calculate(history)
    except (OSError, ValueError, KeyError, TypeError, ValidationError) as exc:
        parser.error(str(exc))
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
