"""
Main Entry Point CLI for Face ID + Blockchain Verification Pipeline.
Usage:
  python main.py --image path/to/consented_face.jpg
  python main.py --image path/to/group.jpg --face-index 0
  python main.py --image path/to/photo.png --review
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

from pipeline.pipeline import PipelineExecutionResult, VerificationPipeline

load_dotenv()
console = Console()
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def render_pipeline_summary(result: PipelineExecutionResult):
    """Renders formatted execution summary in terminal."""
    status_colors = {
        "SUCCESS": "bold green",
        "NO_FACE_DETECTED": "bold yellow",
        "FACE_TOO_SMALL": "bold red",
        "NO_MATCH": "bold yellow",
        "LOW_CONFIDENCE_MATCH": "bold orange3",
        "SEARCH_PROVIDER_UNAVAILABLE": "bold red",
        "CHAIN_WRITE_ERROR": "bold red",
        "HUMAN_REJECTED": "bold magenta",
    }
    color = status_colors.get(result.status, "white")

    console.print()
    console.print(
        Panel(
            f"Pipeline Execution Status: [{color}][ {result.status} ][/{color}]\n"
            f"Total Duration: [cyan]{result.total_duration_ms} ms[/cyan]\n"
            f"{result.error_message or 'All biometric and cryptographic operations completed successfully.'}",
            title="Pipeline Execution Summary",
            border_style=color,
        )
    )

    # 1. Pipeline Steps Table
    step_table = Table(title="Pipeline Step Telemetry", show_header=True, header_style="bold cyan")
    step_table.add_column("Step", style="bold")
    step_table.add_column("Status", justify="center")
    step_table.add_column("Duration (ms)", justify="right")
    step_table.add_column("Key Details")

    for log in result.logs:
        st_color = "green" if log.status == "SUCCESS" else "red" if log.status == "FAILED" else "yellow"
        details_str = ", ".join(f"{k}={v}" for k, v in list(log.details.items())[:3])
        step_table.add_row(log.step_name, f"[{st_color}]{log.status}[/{st_color}]", str(log.duration_ms), details_str)

    console.print(step_table)
    console.print()

    # 2. Winning Match & Blockchain Details
    if result.status == "SUCCESS" and result.write_receipt is not None:
        rec_table = Table(title="Blockchain Record & Identity Commitment", show_header=True, header_style="bold green")
        rec_table.add_column("Field", style="dim", width=25)
        rec_table.add_column("Value")

        rec_table.add_row("Record ID", f"[bold green]#{result.write_receipt.record_id}[/bold green]")
        rec_table.add_row("Transaction Hash", f"[dim]{result.write_receipt.tx_hash}[/dim]")
        rec_table.add_row("Block Number", str(result.write_receipt.block_number))
        rec_table.add_row("Gas Used", str(result.write_receipt.gas_used))
        rec_table.add_row("Explorer Link", f"[blue]{result.write_receipt.explorer_url}[/blue]")
        rec_table.add_row("Content Hash (bytes32)", f"[bold cyan]{result.content_hash}[/bold cyan]")
        rec_table.add_row("Source URL", result.extracted_data.normalized_source_url if result.extracted_data else "N/A")
        rec_table.add_row("Platform", result.extracted_data.platform if result.extracted_data else "N/A")
        if result.match_decision and result.match_decision.winning_candidate:
            rec_table.add_row("Biometric Similarity", f"[bold]{result.match_decision.winning_candidate.similarity_score:.4f}[/bold]")

        console.print(rec_table)
        console.print()
        console.print(
            f"[dim]To verify this record independently at any time, run:[/dim]\n"
            f"  [bold]python verify.py --record-id {result.write_receipt.record_id} --from-cache[/bold]"
        )
        console.print()


def interactive_review_prompt(match_decision) -> bool:
    """Optional Human Review mode (--review flag)."""
    console.print()
    console.print(Panel("[bold yellow]HUMAN REVIEW MODE ACTIVE[/bold yellow]\nInspect candidates before committing to blockchain.", border_style="yellow"))

    table = Table(title="Candidate Evaluation Pool", show_header=True)
    table.add_column("Rank", justify="center")
    table.add_column("URL")
    table.add_column("Similarity Score", justify="right")

    for c in match_decision.all_scored_candidates[:5]:
        table.add_row(str(c.rank), c.fetched_candidate.page_url, f"{c.similarity_score:.4f}")

    console.print(table)
    ans = input("\nApprove commitment of Top-1 match to blockchain ledger? [y/N]: ").strip().lower()
    return ans in ("y", "yes")


def main():
    parser = argparse.ArgumentParser(
        description="Face ID + Blockchain Verification Pipeline (HH Goa 2026 Task #3)"
    )
    parser.add_argument("--image", type=str, required=True, help="Path to input face image file")
    parser.add_argument("--face-index", type=int, help="Optional index of face to select if multiple detected")
    parser.add_argument("--threshold", type=float, help="Override biometric cosine similarity threshold")
    parser.add_argument("--margin", type=float, help="Override minimum confidence margin (default: 0.05)")
    parser.add_argument("--review", action="store_true", help="Launch interactive human review mode before chain commit (off by default)")
    parser.add_argument("--dry-run", action="store_true", help="Execute pipeline without submitting to blockchain")

    args = parser.parse_args()

    if not os.path.exists(args.image):
        console.print(f"[bold red]Error: Input image not found at '{args.image}'[/bold red]")
        sys.exit(1)

    pipeline = VerificationPipeline(
        similarity_threshold=args.threshold,
        confidence_margin=args.margin,
    )

    review_cb = interactive_review_prompt if (args.review or os.getenv("MATCH_REVIEW_MODE") == "interactive") else None

    console.print(f"[bold cyan]Running Face ID + Blockchain Verification Pipeline on: {args.image}[/bold cyan]")
    result = pipeline.run(
        image_input=args.image,
        force_face_index=args.face_index,
        review_callback=review_cb,
        skip_blockchain=args.dry_run,
    )

    render_pipeline_summary(result)

    if result.status == "SUCCESS":
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
