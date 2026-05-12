"""Entry point for the thematic analysis pipeline."""

import argparse
import sys
from pathlib import Path


def main() -> None:
    """Entry point for the thematic analysis pipeline."""
    parser = argparse.ArgumentParser(
        description="Qualitative Thematic Analysis Pipeline"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # convert subcommand
    convert_parser = subparsers.add_parser(
        "convert",
        help="Convert raw CSV data to validated Parquet format",
    )
    convert_parser.add_argument(
        "--exemplars-csv",
        type=Path,
        default=Path("data/raw/data.csv"),
        help="Path to exemplars CSV file",
    )
    convert_parser.add_argument(
        "--tags-csv",
        type=Path,
        default=Path("data/raw/tags.csv"),
        help="Path to tags CSV file",
    )
    convert_parser.add_argument(
        "--exemplars-parquet",
        type=Path,
        default=Path("data/processed/exemplars.parquet"),
        help="Output path for exemplars Parquet",
    )
    convert_parser.add_argument(
        "--tags-parquet",
        type=Path,
        default=Path("data/processed/tags.parquet"),
        help="Output path for tags Parquet",
    )

    args = parser.parse_args()

    # Add src/python to sys.path for imports
    src_dir = Path(__file__).parent / "src" / "python"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    from persistence.converter import convert_csvs

    if args.command == "convert":
        stats = convert_csvs(
            exemplars_csv=args.exemplars_csv,
            tags_csv=args.tags_csv,
            exemplars_parquet=args.exemplars_parquet,
            tags_parquet=args.tags_parquet,
        )
        print("\nConversion Summary:")
        for artifact, s in stats.items():
            print(f"  {artifact}: {s['input_rows']} rows -> {s['output_rows']} rows")
            print(f"    size: {s['input_bytes']} -> {s['output_bytes']} bytes")
            print(f"    compression ratio: {s['compression_ratio']:.1%}")


if __name__ == "__main__":
    main()
