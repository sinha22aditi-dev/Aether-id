"""
Post Data Extractor Module.
Extracts normalized post metadata, platform tags, perceptual hashes,
and prepare immutable verifiable attributes.
"""

from dataclasses import dataclass
import io
import logging
import re
from typing import Optional

import imagehash
from PIL import Image

from .matcher import ScoredCandidate

logger = logging.getLogger("pipeline.match.extractor")


@dataclass
class ExtractedPostData:
    """Structured extraction from the winning candidate post."""
    normalized_source_url: str
    platform: str
    source_type: str = "WEB_PAGE"      # SOCIAL_MEDIA | WEB_PAGE | IMAGE_SOURCE
    public_post_id: Optional[str] = None
    post_text_normalized: Optional[str] = None
    image_sha256: str = ""
    image_phash: str = ""
    schema_version: str = "2.0"


class PostDataExtractor:
    """
    Standardizes and cleans metadata extracted from candidate posts.
    """

    @staticmethod
    def _clean_text(raw_text: Optional[str]) -> Optional[str]:
        if not raw_text:
            return None
        # Normalize whitespace and strip invisible control characters
        text = re.sub(r"\s+", " ", raw_text).strip()
        # Limit maximum text length to preserve compact storage
        if len(text) > 500:
            text = text[:500].rsplit(" ", 1)[0] + "..."
        return text or None

    @classmethod
    def extract(cls, candidate: ScoredCandidate) -> ExtractedPostData:
        """
        Extracts immutable verifiable fields and perceptual hash from winning candidate.
        """
        fc = candidate.fetched_candidate
        c_img = candidate.candidate_image

        # Compute Perceptual Hash (pHash) for diagnostic tracking
        phash_str = ""
        try:
            pil_img = Image.open(io.BytesIO(c_img.image_bytes))
            phash_str = str(imagehash.phash(pil_img))
        except Exception as e:
            logger.warning(f"Could not compute pHash: {e}")

        clean_text = cls._clean_text(fc.page_text or fc.page_title)
        st = getattr(fc, "source_type", getattr(fc.search_result, "source_type", "WEB_PAGE"))

        return ExtractedPostData(
            normalized_source_url=fc.page_url.strip(),
            platform=fc.platform or "web",
            source_type=st,
            public_post_id=fc.public_post_id,
            post_text_normalized=clean_text,
            image_sha256=c_img.sha256,
            image_phash=phash_str,
            schema_version="2.0",
        )
