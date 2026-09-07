"""
Fallback Search Provider: SerpApi (Google Lens / Google Reverse Image).
Implements official two-step local image upload and search with deep diagnostic telemetry.
"""

import io
import logging
import os
from typing import List, Optional

import httpx
from PIL import Image

from .base import SearchProvider, SearchResult

logger = logging.getLogger("pipeline.search.serpapi")


class SerpApiSearchProvider(SearchProvider):
    """
    Fallback reverse image search provider using SerpApi Google Lens engine.
    Authenticates via SERPAPI_KEY.
    """

    name: str = "serpapi"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SERPAPI_KEY")

    def is_configured(self) -> bool:
        """Checks if SERPAPI_KEY is defined and non-empty."""
        return bool(self.api_key and len(self.api_key.strip()) > 5)

    def _prepare_image_bytes(self, image_bytes: bytes, max_bytes: int = 450000) -> bytes:
        """
        Ensures image bytes are within SerpApi's upload limit (500KB max).
        Compresses/resizes if necessary.
        """
        if len(image_bytes) <= max_bytes:
            return image_bytes

        try:
            pil_img = Image.open(io.BytesIO(image_bytes))
            if pil_img.mode in ("RGBA", "P"):
                pil_img = pil_img.convert("RGB")

            # Resize if dimensions are very large
            if max(pil_img.size) > 1024:
                pil_img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)

            quality = 85
            out_buf = io.BytesIO()
            pil_img.save(out_buf, format="JPEG", quality=quality, optimize=True)
            compressed = out_buf.getvalue()

            while len(compressed) > max_bytes and quality > 30:
                quality -= 15
                out_buf = io.BytesIO()
                pil_img.save(out_buf, format="JPEG", quality=quality, optimize=True)
                compressed = out_buf.getvalue()

            logger.info(
                f"[SerpApi] Compressed image from {len(image_bytes)} bytes to {len(compressed)} bytes (q={quality})."
            )
            return compressed
        except Exception as e:
            logger.warning(f"[SerpApi] Image compression fallback: {e}")
            return image_bytes

    def search(
        self,
        image_bytes: bytes,
        representation_type: str = "full_image",
    ) -> List[SearchResult]:
        """
        Submits image to SerpApi using the official two-step protocol:
        1. Upload image to https://serpapi.com/image -> get image_id
        2. Query Google Lens engine at https://serpapi.com/search?engine=google_lens&image_id=...
        """
        # Diagnostic 1: Key detection
        if not self.is_configured():
            logger.info(
                "[SerpApi Diagnostics]:\n"
                "  - API Key Detected: False (missing or invalid SERPAPI_KEY)\n"
                "  - Request Sent: False\n"
                "  - Skipping provider."
            )
            return []

        key_masked = f"{self.api_key[:6]}...{self.api_key[-4:]}" if len(self.api_key) > 10 else "***"
        logger.info(
            f"[SerpApi] === Starting Google Lens Search for {representation_type.upper()} "
            f"({len(image_bytes)} bytes, key: {key_masked}) ==="
        )

        prepared_bytes = self._prepare_image_bytes(image_bytes)

        try:
            # ------------------------------------------------------------------
            # Step 1: Upload image to SerpApi Image API
            # ------------------------------------------------------------------
            upload_url = "https://serpapi.com/image"
            logger.info(f"[SerpApi Step 1] Uploading image ({len(prepared_bytes)} bytes) to {upload_url}...")

            with httpx.Client(timeout=30.0) as client:
                upload_resp = client.post(
                    upload_url,
                    params={"api_key": self.api_key},
                    files={"image": ("query.jpg", prepared_bytes, "image/jpeg")},
                )

            if upload_resp.status_code != 200:
                err_text = upload_resp.text[:300]
                logger.error(f"[SerpApi Step 1 Error] Upload returned HTTP {upload_resp.status_code}: {err_text}")
                raise RuntimeError(f"SerpApi Image Upload HTTP {upload_resp.status_code}: {err_text}")

            upload_data = upload_resp.json()
            image_id = upload_data.get("image_id")
            if not image_id:
                err_msg = upload_data.get("error", "No image_id returned in upload response")
                logger.error(f"[SerpApi Step 1 Error] {err_msg}")
                raise RuntimeError(f"SerpApi upload failed: {err_msg}")

            logger.info(f"[SerpApi Step 1 Success] Image uploaded successfully. image_id='{image_id[:16]}...'")

            # ------------------------------------------------------------------
            # Step 2: Query Google Lens Engine with image_id
            # ------------------------------------------------------------------
            search_url = "https://serpapi.com/search"
            search_params = {
                "engine": "google_lens",
                "image_id": image_id,
                "api_key": self.api_key,
                "no_cache": "true",
            }
            logger.info(f"[SerpApi Step 2] Querying Google Lens with image_id at {search_url}...")

            with httpx.Client(timeout=45.0) as client:
                search_resp = client.get(search_url, params=search_params)

            if search_resp.status_code != 200:
                err_text = search_resp.text[:300]
                logger.error(f"[SerpApi Step 2 Error] Search returned HTTP {search_resp.status_code}: {err_text}")
                raise RuntimeError(f"SerpApi Google Lens HTTP {search_resp.status_code}: {err_text}")

            search_data = search_resp.json()
            if "error" in search_data:
                err_msg = search_data["error"]
                logger.error(f"[SerpApi Step 2 Error] API Error: {err_msg}")
                raise RuntimeError(f"SerpApi API Error: {err_msg}")

            # ------------------------------------------------------------------
            # Step 3: Parse Results and Extract Usable Candidates
            # ------------------------------------------------------------------
            visual_matches = search_data.get("visual_matches", [])
            exact_matches = search_data.get("exact_matches", [])
            knowledge_graph = search_data.get("knowledge_graph", [])
            reverse_image_search = search_data.get("reverse_image_search", {})
            search_metadata = search_data.get("search_metadata", {})

            total_raw = len(visual_matches) + len(exact_matches)
            logger.info(
                f"[SerpApi Diagnostics - {representation_type}]:\n"
                f"  - API Key Detected: True ({key_masked})\n"
                f"  - Request Sent: True (image_id='{image_id[:16]}...')\n"
                f"  - Response Status: 200 (search_id='{search_metadata.get('id', 'N/A')}')\n"
                f"  - Total Raw Results: {total_raw} (Visual matches: {len(visual_matches)}, Exact: {len(exact_matches)})\n"
                f"  - Processed Time: {search_metadata.get('total_time_taken', 'N/A')}s"
            )

            results: List[SearchResult] = []

            # 1. Parse visual matches
            for match in visual_matches:
                link = match.get("link")
                title = match.get("title")
                snippet = match.get("source") or match.get("snippet")
                thumbnail = match.get("thumbnail")
                original_img = match.get("original")

                if link and not any(r.url == link for r in results):
                    results.append(
                        SearchResult(
                            url=link,
                            title=title,
                            snippet=snippet,
                            image_url=original_img or thumbnail,
                            thumbnail_url=thumbnail,
                            provider=self.name,
                            representation=representation_type,
                        )
                    )

            # 2. Parse exact matches if present
            for match in exact_matches:
                link = match.get("link")
                if link and not any(r.url == link for r in results):
                    results.append(
                        SearchResult(
                            url=link,
                            title=match.get("title"),
                            snippet=match.get("source"),
                            image_url=match.get("thumbnail"),
                            thumbnail_url=match.get("thumbnail"),
                            provider=self.name,
                            representation=representation_type,
                        )
                    )

            logger.info(
                f"[SerpApi] Usable candidate URLs extracted: {len(results)} for representation '{representation_type}'."
            )
            return results

        except Exception as e:
            err_str = str(e)
            logger.error(
                f"[SerpApi Error - {representation_type}]: {type(e).__name__}: {err_str}"
            )
            # Re-raise so the cascade records the specific diagnostic failure reason
            raise
