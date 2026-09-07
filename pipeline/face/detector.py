"""
Face Detection and Quality Validation Module.
Handles multi-face detection, bounding box extraction, quality checks (blur, size),
and standardized face selection (largest bbox by default).
"""

from dataclasses import dataclass, field
import io
import logging
from typing import List, Optional, Tuple, Union

import cv2
from facenet_pytorch import MTCNN
import numpy as np
from PIL import Image
import torch

logger = logging.getLogger("pipeline.face.detector")


@dataclass
class FaceDetectionResult:
    """Detailed result of face detection and quality validation."""
    success: bool
    total_faces: int = 0
    selected_index: int = -1
    box: Optional[Tuple[int, int, int, int]] = None  # (x1, y1, x2, y2)
    confidence: float = 0.0
    all_boxes: List[Tuple[int, int, int, int]] = field(default_factory=list)
    is_blurry: bool = False
    blur_score: float = 0.0
    crop_image: Optional[Image.Image] = None
    error_message: Optional[str] = None


class FaceDetector:
    """
    Robust Face Detector using MTCNN with fallback to OpenCV Haar Cascade.
    Performs face localization, size validation, and Laplacian blur detection.
    """

    def __init__(
        self,
        min_face_size: int = 80,
        blur_threshold: float = 60.0,
        selection_mode: str = "largest",
        device: Optional[str] = None,
    ):
        self.min_face_size = min_face_size
        self.blur_threshold = blur_threshold
        self.selection_mode = selection_mode
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        # Initialize MTCNN detector
        self._mtcnn = MTCNN(
            image_size=160,
            margin=0,
            min_face_size=max(20, min_face_size // 2),
            thresholds=[0.6, 0.7, 0.7],
            factor=0.709,
            post_process=False,
            device=self.device,
            keep_all=True,
        )

        # Initialize OpenCV Cascade as a fallback
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self._haar_cascade = cv2.CascadeClassifier(cascade_path)

    def _load_image(self, image_input: Union[str, bytes, Image.Image, np.ndarray]) -> Image.Image:
        """Standardizes input into a PIL RGB Image."""
        if isinstance(image_input, str):
            img = Image.open(image_input)
        elif isinstance(image_input, bytes):
            img = Image.open(io.BytesIO(image_input))
        elif isinstance(image_input, np.ndarray):
            if len(image_input.shape) == 2:
                img = Image.fromarray(image_input).convert("RGB")
            elif image_input.shape[2] == 4:
                img = Image.fromarray(cv2.cvtColor(image_input, cv2.COLOR_BGRA2RGB))
            elif image_input.shape[2] == 3:
                # Default cv2 BGR -> RGB
                img = Image.fromarray(cv2.cvtColor(image_input, cv2.COLOR_BGR2RGB))
            else:
                img = Image.fromarray(image_input).convert("RGB")
        elif isinstance(image_input, Image.Image):
            img = image_input
        else:
            raise ValueError(f"Unsupported image input type: {type(image_input)}")

        return img.convert("RGB")

    def _calculate_blur_score(self, face_np: np.ndarray) -> float:
        """Calculates Laplacian variance of the grayscale face crop."""
        if face_np.size == 0:
            return 0.0
        if len(face_np.shape) == 3:
            gray = cv2.cvtColor(face_np, cv2.COLOR_RGB2GRAY)
        else:
            gray = face_np
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    def detect(
        self,
        image_input: Union[str, bytes, Image.Image, np.ndarray],
        force_index: Optional[int] = None,
    ) -> FaceDetectionResult:
        """
        Detects faces in the image, checks quality metrics, and selects the primary face.
        """
        try:
            pil_img = self._load_image(image_input)
            img_w, img_h = pil_img.size
        except Exception as e:
            logger.error(f"Failed to read image input: {e}")
            return FaceDetectionResult(
                success=False,
                error_message=f"Invalid image input: {e}",
            )

        boxes = []
        confidences = []

        # 1. Primary detection with MTCNN
        try:
            detected_boxes, detected_probs = self._mtcnn.detect(pil_img)
            if detected_boxes is not None and len(detected_boxes) > 0:
                for b, p in zip(detected_boxes, detected_probs):
                    if p is not None and p >= 0.70:
                        x1 = max(0, int(b[0]))
                        y1 = max(0, int(b[1]))
                        x2 = min(img_w, int(b[2]))
                        y2 = min(img_h, int(b[3]))
                        if (x2 - x1) > 10 and (y2 - y1) > 10:
                            boxes.append((x1, y1, x2, y2))
                            confidences.append(float(p))
        except Exception as e:
            logger.warning(f"MTCNN detection error: {e}. Falling back to OpenCV Cascade.")

        # 2. Fallback to OpenCV Haar Cascade if MTCNN returns nothing
        if len(boxes) == 0:
            np_img = np.array(pil_img)
            gray = cv2.cvtColor(np_img, cv2.COLOR_RGB2GRAY)
            haar_faces = self._haar_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
            )
            for (x, y, w, h) in haar_faces:
                boxes.append((int(x), int(y), int(x + w), int(y + h)))
                confidences.append(0.85)

        if len(boxes) == 0:
            logger.info("No faces detected in the provided image.")
            return FaceDetectionResult(
                success=False,
                total_faces=0,
                error_message="NO_FACE_DETECTED",
            )

        # Log all detected face bounding boxes
        logger.info(f"Detected {len(boxes)} face(s): {boxes}")

        # 3. Face Selection: Largest by area (default) or specified index
        if force_index is not None and 0 <= force_index < len(boxes):
            selected_idx = force_index
        elif self.selection_mode == "largest" or len(boxes) == 1:
            # Pick the box with the maximum area
            areas = [(b[2] - b[0]) * (b[3] - b[1]) for b in boxes]
            selected_idx = int(np.argmax(areas))
        else:
            selected_idx = 0

        selected_box = boxes[selected_idx]
        selected_conf = confidences[selected_idx]
        bw = selected_box[2] - selected_box[0]
        bh = selected_box[3] - selected_box[1]

        logger.info(
            f"Selected face #{selected_idx} [bbox={selected_box}, size={bw}x{bh}px, conf={selected_conf:.3f}]"
        )

        # Crop selected face
        crop = pil_img.crop(selected_box)
        crop_np = np.array(crop)

        # 4. Quality Validation: Minimum size
        if bw < self.min_face_size or bh < self.min_face_size:
            logger.warning(
                f"Selected face size ({bw}x{bh}px) is below min threshold ({self.min_face_size}px)."
            )
            # Still provide crop but mark quality failure
            return FaceDetectionResult(
                success=False,
                total_faces=len(boxes),
                selected_index=selected_idx,
                box=selected_box,
                confidence=selected_conf,
                all_boxes=boxes,
                crop_image=crop,
                error_message=f"FACE_TOO_SMALL: {bw}x{bh}px < {self.min_face_size}px",
            )

        # 5. Quality Validation: Blur detection (Laplacian variance)
        blur_val = self._calculate_blur_score(crop_np)
        is_blurry = blur_val < self.blur_threshold
        if is_blurry:
            logger.warning(
                f"Face crop detected as blurry (variance: {blur_val:.1f} < threshold: {self.blur_threshold})"
            )

        return FaceDetectionResult(
            success=True,
            total_faces=len(boxes),
            selected_index=selected_idx,
            box=selected_box,
            confidence=selected_conf,
            all_boxes=boxes,
            is_blurry=is_blurry,
            blur_score=blur_val,
            crop_image=crop,
        )
