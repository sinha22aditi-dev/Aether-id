"""
Multi-Provider Search Cascade Engine.
Orchestrates Google Gemini API (primary) -> SerpApi (fallback) -> TinEye (tertiary),
across Representation A (full image) and Representation B (face crop),
deduplicating discovered candidate URLs and preserving deep diagnostic telemetry.
"""

from dataclasses import dataclass, field
import datetime
import logging
import time
from typing import Dict, List, Optional, Tuple
import urllib.parse

from .base import SearchProvider, SearchResult
from .gemini_search import GeminiSearchProvider
from .representations import SearchRepresentations
from .serpapi_search import SerpApiSearchProvider
from .tineye_search import TinEyeSearchProvider

logger = logging.getLogger("pipeline.search.cascade")


def normalize_url(url: str) -> str:
    """Normalizes URL for deduplication (removes tracking params, lowercase host, strip trailing slash)."""
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url.strip())
        # Filter out common tracking query params
        query_params = urllib.parse.parse_qsl(parsed.query)
        filtered_params = [
            (k, v) for (k, v) in query_params
            if not (k.startswith("utm_") or k in ("ref", "fbclid", "gclid", "src", "source", "igsh"))
        ]
        new_query = urllib.parse.urlencode(filtered_params)
        clean_path = parsed.path.rstrip("/")
        if not clean_path:
            clean_path = "/"
        normalized = urllib.parse.urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            clean_path,
            "",
            new_query,
            "",
        ))
        return normalized
    except Exception:
        return url.strip().rstrip("/")


@dataclass
class CascadeTelemetry:
    """Execution telemetry for search cascade."""
    timestamp: str
    provider: str
    representation: str
    response_time_ms: int
    raw_count: int
    success: bool
    error: Optional[str] = None


@dataclass
class CascadeResult:
    """Final output of the search cascade."""
    candidates: List[SearchResult] = field(default_factory=list)
    winning_provider: str = "none"
    winning_representation: str = "none"
    telemetry: List[CascadeTelemetry] = field(default_factory=list)
    status: str = "NO_MATCH"  # SUCCESS | NO_MATCH | SEARCH_PROVIDER_ERROR | SEARCH_PROVIDER_UNAVAILABLE
    diagnostics_summary: str = ""


