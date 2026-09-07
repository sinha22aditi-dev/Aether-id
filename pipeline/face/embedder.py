"""
Face Embedding and Biometric Similarity Module.
Extracts 512-dimensional L2-normalized embeddings using InceptionResnetV1 (VGGFace2).
Computes exact cosine similarity between biometric face embeddings.
"""

import logging
from typing import Optional, Union

from facenet_pytorch import InceptionResnetV1
import numpy as np
from PIL import Image
import torch
import torchvision.transforms as transforms

logger = logging.getLogger("pipeline.face.embedder")


def compute_cosine_similarity(emb1: np.ndarray, emb2: np.ndarray) -> float:
    """
    Computes genuine cosine similarity between two biometric embeddings.
    Cosine similarity = dot(e1, e2) / (||e1|| * ||e2||)
    Returns a float in [-1.0, 1.0].
    """
    if emb1 is None or emb2 is None:
        return 0.0
    v1 = np.asarray(emb1, dtype=np.float32).flatten()
    v2 = np.asarray(emb2, dtype=np.float32).flatten()
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    sim = np.dot(v1, v2) / (norm1 * norm2)
    return float(np.clip(sim, -1.0, 1.0))


class FaceEmbedder:
    """
    Generates 512-d L2-normalized facial embeddings using InceptionResnetV1.
    """

    def __init__(self, model_name: str = "vggface2", device: Optional[str] = None):
        self.model_name = model_name
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model_version = f"facenet-inceptionresnetv1-{model_name}-512d"

        logger.info(f"Loading FaceEmbedder ({self.model_version}) on device: {self.device}")
        self._model = InceptionResnetV1(pretrained=model_name).eval().to(self.device)

        # Standard normalization for InceptionResnetV1 face crops (160x160, mean/std)
        self._transform = transforms.Compose([
            transforms.Resize((160, 160)),
            transforms.ToTensor(),
            # Fixed standard image standardization: (x - 127.5) / 128.0
            transforms.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
        ])

    def get_embedding(self, face_image: Union[Image.Image, np.ndarray]) -> np.ndarray:
        """
        Extracts 512-d L2-normalized embedding for a given face crop.
        """
        if isinstance(face_image, np.ndarray):
            face_pil = Image.fromarray(face_image).convert("RGB")
        elif isinstance(face_image, Image.Image):
            face_pil = face_image.convert("RGB")
        else:
            raise ValueError(f"Unsupported face image type: {type(face_image)}")

        # Transform and add batch dimension
        tensor = self._transform(face_pil).unsqueeze(0).to(self.device)

        with torch.no_grad():
            embedding_tensor = self._model(tensor)
            # Embedding tensor shape: (1, 512)
            emb = embedding_tensor.squeeze(0).cpu().numpy()

        # L2-normalize vector
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm

        return emb.astype(np.float32)
