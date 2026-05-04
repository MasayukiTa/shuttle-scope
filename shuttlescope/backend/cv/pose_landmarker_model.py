from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlretrieve

logger = logging.getLogger(__name__)

POSE_LANDMARKER_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_lite/float16/latest/"
    "pose_landmarker_lite.task"
)
DEFAULT_POSE_LANDMARKER_PATH = (
    Path(__file__).resolve().parent / "models" / "pose_landmarker_lite.task"
)


def resolve_pose_landmarker_model(*, download_if_missing: bool) -> Path:
    """Return a local Pose Landmarker model path, downloading it if needed."""
    model_path_env = os.environ.get("SS_POSE_LANDMARKER_MODEL")
    model_path = Path(model_path_env) if model_path_env else DEFAULT_POSE_LANDMARKER_PATH

    if model_path.exists():
        return model_path

    if not download_if_missing:
        raise ImportError(
            f"PoseLandmarker model not found: {model_path}. "
            "Set SS_POSE_LANDMARKER_MODEL or run the setup script first."
        )

    model_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        logger.info("[cv.pose_landmarker_model] downloading model to %s", model_path)
        urlretrieve(POSE_LANDMARKER_URL, model_path)
    except (OSError, URLError) as exc:
        raise ImportError(
            f"Failed to download PoseLandmarker model from {POSE_LANDMARKER_URL}"
        ) from exc

    return model_path