class SearchCascade:
    """
    Executes multi-provider cascade across representations.
    Guarantees no single point of failure and preserves comprehensive diagnostics.
    """

    def __init__(
        self,
        primary_provider: Optional[SearchProvider] = None,
        fallback_provider: Optional[SearchProvider] = None,
        tertiary_provider: Optional[SearchProvider] = None,
    ):
        self.primary = primary_provider or GeminiSearchProvider()
        self.fallback = fallback_provider or SerpApiSearchProvider()
        self.tertiary = tertiary_provider or TinEyeSearchProvider()

    def _query_provider(
        self,
        provider: SearchProvider,
        representations: SearchRepresentations,
        include_face_crop: bool = True,
    ) -> Tuple[List[SearchResult], List[CascadeTelemetry]]:
        """Queries a provider with Representation A (full image) and Representation B (face crop)."""
        provider_candidates: List[SearchResult] = []
        logs: List[CascadeTelemetry] = []

        # ----------------------------------------------------------------------
        # 1. Representation A (Full Scene Context)
        # ----------------------------------------------------------------------
        if representations.full_image_bytes is not None:
            t0 = time.time()
            try:
                res_a = provider.search(representations.full_image_bytes, representation_type="full_image")
                elapsed = int((time.time() - t0) * 1000)
                logs.append(
                    CascadeTelemetry(
                        timestamp=datetime.datetime.utcnow().isoformat() + "Z",
                        provider=provider.name,
                        representation="full_image",
                        response_time_ms=elapsed,
                        raw_count=len(res_a),
                        success=True,
                    )
                )
                provider_candidates.extend(res_a)
                logger.info(
                    f"[{provider.name} // Representation A] Completed in {elapsed}ms -> Found {len(res_a)} candidates."
                )
            except Exception as e:
                elapsed = int((time.time() - t0) * 1000)
                err_msg = f"{type(e).__name__}: {e}"
                logs.append(
                    CascadeTelemetry(
                        timestamp=datetime.datetime.utcnow().isoformat() + "Z",
                        provider=provider.name,
                        representation="full_image",
                        response_time_ms=elapsed,
                        raw_count=0,
                        success=False,
                        error=err_msg,
                    )
                )
                logger.warning(
                    f"[{provider.name} // Representation A] Error after {elapsed}ms: {err_msg}"
                )

        # ----------------------------------------------------------------------
        # 2. Representation B (Padded Face Crop)
        # ----------------------------------------------------------------------
        if include_face_crop and representations.face_crop_bytes is not None:
            t0 = time.time()
            try:
                res_b = provider.search(representations.face_crop_bytes, representation_type="face_crop")
                elapsed = int((time.time() - t0) * 1000)
                logs.append(
                    CascadeTelemetry(
                        timestamp=datetime.datetime.utcnow().isoformat() + "Z",
                        provider=provider.name,
                        representation="face_crop",
                        response_time_ms=elapsed,
                        raw_count=len(res_b),
                        success=True,
                    )
                )
                provider_candidates.extend(res_b)
                logger.info(
                    f"[{provider.name} // Representation B] Completed in {elapsed}ms -> Found {len(res_b)} candidates."
                )
            except Exception as e:
                elapsed = int((time.time() - t0) * 1000)
                err_msg = f"{type(e).__name__}: {e}"
                logs.append(
                    CascadeTelemetry(
                        timestamp=datetime.datetime.utcnow().isoformat() + "Z",
                        provider=provider.name,
                        representation="face_crop",
                        response_time_ms=elapsed,
                        raw_count=0,
                        success=False,
                        error=err_msg,
                    )
                )
                logger.warning(
                    f"[{provider.name} // Representation B] Error after {elapsed}ms: {err_msg}"
                )

        return provider_candidates, logs

    def run(self, representations: SearchRepresentations) -> CascadeResult:
        """
        Executes cascade logic:
        Primary (Gemini A + B) -> Fallback (SerpApi A + B) -> Tertiary (TinEye A)
        Does not terminate early on provider failure; continues down the chain.
        """
        all_telemetry: List[CascadeTelemetry] = []
        candidates: List[SearchResult] = []
        winning_provider = "none"
        winning_rep = "none"

        # Guard: Check representation availability
        if not representations.full_image_bytes and not representations.face_crop_bytes:
            logger.warning("Search Cascade: No search representations provided.")
            return CascadeResult(
                status="NO_MATCH",
                diagnostics_summary="No search representations were generated from the input image.",
            )

        logger.info("=================================================================")
        logger.info("Starting Multi-Provider Reverse Image Search Cascade")
        logger.info("=================================================================")

        # ----------------------------------------------------------------------
        # Step 1: Query Primary Provider (Google Gemini API with Search Grounding)
        # ----------------------------------------------------------------------
        if self.primary.is_configured():
            logger.info(f"==> Step 1: Querying PRIMARY search provider '{self.primary.name}'...")
            cands, logs = self._query_provider(self.primary, representations, include_face_crop=True)
            all_telemetry.extend(logs)
            if len(cands) > 0:
                candidates = cands
                winning_provider = self.primary.name
                winning_rep = cands[0].representation
                logger.info(f"Primary provider '{self.primary.name}' succeeded with {len(cands)} candidate(s).")
            else:
                logger.info(
                    f"Primary provider '{self.primary.name}' returned 0 candidates or encountered an error. "
                    "Continuing cascade to fallback provider..."
                )
        else:
            logger.info(f"Primary provider '{self.primary.name}' is not configured. Proceeding to fallback...")

        # ----------------------------------------------------------------------
        # Step 2: Fallback to SerpApi (Google Lens) if Primary returned 0 / failed
        # ----------------------------------------------------------------------
        if len(candidates) == 0:
            if self.fallback.is_configured():
                logger.info(f"==> Step 2: Invoking FALLBACK search provider '{self.fallback.name}'...")
                cands, logs = self._query_provider(self.fallback, representations, include_face_crop=True)
                all_telemetry.extend(logs)
                if len(cands) > 0:
                    candidates = cands
                    winning_provider = self.fallback.name
                    winning_rep = cands[0].representation
                    logger.info(f"Fallback provider '{self.fallback.name}' succeeded with {len(cands)} candidate(s).")
                else:
                    logger.info(
                        f"Fallback provider '{self.fallback.name}' returned 0 candidates or encountered an error. "
                        "Continuing cascade..."
                    )
            else:
                logger.info(f"Fallback provider '{self.fallback.name}' is not configured.")

        # ----------------------------------------------------------------------
        # Step 3: Tertiary Fallback to TinEye if still 0 candidates
        # ----------------------------------------------------------------------
        if len(candidates) == 0:
            if self.tertiary.is_configured():
                logger.info(f"==> Step 3: Invoking TERTIARY search provider '{self.tertiary.name}'...")
                cands, logs = self._query_provider(self.tertiary, representations, include_face_crop=False)
                all_telemetry.extend(logs)
                if len(cands) > 0:
                    candidates = cands
                    winning_provider = self.tertiary.name
                    winning_rep = "full_image"
                    logger.info(f"Tertiary provider '{self.tertiary.name}' succeeded with {len(cands)} candidate(s).")
            else:
                logger.info(f"Tertiary provider '{self.tertiary.name}' is not configured.")

        # ----------------------------------------------------------------------
        # Deduplication of Discovered URLs
        # ----------------------------------------------------------------------
        deduped: List[SearchResult] = []
        seen_urls = set()

        for c in candidates:
            norm = normalize_url(c.url)
            if norm and norm not in seen_urls:
                seen_urls.add(norm)
                deduped.append(c)

        # ----------------------------------------------------------------------
        # Diagnostic Classification of Terminal Status
        # ----------------------------------------------------------------------
        # Check provider errors
        configured_providers = [p for p in (self.primary, self.fallback, self.tertiary) if p.is_configured()]
        errors = [t for t in all_telemetry if not t.success and t.error]

        if len(deduped) > 0:
            status = "SUCCESS"
            summary = f"Discovered {len(deduped)} unique candidate(s) via '{winning_provider}'."
            logger.info(f"Search Cascade Succeeded: {summary}")

        elif len(configured_providers) == 0:
            status = "SEARCH_PROVIDER_UNAVAILABLE"
            summary = "No search providers are configured with valid API credentials in .env."
            logger.warning(f"Search Cascade: {summary}")

        elif len(errors) == len(all_telemetry) and len(all_telemetry) > 0:
            # All attempted provider calls threw exceptions
            status = "SEARCH_PROVIDER_ERROR"
            err_details = "; ".join([f"{e.provider}: {e.error}" for e in errors])
            summary = f"All configured search providers encountered errors: {err_details}"
            logger.error(f"Search Cascade: {summary}")

        else:
            # At least one provider executed cleanly with HTTP 200, but 0 matches exist online
            status = "NO_MATCH"
            summary = "Search providers executed successfully, but no matching images/pages exist on the public web."
            logger.info(f"Search Cascade: {summary}")

        return CascadeResult(
            candidates=deduped,
            winning_provider=winning_provider,
            winning_representation=winning_rep,
            telemetry=all_telemetry,
            status=status,
            diagnostics_summary=summary,
        )
