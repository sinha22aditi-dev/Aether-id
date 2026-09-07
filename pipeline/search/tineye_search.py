"""
Optional Tertiary Fallback Provider: TinEye API.
Implements HMAC request signing and reverse image search.
"""

import hashlib
import hmac
import logging
import os
import time
from typing import List, Optional

import httpx

from .base import SearchProvider, SearchResult

logger = logging.getLogger("pipeline.search.tineye")


class TinEyeSearchProvider(SearchProvider):
    """
    Tertiary fallback reverse image search provider using TinEye API.
    Authenticates via TINEYE_API_KEY and TINEYE_API_SECRET.
    """

    name: str = "tineye"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("TINEYE_API_KEY")
        self.api_secret = api_secret or os.getenv("TINEYE_API_SECRET")

    def is_configured(self) -> bool:
        """Checks if TinEye keys are configured."""
        return bool(self.api_key and self.api_secret)

    def _generate_nonce(self) -> str:
        return str(int(time.time()))

    def _generate_hmac_signature(self, nonce: str, date: str) -> str:
        message = f"{self.api_secret}{nonce}{date}"
        return hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def search(
        self,
        image_bytes: bytes,
        representation_type: str = "full_image",
    ) -> List[SearchResult]:
        """
        Queries TinEye API (Representation A only per PRD).
        """
        if not self.is_configured():
            logger.info("[TinEye] Not configured (missing TINEYE_API_KEY / TINEYE_API_SECRET). Skipping.")
            return []

        try:
            logger.info(
                f"[TinEye] Submitting reverse search ({representation_type}, {len(image_bytes)} bytes)..."
            )
            url = "https://api.tineye.com/rest/search/"

            nonce = self._generate_nonce()
            date = str(int(time.time()))
            signature = self._generate_hmac_signature(nonce, date)

            params = {
                "api_key": self.api_key,
                "nonce": nonce,
                "date": date,
                "api_sig": signature,
            }

            files = {
                "image": ("query.jpg", image_bytes, "image/jpeg"),
            }

            with httpx.Client(timeout=25.0) as client:
                response = client.post(url, params=params, files=files)

            if response.status_code != 200:
                logger.warning(
                    f"[TinEye] Request returned HTTP {response.status_code}: {response.text[:200]}"
                )
                return []

            data = response.json()
            results: List[SearchResult] = []

            matches = data.get("results", {}).get("matches", [])
            for match in matches:
                backlinks = match.get("backlinks", [])
                for bl in backlinks:
                    page_url = bl.get("backlink")
                    img_url = bl.get("url")
                    if page_url and not any(r.url == page_url for r in results):
                        results.append(
                            SearchResult(
                                url=page_url,
                                image_url=img_url,
                                provider=self.name,
                                representation=representation_type,
                            )
                        )

            logger.info(f"[TinEye] Found {len(results)} candidate(s).")
            return results

        except Exception as e:
            logger.warning(f"[TinEye] Search error: {e}")
            return []
