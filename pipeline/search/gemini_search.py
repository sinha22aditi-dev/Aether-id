"""
Primary Search Provider: Google AI Studio Gemini API with Google Search Grounding.
Discovers matching webpage URLs, source articles, social posts, and visual contexts.
Note: Gemini is used strictly for candidate and URL discovery. Biometric face validation
is independently executed via InceptionResnetV1 512-d embeddings and cosine similarity.
"""

import logging
import os
import re
from typing import List, Optional
import urllib.parse

from .base import SearchProvider, SearchResult

logger = logging.getLogger("pipeline.search.gemini")


class GeminiSearchProvider(SearchProvider):
    """
    Primary reverse visual discovery and web search provider using Google AI Studio Gemini API.
    Authenticates via GEMINI_API_KEY and utilizes Google Search grounding tools.
    """

    name: str = "gemini"

    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-2.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = os.getenv("GEMINI_MODEL", model_name)
        self._client = None

    def is_configured(self) -> bool:
        """Checks if GEMINI_API_KEY is defined and non-empty."""
        return bool(self.api_key and len(self.api_key.strip()) > 5)

    def _get_client(self):
        if self._client is None:
            if not self.is_configured():
                raise RuntimeError(
                    "[Gemini Search] GEMINI_API_KEY is not configured in .env. "
                    "Please set GEMINI_API_KEY to your Google AI Studio API key."
                )
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.error(f"[Gemini Auth Error] Failed to initialize Gemini Client: {e}")
                raise
        return self._client

    def _extract_urls_from_text(self, text: str) -> List[str]:
        """Extracts valid HTTP/HTTPS URLs from raw text output."""
        if not text:
            return []
        url_pattern = r'https?://[^\s<>"\')\]]+'
        matches = re.findall(url_pattern, text)
        clean_urls = []
        for url in matches:
            url = url.rstrip(".,;:)")
            if len(url) > 10 and "." in url:
                clean_urls.append(url)
        return clean_urls

    def search(
        self,
        image_bytes: bytes,
        representation_type: str = "full_image",
    ) -> List[SearchResult]:
        """
        Submits image to Gemini with Google Search Grounding to discover candidate web URLs.
        """
        if not self.is_configured():
            logger.info(
                "[Gemini Search Diagnostics]:\n"
                "  - API Key Detected: False (missing or invalid GEMINI_API_KEY)\n"
                "  - Request Sent: False\n"
                "  - Skipping Gemini search provider."
            )
            return []

        key_masked = f"{self.api_key[:6]}...{self.api_key[-4:]}" if len(self.api_key) > 10 else "***"
        logger.info(
            f"[Gemini Search] === Starting Visual Discovery for {representation_type.upper()} "
            f"({len(image_bytes)} bytes, model: {self.model_name}, key: {key_masked}) ==="
        )

        try:
            from google.genai import types
            client = self._get_client()

            # Prepare image Part
            image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")

            prompt = (
                "You are an automated visual web search agent. Analyze this image (or face crop) "
                "and find all public web pages, articles, social media posts, archives, or galleries "
                "where this exact person, photo, or subject appears online.\n\n"
                "Use Google Search to find real, exact webpage URLs where this subject or image is hosted.\n"
                "List each discovered webpage URL clearly with its title and context."
            )

            # Configure Google Search Grounding tool
            config = types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.2,
            )

            logger.info(
                f"[Gemini Search Step] Sending multimodal request to {self.model_name} with Google Search grounding..."
            )
            response = client.models.generate_content(
                model=self.model_name,
                contents=[prompt, image_part],
                config=config,
            )

            results: List[SearchResult] = []
            seen_urls = set()

            grounding_chunks_count = 0
            web_queries_count = 0

            # 1. Parse Google Search Grounding metadata
            if response.candidates and len(response.candidates) > 0:
                cand = response.candidates[0]
                grounding_meta = getattr(cand, "grounding_metadata", None)

                if grounding_meta:
                    # Grounding chunks contain exact web URIs verified by Google Search
                    chunks = getattr(grounding_meta, "grounding_chunks", []) or []
                    grounding_chunks_count = len(chunks)

                    for chunk in chunks:
                        web = getattr(chunk, "web", None)
                        if web:
                            uri = getattr(web, "uri", None)
                            title = getattr(web, "title", None)
                            if uri and uri not in seen_urls:
                                seen_urls.add(uri)
                                results.append(
                                    SearchResult(
                                        url=uri,
                                        title=title,
                                        snippet=f"Discovered via Gemini Google Search Grounding: {title or uri}",
                                        provider=self.name,
                                        representation=representation_type,
                                    )
                                )

                    web_queries = getattr(grounding_meta, "web_search_queries", []) or []
                    web_queries_count = len(web_queries)
                    if web_queries:
                        logger.info(f"  - Web Search Queries executed by Gemini: {web_queries}")

            # 2. Parse any direct URLs generated in response text
            resp_text = response.text or ""
            text_urls = self._extract_urls_from_text(resp_text)
            for url in text_urls:
                if url not in seen_urls:
                    seen_urls.add(url)
                    results.append(
                        SearchResult(
                            url=url,
                            title=None,
                            snippet="Discovered via Gemini response analysis",
                            provider=self.name,
                            representation=representation_type,
                        )
                    )

            logger.info(
                f"[Gemini Search Diagnostics - {representation_type}]:\n"
                f"  - API Key Detected: True ({key_masked})\n"
                f"  - Request Sent: True (model='{self.model_name}')\n"
                f"  - Grounding Chunks Returned: {grounding_chunks_count}\n"
                f"  - Search Queries Run: {web_queries_count}\n"
                f"  - Usable Candidate URLs Extracted: {len(results)}"
            )

            return results

        except Exception as e:
            err_str = str(e)
            logger.error(
                f"[Gemini Search Error - {representation_type}]: {type(e).__name__}: {err_str}"
            )
            # Re-raise so cascade catches, logs telemetry, and falls back to SerpApi
            raise
