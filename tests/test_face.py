"""
Unit tests for Face Detection, Quality Checks, and Face Embedder.
"""

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import pytest

from pipeline.face.detector import FaceDetector, FaceDetectionResult
from pipeline.face.embedder import FaceEmbedder, compute_cosine_similarity


def create_synthetic_face_image(width=300, height=300, is_blurry=False) -> Image.Image:
    """Creates a synthetic face-like test image."""
    img = Image.new("RGB", (width, height), color=(240, 220, 200))
    draw = ImageDraw.Draw(img)

    # Face contour / head
    draw.ellipse([50, 40, 250, 260], fill=(255, 224, 189), outline=(100, 50, 30), width=3)
    # Eyes
    draw.ellipse([90, 100, 130, 130], fill=(255, 255, 255), outline=(0, 0, 0), width=2)
    draw.ellipse([105, 110, 120, 125], fill=(30, 80, 180))  # Pupil
    draw.ellipse([170, 100, 210, 130], fill=(255, 255, 255), outline=(0, 0, 0), width=2)
    draw.ellipse([180, 110, 195, 125], fill=(30, 80, 180))  # Pupil
    # Nose
    draw.polygon([(150, 130), (140, 175), (160, 175)], fill=(220, 180, 150))
    # Mouth
    draw.arc([110, 180, 190, 220], start=0, end=180, fill=(200, 50, 50), width=4)

    if is_blurry:
        img = img.filter(ImageFilter.GaussianBlur(radius=8))

    return img


def create_multi_face_image() -> Image.Image:
    """Creates an image with two faces of different sizes."""
    img = Image.new("RGB", (600, 400), color=(200, 200, 200))
    draw = ImageDraw.Draw(img)

    # Small face on left
    draw.ellipse([40, 50, 140, 170], fill=(255, 224, 189), outline=(0, 0, 0), width=2)
    draw.ellipse([60, 80, 80, 100], fill=(0, 0, 0))
    draw.ellipse([100, 80, 120, 100], fill=(0, 0, 0))
    draw.line([(70, 130), (110, 130)], fill=(200, 0, 0), width=3)

    # Large face on right (dominates area)
    draw.ellipse([220, 40, 520, 360], fill=(255, 224, 189), outline=(0, 0, 0), width=3)
    draw.ellipse([280, 120, 340, 170], fill=(255, 255, 255), outline=(0, 0, 0), width=2)
    draw.ellipse([300, 135, 325, 160], fill=(0, 0, 0))
    draw.ellipse([400, 120, 460, 170], fill=(255, 255, 255), outline=(0, 0, 0), width=2)
    draw.ellipse([415, 135, 440, 160], fill=(0, 0, 0))
    draw.polygon([(370, 170), (350, 230), (390, 230)], fill=(220, 180, 150))
    draw.arc([310, 240, 430, 300], start=0, end=180, fill=(200, 50, 50), width=5)

    return img


def test_no_face_detection():
    detector = FaceDetector()
    blank_img = Image.new("RGB", (200, 200), color=(128, 128, 128))
    result = detector.detect(blank_img)
    assert not result.success
    assert result.total_faces == 0
    assert result.error_message == "NO_FACE_DETECTED"


def test_face_detector_basic():
    detector = FaceDetector(min_face_size=50)
    face_img = create_synthetic_face_image()
    result = detector.detect(face_img)

    assert isinstance(result, FaceDetectionResult)
    # The detector should find at least one face (via MTCNN or Haar fallback)
    assert result.total_faces >= 1
    assert result.selected_index >= 0
    assert result.box is not None
    assert result.crop_image is not None


def test_face_blur_quality():
    detector = FaceDetector(min_face_size=50, blur_threshold=100.0)
    sharp_img = create_synthetic_face_image(is_blurry=False)
    blurry_img = create_synthetic_face_image(is_blurry=True)

    res_sharp = detector.detect(sharp_img)
    res_blurry = detector.detect(blurry_img)

    if res_sharp.success and res_blurry.success:
        assert res_sharp.blur_score > res_blurry.blur_score


def test_face_embedder_dimension_and_norm():
    embedder = FaceEmbedder()
    face_img = create_synthetic_face_image()

    emb = embedder.get_embedding(face_img)
    assert isinstance(emb, np.ndarray)
    assert emb.shape == (512,)
    # Embedding must be L2 normalized (unit length)
    norm = np.linalg.norm(emb)
    assert pytest.approx(norm, rel=1e-3) == 1.0


def test_cosine_similarity_identity_and_orthogonality():
    embedder = FaceEmbedder()
    img1 = create_synthetic_face_image(width=200, height=200)
    emb1 = embedder.get_embedding(img1)

    # Identical vector similarity must be 1.0
    sim_self = compute_cosine_similarity(emb1, emb1)
    assert pytest.approx(sim_self, rel=1e-4) == 1.0

    # Opposite vector similarity must be -1.0
    sim_neg = compute_cosine_similarity(emb1, -emb1)
    assert pytest.approx(sim_neg, rel=1e-4) == -1.0

    # Zero vector handling
    zero_vec = np.zeros(512, dtype=np.float32)
    assert compute_cosine_similarity(emb1, zero_vec) == 0.0
