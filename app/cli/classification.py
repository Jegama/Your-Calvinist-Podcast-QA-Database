"""Advance the overnight classification worker against the configured database."""

import argparse

from sqlalchemy import func, select, update

from app.db.engine import get_session
from app.db.models import QAItem
from app.ingest.classification import run_classification_worker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--status", action="store_true", help="Show counts without calling Google")
    action.add_argument("--retry-failed", action="store_true", help="Queue only failed items for another batch")
    args = parser.parse_args()
    if args.status:
        with get_session() as db:
            rows = db.execute(
                select(QAItem.classification_state, func.count())
                .where(QAItem.classification_state.is_not(None)).group_by(QAItem.classification_state)
            )
            print(dict(rows.all()))
    elif args.retry_failed:
        with get_session() as db:
            result = db.execute(
                update(QAItem).where(QAItem.classification_state == "failed")
                .values(classification_state="queued", classification_error=None)
            )
            print(f"Queued {result.rowcount} failed classifications")
    else:
        print(run_classification_worker())


if __name__ == "__main__":
    main()
