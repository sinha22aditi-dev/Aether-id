"""
Independent Verification CLI Tool.
Usage:
  python verify.py --record-id 0 --canonical-json ./record_0.json
  python verify.py --record-id 0 --from-cache
  python verify.py --record-id 999 --canonical-json ./anything.json
"""

import argparse
import json
import logging
import os
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pipeline.canon.canonicalize import Canonicalizer
from pipeline.chain.client import BlockchainClient
from pipeline.chain.reader import BlockchainReader
from pipeline.storage.cache import MetadataCache
from pipeline.verifier import RecordVerifier

load_dotenv()
console = Console()
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


def print_verification_report(result):
    """Renders a rich formatted verification summary."""
    status_colors = {
        "VERIFIED": "bold green",
        "TAMPER DETECTED": "bold red",
        "RECORD_NOT_FOUND": "bold yellow",
        "INSUFFICIENT_DATA": "bold magenta",
        "SOURCE_UNAVAILABLE": "bold blue",
        "CHAIN_RPC_ERROR": "bold orange3",
    }
    color = status_colors.get(result.status, "white")

    console.print()
    console.print(
        Panel(
            f"[{color}][ {result.status} ][/{color}]\n\n{result.message}",
            title=f"Verification Report — Record #{result.record_id}",
            border_style=color,
        )
    )

    table = Table(title="Record Telemetry & Cryptographic Verification", show_header=True, header_style="bold cyan")
    table.add_column("Property", style="dim", width=25)
    table.add_column("Value")

    table.add_row("Record ID", str(result.record_id))
    table.add_row("Status", f"[{color}]{result.status}[/{color}]")
    if result.computed_hash:
        table.add_row("Computed Hash (SHA-256)", result.computed_hash)
    if result.on_chain_hash:
        table.add_row("On-Chain Hash", result.on_chain_hash)
    table.add_row("Hash Match", "YES (100% Intact)" if result.is_hash_match else "NO (Tampered / Mismatch)")
    table.add_row("Live Source Reachable", "YES" if result.source_url_reachable else "NO / Untested")

    if result.on_chain_record and result.on_chain_record.exists:
        table.add_row("On-Chain Submitter", result.on_chain_record.submitter)
        table.add_row("On-Chain Timestamp", str(result.on_chain_record.timestamp))
        table.add_row("Metadata URI", result.on_chain_record.metadata_uri)

    console.print(table)

    if result.field_diffs:
        console.print()
        diff_table = Table(title="[bold red]Field-Level Tampering Discrepancies (vs Cached Original)[/bold red]", show_header=True)
        diff_table.add_column("Field", style="bold yellow")
        diff_table.add_column("Original Commitment (On-Chain Reference)", style="green")
        diff_table.add_column("Supplied (Tampered) Value", style="red")

        for d in result.field_diffs:
            diff_table.add_row(d.field_name, str(d.original_value), str(d.tampered_value))

        console.print(diff_table)

    console.print()


def main():
    parser = argparse.ArgumentParser(
        description="Independent Blockchain Record Verification CLI for Face ID Pipeline"
    )
    parser.add_argument("--record-id", type=int, required=True, help="On-chain sequential recordId to verify")
    parser.add_argument("--canonical-json", type=str, help="Path to JSON file containing immutable verifiable fields")
    parser.add_argument("--from-cache", action="store_true", help="Load verifiable data directly from local SQLite cache for testing")
    parser.add_argument("--no-live-check", action="store_true", help="Skip live HTTP reachability check of source URL")

    args = parser.parse_args()

    client = BlockchainClient()
    reader = BlockchainReader(client=client)
    cache = MetadataCache()
    verifier = RecordVerifier(reader=reader, cache=cache, check_live_source=not args.no_live_check)

    data = None
    if args.canonical_json:
        if not os.path.exists(args.canonical_json):
            console.print(f"[bold red]Error: JSON file not found at {args.canonical_json}[/bold red]")
            sys.exit(1)
        with open(args.canonical_json, "r", encoding="utf-8") as f:
            data = json.load(f)
    elif args.from_cache:
        cached_rec = cache.get_record(args.record_id)
        if not cached_rec:
            console.print(f"[yellow]Warning: Record #{args.record_id} not found in local cache. Verifying empty payload...[/yellow]")
            data = {}
        else:
            data = cached_rec.immutable_data
            console.print(f"[dim]Loaded immutable payload for Record #{args.record_id} from local cache.[/dim]")
    else:
        console.print("[bold red]Error: Must specify either --canonical-json <path> or --from-cache[/bold red]")
        sys.exit(1)

    result = verifier.verify(args.record_id, data)
    print_verification_report(result)

    # Exit codes
    if result.status == "VERIFIED":
        sys.exit(0)
    elif result.status == "TAMPER DETECTED":
        sys.exit(2)
    elif result.status == "RECORD_NOT_FOUND":
        sys.exit(3)
    elif result.status == "INSUFFICIENT_DATA":
        sys.exit(4)
    elif result.status == "SOURCE_UNAVAILABLE":
        sys.exit(5)
    elif result.status == "CHAIN_RPC_ERROR":
        sys.exit(6)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
