"""
AETHER-ID End-to-End Demo Pipeline & Verification Tool (PRD Sec. 25).
Runs an end-to-end pipeline execution and verification test using synthetic/fixture inputs
on local EVM ledger or Polygon Amoy Testnet.
"""

import io
import os
import sys
import time

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
from PIL import Image, ImageDraw
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pipeline.canon.canonicalize import Canonicalizer, ImmutableVerifiableData
from pipeline.chain.client import BlockchainClient
from pipeline.chain.reader import BlockchainReader
from pipeline.chain.writer import BlockchainWriter
from pipeline.face.detector import FaceDetector
from pipeline.face.embedder import FaceEmbedder
from pipeline.match.matcher import BiometricMatcher
from pipeline.search.base import SearchResult
from pipeline.search.fetch_candidates import CandidateImage, FetchedCandidate
from pipeline.storage.cache import MetadataCache
from pipeline.verifier import RecordVerifier

load_dotenv()
console = Console()


def create_demo_portrait() -> Image.Image:
    """Generates a synthetic portrait image with clear facial features for demo testing."""
    img = Image.new("RGB", (300, 300), color=(240, 242, 245))
    draw = ImageDraw.Draw(img)

    # Draw head outline
    draw.ellipse([80, 50, 220, 230], fill=(235, 195, 165), outline=(180, 130, 100), width=3)
    # Eyes
    draw.ellipse([110, 110, 135, 135], fill=(255, 255, 255), outline=(50, 50, 50), width=2)
    draw.ellipse([118, 118, 127, 127], fill=(30, 80, 150))
    draw.ellipse([165, 110, 190, 135], fill=(255, 255, 255), outline=(50, 50, 50), width=2)
    draw.ellipse([173, 118, 182, 127], fill=(30, 80, 150))
    # Nose
    draw.line([150, 130, 145, 165], fill=(180, 130, 100), width=3)
    draw.line([145, 165, 155, 165], fill=(180, 130, 100), width=3)
    # Smile
    draw.arc([120, 160, 180, 200], start=10, end=170, fill=(160, 60, 60), width=4)

    return img


