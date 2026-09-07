"""
Search Representations Generator.
Prepares Representation A (full original image with background context)
and Representation B (padded face crop with 20% margin).
"""

from dataclasses import dataclass
import io
import logging
from typing import Optional, Tuple, Union

import numpy as np
from PIL import Image

logger = logging.getLogger("pipeline.search.representations")


@dataclass
class SearchRepresentations:
    """Container holding prepared image byte buffers for reverse search."""
    full_image_bytes: Optional[bytes] = None
    face_crop_bytes: Optional[bytes] = None


class RepresentationBuilder:
    """
    Constructs multi-representation search payloads from the input image
    and detected face bounding box.
    """

    def __init__(
        self,
        use_full_image: bool = True,
        use_face_crop: bool = True,
        padding_ratio: float = 0.20,
        max_full_dim: int = 1024,
    ):
        self.use_full_image = use_full_image
        self.use_face_crop = use_face_crop
        self.padding_ratio = padding_ratio
        self.max_full_dim = max_full_dim

    def _to_pil(self, img_input: Union[str, bytes, Image.Image, np.ndarray]) -> Image.Image:
        if isinstance(img_input, str):
            return Image.open(img_input).convert("RGB")
        elif isinstance(img_input, bytes):
            return Image.open(io.BytesIO(img_input)).convert("RGB")
        elif isinstance(img_input, np.ndarray):
            return Image.fromarray(img_input).convert("RGB")
        elif isinstance(img_input, Image.Image):
            return img_input.convert("RGB")
        else:
            raise ValueError(f"Unsupported image input type: {type(img_input)}")

    def _encode_jpeg(self, img: Image.Image, quality: int = 92) -> bytes:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()

    def build(
        self,
        image_input: Union[str, bytes, Image.Image, np.ndarray],
        face_box: Optional[Tuple[int, int, int, int]] = None,
    ) -> SearchRepresentations:
        """
        Generates Representation A (full image) and Representation B (padded crop).
        """
        pil_img = self._to_pil(image_input)
        img_w, img_h = pil_img.size

        full_bytes = None
        crop_bytes = None

        # 1. Representation A: Full image with rich visual context
        if self.use_full_image:
            full_img = pil_img.copy()
            if max(img_w, img_h) > self.max_full_dim:
                full_img.thumbnail((self.max_full_dim, self.max_full_dim), Image.Resampling.LANCZOS)
            full_bytes = self._encode_jpeg(full_img, quality=90)
            logger.info(f"Built Representation A (Full Image): {len(full_bytes)} bytes")

        # 2. Representation B: Padded face crop (+20% margin around bounding box)
        if self.use_face_crop and face_box is not None:
            x1, y1, x2, y2 = face_box
            w = x2 - x1
            h = y2 - y1

            pad_x = int(w * self.padding_ratio)
            pad_y = int(h * self.padding_ratio)

            crop_x1 = max(0, x1 - pad_x)
            crop_y1 = max(0, y1 - pad_y)
            crop_x2 = min(img_w, x2 + pad_x)
            crop_y2 = min(img_h, y2 + pad_y)

            crop_img = pil_img.crop((crop_x1, crop_y1, crop_x2, crop_y2))
            crop_bytes = self._encode_jpeg(crop_img, quality=95)
            logger.info(
                f"Built Representation B (Padded Face Crop, +{int(self.padding_ratio*100)}%): "
                f"{crop_img.size[0]}x{crop_img.size[1]}px, {len(crop_bytes)} bytes"
            )

        return SearchRepresentations(
            full_image_bytes=full_bytes,
            face_crop_bytes=crop_bytes,
        )
