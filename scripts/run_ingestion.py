import argparse
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).parent.parent)
)

from domains import list_domains
from ingestion.pipeline import IngestionPipeline


def main():
    parser = argparse.ArgumentParser(
        description="Domain Onboarding CLI"
    )

    parser.add_argument(
        "--domain",
        type=str,
        help="Domain ID to ingest",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force full re-index",
    )

    parser.add_argument(
        "--list-domains",
        action="store_true",
        help="List domains",
    )

    args = parser.parse_args()

    if args.list_domains:
        print("Available domains:", list_domains())
        return

    if not args.domain:
        parser.print_help()
        return

    print("=" * 60)
    print(f"DOMAIN ONBOARDING: {args.domain}")
    print("=" * 60)

    pipeline = IngestionPipeline(args.domain)

    result = pipeline.run(
        force_reindex=args.force
    )

    print("\n" + "=" * 60)
    print(f"HOÀN THÀNH — {result.domain_id}")
    print("=" * 60)

    print(f"Loaded       : {result.total_loaded}")
    print(f"Valid        : {result.total_valid}")
    print(f"After dedup  : {result.total_after_dedup}")
    print(f"Chunks       : {result.total_chunks}")
    print(f"Duplicates   : {len(result.removed_duplicates)}")
    print(f"Errors       : {len(result.validation_errors)}")


if __name__ == "__main__":
    main()