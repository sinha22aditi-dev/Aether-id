"""
Base Search Provider and Search Result Data Structures.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


import time
from typing import List, Optional, Tuple
import urllib.parse


def classify_source_url(url: str) -> Tuple[str, str]:
    """
    Classifies candidate URL into (source_type, source_platform).
    source_type: "SOCIAL_MEDIA" | "WEB_PAGE" | "IMAGE_SOURCE"
    source_platform: "twitter" | "instagram" | "linkedin" | "facebook" | "reddit" | "youtube" | "tiktok" | "pinterest" | "github" | "web"
    """
    if not url:
        return "WEB_PAGE", "web"

    clean_url = url.lower().strip()
    try:
        parsed = urllib.parse.urlparse(clean_url)
        netloc = parsed.netloc
        path_lower = parsed.path.lower()
    except Exception:
        return "WEB_PAGE", "web"

    # Image source check (direct image file extensions)
    img_exts = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff")
    if any(path_lower.endswith(ext) for ext in img_exts) or clean_url.startswith("data:image/"):
        return "IMAGE_SOURCE", netloc.replace("www.", "") or "direct_image"

    # Recognized Social Media platforms
    social_map = {
        "twitter.com": "twitter",
        "x.com": "twitter",
        "instagram.com": "instagram",
        "instagr.am": "instagram",
        "linkedin.com": "linkedin",
        "facebook.com": "facebook",
        "fb.com": "facebook",
        "fb.watch": "facebook",
        "reddit.com": "reddit",
        "redd.it": "reddit",
        "youtube.com": "youtube",
        "youtu.be": "youtube",
        "tiktok.com": "tiktok",
        "pinterest.com": "pinterest",
        "pin.it": "pinterest",
        "github.com": "github",
        "threads.net": "threads",
        "bsky.app": "bluesky",
        "medium.com": "medium",
        "tumblr.com": "tumblr",
        "flickr.com": "flickr",
    }

    for domain, plat in social_map.items():
        if domain in netloc:
            return "SOCIAL_MEDIA", plat

    return "WEB_PAGE", netloc.replace("www.", "") or "web"


@dataclass
class SearchResult:
    """Standardized search candidate discovered from reverse image search with complete provenance."""
    url: str                           # Candidate webpage URL
    title: Optional[str] = None        # Page title or heading
    snippet: Optional[str] = None      # Text snippet / context
    image_url: Optional[str] = None    # Direct image URL if provided by engine
    thumbnail_url: Optional[str] = None
    provider: str = "unknown"          # gemini | serpapi | tineye
    representation: str = "full_image" # full_image | face_crop
    source_type: str = "WEB_PAGE"      # SOCIAL_MEDIA | WEB_PAGE | IMAGE_SOURCE
    source_platform: str = "web"       # twitter | instagram | linkedin | facebook | reddit | youtube | tiktok | etc.
    discovery_method: str = "search"  # google_search_grounding | google_lens_api | tineye_api
    search_timestamp: float = 0.0      # Unix epoch timestamp of search execution

    def __post_init__(self):
        if not self.search_timestamp:
            self.search_timestamp = time.time()
        if self.url and (self.source_type == "WEB_PAGE" and self.source_platform == "web"):
            st, sp = classify_source_url(self.url)
            self.source_type = st
            self.source_platform = sp
        if self.discovery_method in ("search", "", None):
            if self.provider == "gemini":
                self.discovery_method = "google_search_grounding"
            elif self.provider == "serpapi":
                self.discovery_method = "google_lens_api"
            elif self.provider == "tineye":
                self.discovery_method = "tineye_api"
            else:
                self.discovery_method = "reverse_image_search"


class SearchProvider(ABC):
    """Abstract Base Class for Reverse Image Search Providers."""

    name: str = "base_provider"

    @abstractmethod
    def is_configured(self) -> bool:
        """Returns True if provider credentials/prerequisites are configured."""
        pass

    @abstractmethod
    def search(
        self,
        image_bytes: bytes,
        representation_type: str = "full_image",
    ) -> List[SearchResult]:
        """
        Executes a reverse image search with the given image bytes and representation.
        Returns a list of SearchResult candidates.
        """
        pass
