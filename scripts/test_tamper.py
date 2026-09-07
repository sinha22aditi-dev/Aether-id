"""
Tamper Detection Demonstration Script (PRD Section 17 & 25).
Demonstrates the 3 critical live verification outcomes:
1. VERIFIED: Genuine record matches on-chain commitment.
2. TAMPER DETECTED: Modified field is caught with diagnostic diff.
3. RECORD_NOT_FOUND: Fabricated recordId correctly distinguished from tampering.
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pipeline.canon.canonicalize import Canonicalizer, ImmutableVerifiableData
from pipeline.chain.client import BlockchainClient
from pipeline.chain.reader import BlockchainReader
from pipeline.chain.writer import BlockchainWriter
from pipeline.storage.cache import MetadataCache
from pipeline.verifier import RecordVerifier

load_dotenv()
console = Console()


def run_tamper_demo():
    console.print(
        Panel(
            "[bold cyan]Face ID + Blockchain Verification — Live Tamper Demonstration[/bold cyan]\n"
            "Testing 3 Core Verification Scenarios on Real EVM Ledger",
            border_style="cyan",
        )
    )

    # Support --local flag or auto-fallback to local in-process EVM
    use_local = "--local" in sys.argv or os.getenv("USE_LOCAL_CHAIN", "true").lower() == "true"
    client = BlockchainClient(use_local_chain=use_local)

    if not use_local:
        if not client.is_connected() or not client.contract_address:
            console.print("[yellow]Remote RPC / Contract not reachable. Falling back to in-process local EVM ledger for demonstration...[/yellow]")
            client = BlockchainClient(use_local_chain=True)
            use_local = True

    if use_local:
        contract_addr, _ = client.deploy_contract(private_key="default")
    else:
        contract_addr = client.contract_address

    writer = BlockchainWriter(client=client, contract_address=contract_addr)
    reader = BlockchainReader(client=client, contract_address=contract_addr)
    cache = MetadataCache()
    verifier = RecordVerifier(reader=reader, cache=cache, check_live_source=False)

    # --------------------------------------------------------------------------
    # 1. Create and submit an authentic original record
    # --------------------------------------------------------------------------
    console.print("[bold yellow]Step 1: Committing authentic record to blockchain...[/bold yellow]")
    original_data = ImmutableVerifiableData(
        normalized_source_url="https://example.com/posts/consented_photo_123",
        platform="twitter",
        public_post_id="post_123456",
        post_text_normalized="Verified portrait of John Doe at HH Goa 2026",
        image_sha256="4f8a896d8e20f1a92e1f438a32b2e88a9f24e4c2789127890abcdef123456789",
        schema_version="1.0",
    )
    content_hash, canonical_bytes = Canonicalizer.create_fingerprint(original_data)

    receipt = writer.submit_record(content_hash, metadata_uri=original_data.normalized_source_url)
    rec_id = receipt.record_id

    cache.save_record(
        record_id=rec_id,
        tx_hash=receipt.tx_hash,
        content_hash=content_hash,
        immutable_data=original_data.to_dict(),
        audit_metadata={"simulated": True},
    )

    console.print(f"Record created on-chain: [bold green]Record #{rec_id}[/bold green]")
    console.print(f"Content Hash: [dim]{content_hash}[/dim]")
    console.print(f"Tx Hash: [dim]{receipt.tx_hash}[/dim]")
    console.print()

    # --------------------------------------------------------------------------
    # Case A: Verify with exact unmodified original data -> VERIFIED
    # --------------------------------------------------------------------------
    console.print(f"[bold cyan]==> Case A: Verifying Record #{rec_id} with exact original data...[/bold cyan]")
    res_a = verifier.verify(rec_id, original_data.to_dict())
    console.print(f"Outcome: [{'green' if res_a.status == 'VERIFIED' else 'red'}][ {res_a.status} ][/]")
    console.print(f"Message: {res_a.message}")
    assert res_a.status == "VERIFIED"
    console.print()

    # --------------------------------------------------------------------------
    # Case B: Verify with tampered/modified text -> TAMPER DETECTED
    # --------------------------------------------------------------------------
    console.print(f"[bold cyan]==> Case B: Verifying Record #{rec_id} with TAMPERED post text...[/bold cyan]")
    tampered_data = original_data.to_dict()
    tampered_data["post_text_normalized"] = "Altered caption by unauthorized actor"

    res_b = verifier.verify(rec_id, tampered_data)
    console.print(f"Outcome: [{'red' if res_b.status == 'TAMPER DETECTED' else 'green'}][ {res_b.status} ][/]")
    console.print(f"Message: {res_b.message}")
    if res_b.field_diffs:
        for d in res_b.field_diffs:
            console.print(f"  [yellow]Diff in field '{d.field_name}':[/yellow] '{d.original_value}' -> '[red]{d.tampered_value}[/red]'")
    assert res_b.status == "TAMPER DETECTED"
    console.print()

    # --------------------------------------------------------------------------
    # Case C: Verify with fabricated recordId 99999 -> RECORD_NOT_FOUND
    # --------------------------------------------------------------------------
    console.print("[bold cyan]==> Case C: Verifying fabricated Record #99999 (never submitted)...[/bold cyan]")
    res_c = verifier.verify(99999, original_data.to_dict())
    console.print(f"Outcome: [{'yellow' if res_c.status == 'RECORD_NOT_FOUND' else 'red'}][ {res_c.status} ][/]")
    console.print(f"Message: {res_c.message}")
    assert res_c.status == "RECORD_NOT_FOUND"
    console.print()

    console.print(Panel("[bold green]All 3 Demonstration Scenarios Succeeded Perfectly![/bold green]\nDirect proof that TAMPER DETECTED and RECORD_NOT_FOUND are cleanly distinguished.", border_style="green"))


if __name__ == "__main__":
    run_tamper_demo()
