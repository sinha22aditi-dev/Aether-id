"""
Unit tests for Search Representations, Gemini Search Provider, Cascade, and Fallback logic.
"""

from typing import List
from PIL import Image
import pytest

from pipeline.search.base import SearchProvider, SearchResult
from pipeline.search.cascade import SearchCascade, CascadeResult, normalize_url
from pipeline.search.gemini_search import GeminiSearchProvider
from pipeline.search.representations import RepresentationBuilder


class MockSearchProvider(SearchProvider):
    def __init__(self, name: str, is_conf: bool, results: List[SearchResult], should_raise: bool = False):
        self.name = name
        self._is_conf = is_conf
        self._results = results
        self._should_raise = should_raise

    def is_configured(self) -> bool:
        return self._is_conf

    def search(self, image_bytes: bytes, representation_type: str = "full_image") -> List[SearchResult]:
        if self._should_raise:
            raise RuntimeError(f"Simulated API error in {self.name}")
        return self._results


def test_url_normalization():
    url1 = "https://WWW.Example.com/post/123/?utm_source=twitter&utm_medium=social#comment"
    norm1 = normalize_url(url1)
    assert norm1 == "https://www.example.com/post/123"

    url2 = "https://example.com/page?ref=home&id=42&fbclid=xyz"
    norm2 = normalize_url(url2)
    assert norm2 == "https://example.com/page?id=42"


def test_source_classification_social_vs_web_vs_image():
    from pipeline.search.base import classify_source_url, SearchResult

    # Social Media Platforms
    st, sp = classify_source_url("https://twitter.com/user/status/123456789")
    assert st == "SOCIAL_MEDIA"
    assert sp == "twitter"

    st, sp = classify_source_url("https://www.instagram.com/p/Cxyz123/")
    assert st == "SOCIAL_MEDIA"
    assert sp == "instagram"

    st, sp = classify_source_url("https://linkedin.com/in/john-doe")
    assert st == "SOCIAL_MEDIA"
    assert sp == "linkedin"

    st, sp = classify_source_url("https://reddit.com/r/technology/comments/abc")
    assert st == "SOCIAL_MEDIA"
    assert sp == "reddit"

    # Direct Image Source
    st, sp = classify_source_url("https://cdn.photos.org/images/portrait_hd.jpg")
    assert st == "IMAGE_SOURCE"

    # General Web Page
    st, sp = classify_source_url("https://techblog.example.com/articles/2026/face-id")
    assert st == "WEB_PAGE"
    assert sp == "techblog.example.com"

    # Auto-classification in SearchResult __post_init__
    sr = SearchResult(url="https://x.com/user/status/999")
    assert sr.source_type == "SOCIAL_MEDIA"
    assert sr.source_platform == "twitter"


def test_gemini_provider_configuration_and_url_extraction():
    provider = GeminiSearchProvider(api_key="AIzaSyDummyKeyForTestingPurposes12345")
    assert provider.is_configured() is True
    assert provider.name == "gemini"

    unconfigured = GeminiSearchProvider(api_key="")
    assert unconfigured.is_configured() is False

    # Test text URL parser helper
    sample_text = (
        "Here are the discovered sources:\n"
        "- Official archive: https://example.com/photos/archive/100\n"
        "- Article report: https://news.example.org/tech/2026/face-id-launch.\n"
        "No other URLs."
    )
    urls = provider._extract_urls_from_text(sample_text)
    assert "https://example.com/photos/archive/100" in urls
    assert "https://news.example.org/tech/2026/face-id-launch" in urls
    assert len(urls) == 2


def test_representation_builder():
    builder = RepresentationBuilder(use_full_image=True, use_face_crop=True, padding_ratio=0.20)
    img = Image.new("RGB", (500, 500), color=(100, 150, 200))
    face_box = (100, 100, 200, 200)  # 100x100 face

    reps = builder.build(img, face_box)
    assert reps.full_image_bytes is not None
    assert reps.face_crop_bytes is not None
    assert len(reps.full_image_bytes) > 0
    assert len(reps.face_crop_bytes) > 0


def test_cascade_primary_success():
    primary_results = [
        SearchResult(url="https://example.com/page1", title="Page 1", provider="gemini", representation="full_image")
    ]
    primary = MockSearchProvider("gemini", is_conf=True, results=primary_results)
    fallback = MockSearchProvider("serpapi", is_conf=True, results=[])
    tertiary = MockSearchProvider("tineye", is_conf=True, results=[])

    cascade = SearchCascade(primary, fallback, tertiary)
    builder = RepresentationBuilder()
    reps = builder.build(Image.new("RGB", (100, 100)), face_box=(10, 10, 50, 50))

    res = cascade.run(reps)
    assert res.status == "SUCCESS"
    assert res.winning_provider == "gemini"
    assert len(res.candidates) == 1
    assert res.candidates[0].url == "https://example.com/page1"


def test_cascade_fallback_on_primary_failure():
    primary = MockSearchProvider("gemini", is_conf=True, results=[], should_raise=True)
    fallback_results = [
        SearchResult(url="https://fallback.com/page", title="Fallback Page", provider="serpapi", representation="full_image")
    ]
    fallback = MockSearchProvider("serpapi", is_conf=True, results=fallback_results)
    tertiary = MockSearchProvider("tineye", is_conf=True, results=[])

    cascade = SearchCascade(primary, fallback, tertiary)
    builder = RepresentationBuilder()
    reps = builder.build(Image.new("RGB", (100, 100)), face_box=(10, 10, 50, 50))

    res = cascade.run(reps)
    assert res.status == "SUCCESS"
    assert res.winning_provider == "serpapi"
    assert len(res.candidates) == 1
    assert res.candidates[0].url == "https://fallback.com/page"


def test_cascade_all_empty_returns_no_match():
    primary = MockSearchProvider("gemini", is_conf=True, results=[])
    fallback = MockSearchProvider("serpapi", is_conf=True, results=[])
    tertiary = MockSearchProvider("tineye", is_conf=True, results=[])

    cascade = SearchCascade(primary, fallback, tertiary)
    builder = RepresentationBuilder()
    reps = builder.build(Image.new("RGB", (100, 100)), face_box=(10, 10, 50, 50))

    res = cascade.run(reps)
    assert res.status == "NO_MATCH"
    assert len(res.candidates) == 0
