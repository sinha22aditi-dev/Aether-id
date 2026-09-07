"""
FastAPI Server Backend for Face ID + Blockchain Verification Web Application.
"""

import base64
import io
import json
import logging
import os
import sys
from typing import Any, Dict, Optional

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pipeline.chain.client import BlockchainClient
from pipeline.chain.reader import BlockchainReader
from pipeline.pipeline import VerificationPipeline
from pipeline.storage.cache import MetadataCache
from pipeline.verifier import RecordVerifier

load_dotenv()
logger = logging.getLogger("server")

app = FastAPI(title="Face ID + Blockchain Verification System", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

# Initialize core pipeline services
pipeline = VerificationPipeline()
cache = MetadataCache()
chain_client = pipeline.chain_client
chain_reader = BlockchainReader(client=chain_client)
verifier = RecordVerifier(reader=chain_reader, cache=cache)

# Startup diagnostic logging
logger.info("=" * 65)
logger.info("AETHER-ID Verification Server Initializing...")
chain_diag = chain_client.get_diagnostics()
logger.info(f"Blockchain Status: [{chain_diag['status']}] - {chain_diag['summary']}")
if chain_diag["errors"]:
    for err in chain_diag["errors"]:
        logger.error(f"  [Blockchain Config Error] {err}")
if chain_diag["warnings"]:
    for warn in chain_diag["warnings"]:
        logger.warning(f"  [Blockchain Warning] {warn}")
logger.info("=" * 65)


class VerifyRequest(BaseModel):
    record_id: int
    data: Optional[Dict[str, Any]] = None
    from_cache: bool = False
    check_live_source: bool = True


@app.get("/")
def serve_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Face ID Blockchain Verification API is running. UI files under /static."}


@app.get("/api/status")
def get_system_status():
    """Returns runtime status of search providers and blockchain connectivity with diagnostics."""
    chain_diag = chain_client.get_diagnostics()
    return {
        "status": "online",
        "blockchain": {
            "connected": chain_diag["rpc_connected"],
            "status": chain_diag["status"],
            "summary": chain_diag["summary"],
            "rpc_url": chain_diag["active_rpc_url"],
            "configured_rpc_url": chain_diag["configured_rpc_url"],
            "chain_id": chain_diag["actual_chain_id"] or chain_diag["expected_chain_id"],
            "block_number": chain_diag["block_number"],
            "gas_price_gwei": chain_diag["gas_price_gwei"],
            "contract_address": chain_diag["contract"]["address"],
            "contract_deployed": chain_diag["contract"]["deployed"],
            "wallet_address": chain_diag["wallet"]["address"],
            "wallet_balance_pol": chain_diag["wallet"]["balance_pol"],
            "use_local_chain": chain_diag["use_local_chain"],
            "errors": chain_diag["errors"],
            "warnings": chain_diag["warnings"],
        },
        "search_providers": {
            "gemini": pipeline.cascade.primary.is_configured(),
            "serpapi": pipeline.cascade.fallback.is_configured(),
            "tineye": pipeline.cascade.tertiary.is_configured(),
        },
        "models": {
            "embedder": pipeline.embedder.model_version,
            "similarity_threshold": pipeline.matcher.similarity_threshold,
            "confidence_margin": pipeline.matcher.confidence_margin,
            "face_selection_mode": pipeline.detector.selection_mode,
        },
    }


@app.get("/api/blockchain/diagnostics")
def get_blockchain_diagnostics():
    """Returns deep diagnostic telemetry for blockchain connection, wallet, and contract."""
    return chain_client.get_diagnostics()


@app.post("/api/scan")
async def run_scan(
    file: UploadFile = File(...),
    threshold: Optional[float] = Form(None),
    face_index: Optional[int] = Form(None),
    dry_run: bool = Form(False),
):
    """
    Executes end-to-end pipeline:
    Face Detection -> Embedding -> Search Cascade -> Biometric Matching -> Canonicalization -> Blockchain Write
    """
    try:
        contents = await file.read()
        if len(contents) == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        # Override threshold if provided
        if threshold is not None:
            pipeline.matcher.similarity_threshold = float(threshold)

        result = pipeline.run(
            image_input=contents,
            force_face_index=face_index,
            skip_blockchain=dry_run,
        )

        # Prepare base64 crop image if available
        crop_b64 = None
        if result.detection and result.detection.crop_image:
            buf = io.BytesIO()
            result.detection.crop_image.save(buf, format="JPEG")
            crop_b64 = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")

        # Prepare candidate images & scores
        candidate_list = []
        if result.match_decision and result.match_decision.all_scored_candidates:
            for sc in result.match_decision.all_scored_candidates:
                cand_img_b64 = None
                if sc.candidate_image and sc.candidate_image.image_bytes:
                    cand_img_b64 = "data:image/jpeg;base64," + base64.b64encode(sc.candidate_image.image_bytes).decode("utf-8")

                candidate_list.append({
                    "rank": sc.rank,
                    "url": sc.fetched_candidate.page_url,
                    "title": sc.fetched_candidate.page_title,
                    "platform": sc.fetched_candidate.platform,
                    "similarity_score": round(float(sc.similarity_score), 4),
                    "image_sha256": sc.candidate_image.sha256,
                    "image_b64": cand_img_b64,
                })

        response_data = {
            "status": result.status,
            "total_duration_ms": result.total_duration_ms,
            "error_message": result.error_message,
            "detection": {
                "total_faces": result.detection.total_faces if result.detection else 0,
                "selected_index": result.detection.selected_index if result.detection else -1,
                "box": result.detection.box if result.detection else None,
                "blur_score": round(result.detection.blur_score, 2) if result.detection else 0.0,
                "is_blurry": result.detection.is_blurry if result.detection else False,
                "crop_image_b64": crop_b64,
            } if result.detection else None,
            "search": {
                "winning_provider": result.cascade.winning_provider if result.cascade else "none",
                "winning_representation": result.cascade.winning_representation if result.cascade else "none",
                "candidate_count": len(result.cascade.candidates) if result.cascade else 0,
                "status": result.cascade.status if result.cascade else "none",
                "diagnostics_summary": result.cascade.diagnostics_summary if result.cascade else "",
                "telemetry": [
                    {
                        "provider": t.provider,
                        "representation": t.representation,
                        "raw_count": t.raw_count,
                        "response_time_ms": t.response_time_ms,
                        "success": t.success,
                        "error": t.error,
                    }
                    for t in (result.cascade.telemetry if result.cascade else [])
                ],
            } if result.cascade else None,
            "candidates": candidate_list,
            "match": {
                "top1_score": round(result.match_decision.top1_score, 4) if result.match_decision else 0.0,
                "top2_score": round(result.match_decision.top2_score, 4) if result.match_decision else 0.0,
                "margin": round(result.match_decision.score_margin, 4) if result.match_decision else 0.0,
                "threshold_applied": result.match_decision.threshold_applied if result.match_decision else 0.60,
                "margin_applied": result.match_decision.margin_applied if result.match_decision else 0.05,
            } if result.match_decision else None,
            "immutable_data": result.immutable_data.to_dict() if result.immutable_data else None,
            "audit_metadata": result.audit_metadata.to_dict() if result.audit_metadata else None,
            "content_hash": result.content_hash,
            "blockchain": {
                "record_id": result.write_receipt.record_id,
                "tx_hash": result.write_receipt.tx_hash,
                "block_number": result.write_receipt.block_number,
                "gas_used": result.write_receipt.gas_used,
                "explorer_url": result.write_receipt.explorer_url,
            } if result.write_receipt else None,
            "logs": [
                {
                    "step": l.step_name,
                    "status": l.status,
                    "duration_ms": l.duration_ms,
                    "details": l.details,
                }
                for l in result.logs
            ],
        }

        return response_data

    except Exception as e:
        logger.error(f"Scan API error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/verify")
def run_verify(req: VerifyRequest):
    """
    Independent Re-Verification Endpoint:
    Takes (recordId, data) -> verifies against on-chain record -> returns 1 of 6 status outcomes.
    """
    try:
        data = req.data
        if req.from_cache:
            cached = cache.get_record(req.record_id)
            if not cached:
                data = {}
            else:
                data = cached.immutable_data

        if not data:
            data = {}

        verifier.check_live_source = req.check_live_source
        res = verifier.verify(req.record_id, data)

        return {
            "status": res.status,
            "record_id": res.record_id,
            "computed_hash": res.computed_hash,
            "on_chain_hash": res.on_chain_hash,
            "is_hash_match": res.is_hash_match,
            "source_url_reachable": res.source_url_reachable,
            "message": res.message,
            "timestamp": res.timestamp,
            "on_chain_record": {
                "record_id": res.on_chain_record.record_id,
                "submitter": res.on_chain_record.submitter,
                "timestamp": res.on_chain_record.timestamp,
                "metadata_uri": res.on_chain_record.metadata_uri,
                "exists": res.on_chain_record.exists,
            } if res.on_chain_record else None,
            "field_diffs": [
                {
                    "field": d.field_name,
                    "original": d.original_value,
                    "tampered": d.tampered_value,
                }
                for d in res.field_diffs
            ],
        }

    except Exception as e:
        logger.error(f"Verify API error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/records")
def list_cached_records():
    """Lists cached blockchain records."""
    records = cache.list_records(limit=30)
    return [
        {
            "record_id": r.record_id,
            "tx_hash": r.tx_hash,
            "content_hash": r.content_hash,
            "immutable_data": r.immutable_data,
            "audit_metadata": r.audit_metadata,
            "created_at": r.created_at,
        }
        for r in records
    ]


app.mount("/static", StaticFiles(directory=static_dir), name="static")
