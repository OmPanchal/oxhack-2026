"""Export exact AWS hourly quote samples and gap coverage without contacting AWS."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

from app.database import Database
from app.market.history import AwsQuoteArchive, hourly_history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path(__file__).resolve().parents[1] / 'state/engine.sqlite3')
    parser.add_argument('--as-of', help='UTC decision cutoff (ISO timestamp with timezone); defaults to now.')
    parser.add_argument('--output', type=Path, help='New JSON export file; existing files are never overwritten.')
    args = parser.parse_args()
    try:
        cutoff = datetime.fromisoformat(args.as_of.replace('Z', '+00:00')) if args.as_of else datetime.now(timezone.utc)
        if not args.database.is_file():
            raise ValueError(f'Database does not exist: {args.database}')
        report = hourly_history(AwsQuoteArchive(Database(args.database)), cutoff)
        if args.output:
            with args.output.open('x') as stream:
                json.dump(report, stream, indent=2)
                stream.write('\n')
            print(f'Exported {report["hourlySampleCount"]} samples to {args.output}')
        else:
            print(json.dumps({key: value for key, value in report.items() if key != 'samples'}, indent=2))
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f'History export failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