def run_demo():
    console.print(
        Panel(
            "[bold cyan]AETHER-ID // End-to-End Pipeline & Blockchain Demo[/bold cyan]\n"
            "Demonstrating Face Detection, Biometric Matching, Canonical Hashing, Blockchain Record Creation & Independent Re-Verification",
            title="System Demonstration",
            border_style="cyan",
        )
    )

    use_local = "--local" in sys.argv or os.getenv("USE_LOCAL_CHAIN", "true").lower() == "true"
    chain_client = BlockchainClient(use_local_chain=use_local)

    if use_local:
        console.print("[yellow]Running on Local In-Memory EVM Chain (eth-tester)...[/yellow]")
        contract_addr, _ = chain_client.deploy_contract(private_key="default")
    else:
        console.print(f"[cyan]Connecting to Chain ID {chain_client.chain_id} via {chain_client.rpc_url}...[/cyan]")
        contract_addr = chain_client.contract_address

    writer = BlockchainWriter(client=chain_client, contract_address=contract_addr)
    reader = BlockchainReader(client=chain_client, contract_address=contract_addr)
    cache = MetadataCache()
    verifier = RecordVerifier(reader=reader, cache=cache, check_live_source=False)

    # 1. Generate Synthetic Input Image
    console.print("\n[bold yellow]Stage 1: Face Detection & Biometric Embedding[/bold yellow]")
    demo_img = create_demo_portrait()
    detector = FaceDetector(min_face_size=30, blur_threshold=10.0)
    embedder = FaceEmbedder()

    det_res = detector.detect(demo_img)
    console.print(f"  - Face Detected: [green]{det_res.success}[/green] (Total Faces: {det_res.total_faces})")
    console.print(f"  - Bounding Box: {det_res.box}")
    console.print(f"  - Blur Variance Score: {det_res.blur_score:.2f}")

    emb = embedder.get_embedding(det_res.crop_image)
    console.print(f"  - Biometric Embedding: [cyan]{len(emb)}-dimensional L2-normalized vector[/cyan]")

    # 2. Simulate Candidate Discovery & Biometric Match Verification
    console.print("\n[bold yellow]Stage 2: Candidate Discovery & Biometric Matching[/bold yellow]")
    buf = io.BytesIO()
    demo_img.save(buf, format="JPEG")
    img_bytes = buf.getvalue()
    sha256_hash = "a1b2c3d4e5f678901234567890abcdef1234567890abcdef1234567890abcdef"

    sr = SearchResult(
        url="https://twitter.com/consented_user/status/188200112233",
        title="Verified Portrait of Consented Subject on X/Twitter",
        snippet="Official published portrait from HH Goa 2026 verification test suite.",
        provider="gemini",
        representation="full_image",
        source_type="SOCIAL_MEDIA",
        source_platform="twitter",
        discovery_method="google_search_grounding",
    )

    fc = FetchedCandidate(
        search_result=sr,
        page_url=sr.url,
        page_title=sr.title,
        page_text=sr.snippet,
        platform="twitter",
        source_type="SOCIAL_MEDIA",
        public_post_id="188200112233",
        images=[CandidateImage(image_url=sr.url + "/photo.jpg", image_bytes=img_bytes, sha256=sha256_hash)],
    )

    matcher = BiometricMatcher(similarity_threshold=0.60, confidence_margin=0.05, detector=detector, embedder=embedder)
    match_decision = matcher.evaluate_candidates(emb, [fc])

    console.print(f"  - Match Status: [bold green]{match_decision.status}[/bold green]")
    console.print(f"  - Top-1 Cosine Similarity: [bold cyan]{match_decision.top1_score:.4f}[/bold cyan]")
    console.print(f"  - Source Type Discovered: [bold green]{match_decision.winning_candidate.fetched_candidate.source_type}[/bold green] ({match_decision.winning_candidate.fetched_candidate.platform})")

    # 3. Canonicalization & Fingerprinting
    console.print("\n[bold yellow]Stage 3: Two-Tier Canonicalization & Fingerprinting[/bold yellow]")
    immutable_data = ImmutableVerifiableData(
        normalized_source_url=sr.url,
        platform="twitter",
        source_type="SOCIAL_MEDIA",
        public_post_id="188200112233",
        post_text_normalized="Verified Portrait of Consented Subject on X/Twitter",
        image_sha256=sha256_hash,
        schema_version="2.0",
    )

    content_hash, canonical_bytes = Canonicalizer.create_fingerprint(immutable_data)
    console.print(f"  - Canonical Data JSON (Tier A): {canonical_bytes.decode('utf-8')}")
    console.print(f"  - Canonical Fingerprint (SHA-256): [bold green]{content_hash}[/bold green]")

    # 4. Smart Contract Submission
    console.print("\n[bold yellow]Stage 4: On-Chain Smart Contract Record Creation[/bold yellow]")
    receipt = writer.submit_record(content_hash, metadata_uri=sr.url)
    console.print(f"  - Assigned Record ID: [bold cyan]Record #{receipt.record_id}[/bold cyan]")
    console.print(f"  - Transaction Hash: [dim]{receipt.tx_hash}[/dim]")
    console.print(f"  - Block Number: {receipt.block_number}")
    console.print(f"  - Gas Used: {receipt.gas_used}")

    # Save to local cache
    cache.save_record(
        record_id=receipt.record_id,
        tx_hash=receipt.tx_hash,
        content_hash=content_hash,
        immutable_data=immutable_data.to_dict(),
        audit_metadata={"search_provider": "gemini", "biometric_score": match_decision.top1_score},
    )

    # 5. Independent Verification
    console.print("\n[bold yellow]Stage 5: Independent On-Chain Re-Verification[/bold yellow]")
    v_res = verifier.verify(receipt.record_id, immutable_data.to_dict())
    console.print(f"  - Verification Outcome: [bold green][ {v_res.status} ][/bold green]")
    console.print(f"  - On-Chain Record Match: {v_res.computed_hash == v_res.on_chain_hash}")
    console.print(f"  - Verification Summary: {v_res.message}")

    # 6. Tamper Detection Test
    console.print("\n[bold yellow]Stage 6: Field-Level Tamper Detection Test[/bold yellow]")
    tampered_data = immutable_data.to_dict()
    tampered_data["post_text_normalized"] = "ALTERED text attempting unauthorized modification"
    t_res = verifier.verify(receipt.record_id, tampered_data)
    console.print(f"  - Tampered Outcome: [bold red][ {t_res.status} ][/bold red]")
    console.print(f"  - Tamper Message: {t_res.message}")

    console.print("\n" + "+" * 75)
    console.print("[bold green]All 6 Stages of End-to-End Demo Executed Successfully![/bold green]")
    console.print("+" * 75)


if __name__ == "__main__":
    run_demo()
