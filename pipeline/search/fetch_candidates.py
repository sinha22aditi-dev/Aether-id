"""
Candidate Page Fetcher & Media Extractor.
Fetches candidate webpages live using HTTP, extracts metadata (title, text, platform),
and downloads candidate images for biometric face verification.
"""

from dataclasses import dataclass, field
import hashlib
import logging
from typing import Dict, List, Optional, Tuple
import urllib.parse

from bs4 import BeautifulSoup
import httpx

from .base import SearchResult

from .base import SearchResult, classify_source_url

logger = logging.getLogger("pipeline.search.fetch_candidates")


@dataclass
class CandidateImage:
    """Represents a downloaded candidate image."""
    image_url: str
    image_bytes: bytes
    sha256: str
    width: Optional[int] = None
    height: Optional[int] = None


@dataclass
class FetchedCandidate:
    """Fully parsed candidate webpage and associated images with complete provenance."""
    search_result: SearchResult
    page_url: str
    page_title: str
    page_text: str
    platform: str
    source_type: str = "WEB_PAGE"       # SOCIAL_MEDIA | WEB_PAGE | IMAGE_SOURCE
    public_post_id: Optional[str] = None
    images: List[CandidateImage] = field(default_factory=list)
    fetch_error: Optional[str] = None


class CandidateFetcher:
    """
    Fetches candidate pages, extracts open-graph metadata and downloads images
    for face verification with robust timeout and SSL handling.
    """

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    def __init__(self, timeout: float = 8.0, max_images_per_page: int = 5, max_candidates_to_fetch: int = 15):
        self.timeout = timeout
        self.max_images_per_page = max_images_per_page
        self.max_candidates_to_fetch = max_candidates_to_fetch
        self._headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _detect_platform(self, url: str) -> Tuple[str, str, Optional[str]]:
        """Detects (source_type, platform, public_post_id) from candidate URL."""
        source_type, platform = classify_source_url(url)
        post_id = None

        try:
            parsed = urllib.parse.urlparse(url.lower())
            path_parts = [p for p in parsed.path.split("/") if p]

            if platform == "twitter":
                if "status" in path_parts:
                    idx = path_parts.index("status")
                    if idx + 1 < len(path_parts):
                        post_id = path_parts[idx + 1]
                elif path_parts:
                    post_id = path_parts[0]
            elif platform == "instagram":
                if "p" in path_parts and len(path_parts) > 1:
                    post_id = path_parts[path_parts.index("p") + 1]
                elif "reel" in path_parts and len(path_parts) > 1:
                    post_id = path_parts[path_parts.index("reel") + 1]
            elif platform == "linkedin":
                if len(path_parts) > 1 and path_parts[0] in ("in", "posts", "pulse"):
                    post_id = path_parts[1]
            elif platform == "reddit":
                if "comments" in path_parts:
                    idx = path_parts.index("comments")
                    if idx + 1 < len(path_parts):
                        post_id = path_parts[idx + 1]
            elif platform == "youtube":
                if "watch" in path_parts and "v" in parsed.query:
                    qs = urllib.parse.parse_qs(parsed.query)
                    if "v" in qs:
                        post_id = qs["v"][0]
                elif "shorts" in path_parts and len(path_parts) > 1:
                    post_id = path_parts[path_parts.index("shorts") + 1]
            elif platform == "github":
                if path_parts:
                    post_id = path_parts[0]
        except Exception:
            pass

        return source_type, platform, post_id

    def _download_image(self, client: httpx.Client, img_url: str) -> Optional[CandidateImage]:
        """Downloads image bytes and computes SHA-256 hash."""
        try:
            resp = client.get(img_url, timeout=6.0)
            if resp.status_code == 200 and len(resp.content) > 1024:
                content_type = resp.headers.get("content-type", "").lower()
                if "image" in content_type or len(resp.content) > 2048:
                    sha256 = hashlib.sha256(resp.content).hexdigest()
                    return CandidateImage(
                        image_url=img_url,
                        image_bytes=resp.content,
                        sha256=sha256,
                    )
        except Exception as e:
            logger.debug(f"Failed to download candidate image {img_url}: {e}")
        return None

    def fetch_candidate(self, result: SearchResult) -> FetchedCandidate:
        """
        Fetches webpage, parses OpenGraph/HTML metadata, and retrieves images.
        """
        source_type, platform, post_id = self._detect_platform(result.url)
        page_title = result.title or ""
        page_text = result.snippet or ""
        downloaded_images: List[CandidateImage] = []

        # Use verify=False to prevent certificate chain failures from dropping candidates
        with httpx.Client(timeout=self.timeout, follow_redirects=True, headers=self._headers, verify=False) as client:
            # 1. Download directly provided image URL if available
            if result.image_url:
                direct_img = self._download_image(client, result.image_url)
                if direct_img:
                    downloaded_images.append(direct_img)

            # 2. Fetch webpage HTML
            try:
                resp = client.get(result.url)
                if resp.status_code == 200:
                    content_type = resp.headers.get("content-type", "").lower()

                    # If the URL itself is a direct image
                    if "image/" in content_type:
                        sha256 = hashlib.sha256(resp.content).hexdigest()
                        direct_img = CandidateImage(
                            image_url=result.url,
                            image_bytes=resp.content,
                            sha256=sha256,
                        )
                        if not any(img.sha256 == sha256 for img in downloaded_images):
                            downloaded_images.append(direct_img)
                        return FetchedCandidate(
                            search_result=result,
                            page_url=result.url,
                            page_title=page_title or "Direct Image Source",
                            page_text=page_text or result.url,
                            platform=platform,
                            source_type="IMAGE_SOURCE",
                            public_post_id=post_id,
                            images=downloaded_images,
                        )

                    soup = BeautifulSoup(resp.text, "html.parser")

                    # Extract Page Title
                    if not page_title:
                        og_title = soup.find("meta", property="og:title")
                        if og_title and og_title.get("content"):
                            page_title = og_title["content"].strip()
                        elif soup.title and soup.title.string:
                            page_title = soup.title.string.strip()

                    # Extract Page Text / Summary
                    og_desc = soup.find("meta", property="og:description")
                    if og_desc and og_desc.get("content"):
                        page_text = (page_text + " " + og_desc["content"].strip()).strip()

                    # Gather candidate image links
                    candidate_urls = []
                    # Check og:image & twitter:image
                    for prop in ("og:image", "twitter:image", "image"):
                        meta_img = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
                        if meta_img and meta_img.get("content"):
                            candidate_urls.append(urllib.parse.urljoin(result.url, meta_img["content"].strip()))

                    # Check <img> tags
                    for img in soup.find_all("img"):
                        src = img.get("src") or img.get("data-src")
                        if src:
                            full_url = urllib.parse.urljoin(result.url, src.strip())
                            if full_url not in candidate_urls and not full_url.endswith(".svg"):
                                candidate_urls.append(full_url)
                        if len(candidate_urls) >= self.max_images_per_page:
                            break

                    # Download candidate images
                    for img_url in candidate_urls:
                        if len(downloaded_images) >= self.max_images_per_page:
                            break
                        if any(img.image_url == img_url for img in downloaded_images):
                            continue

                        cand_img = self._download_image(client, img_url)
                        if cand_img and not any(i.sha256 == cand_img.sha256 for i in downloaded_images):
                            downloaded_images.append(cand_img)

            except Exception as e:
                logger.debug(f"Failed to fetch webpage HTML at {result.url}: {e}")

        return FetchedCandidate(
            search_result=result,
            page_url=result.url,
            page_title=page_title or result.url,
            page_text=page_text or page_title or result.url,
            platform=platform,
            source_type=source_type,
            public_post_id=post_id,
            images=downloaded_images,
        )

    def fetch_all(self, results: List[SearchResult]) -> List[FetchedCandidate]:
        """Fetches candidates (up to max_candidates_to_fetch) sequentially with logging."""
        fetched: List[FetchedCandidate] = []
        subset = results[:self.max_candidates_to_fetch]
        logger.info(f"[Candidate Fetcher] Fetching top {len(subset)} candidate page(s) (of {len(results)} total)...")
        for idx, r in enumerate(subset, 1):
            logger.info(f"  [{idx}/{len(subset)}] Fetching candidate: {r.url}")
            fc = self.fetch_candidate(r)
            fetched.append(fc)
        return fetched
