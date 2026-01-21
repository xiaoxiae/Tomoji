import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from PIL import Image
import urllib.request

from backend.config import (
    DEFAULT_PADDING, DEFAULT_OUTPUT_SIZE,
    DEFAULT_KEEP_BACKGROUND, DEFAULT_KEEP_CLOTHES, DEFAULT_KEEP_ACCESSORIES, DATA_DIR
)

# Model paths
SEGMENTER_MODEL_PATH = DATA_DIR / "selfie_multiclass_256x256.tflite"
SEGMENTER_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite"

# Segmentation categories:
# 0 - background
# 1 - hair
# 2 - body-skin
# 3 - face-skin
# 4 - clothes
# 5 - others (accessories)


def _ensure_model():
    """Download the segmentation model if not present."""
    if not SEGMENTER_MODEL_PATH.exists():
        SEGMENTER_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(SEGMENTER_MODEL_URL, SEGMENTER_MODEL_PATH)


def detect_and_crop_face(
    image: Image.Image,
    padding: float = DEFAULT_PADDING,
    output_size: int = DEFAULT_OUTPUT_SIZE,
    keep_background: bool = DEFAULT_KEEP_BACKGROUND,
    keep_clothes: bool = DEFAULT_KEEP_CLOTHES,
    keep_accessories: bool = DEFAULT_KEEP_ACCESSORIES
) -> Image.Image:
    """
    Segment face using multiclass model, remove background, and fit to square output.

    Args:
        image: PIL Image to process
        padding: Extra padding around detected face (0.0-1.0)
        output_size: Output image size in pixels (square)
        keep_background: If True, preserve original background instead of making it transparent
        keep_clothes: If True, include clothes (category 4) in the segmentation mask
        keep_accessories: If True, include accessories like glasses (category 5) in the mask

    Returns:
        Cropped and resized PIL Image with transparent or original background

    Raises:
        ValueError: If no face is detected
    """
    _ensure_model()

    # Convert PIL to RGB numpy array
    if image.mode == "RGBA":
        image = image.convert("RGB")
    rgb_image = np.array(image)
    h, w = rgb_image.shape[:2]

    # Create MediaPipe Image
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)

    # Create image segmenter
    base_options = python.BaseOptions(model_asset_path=str(SEGMENTER_MODEL_PATH))
    options = vision.ImageSegmenterOptions(
        base_options=base_options,
        output_category_mask=True
    )

    with vision.ImageSegmenter.create_from_options(options) as segmenter:
        result = segmenter.segment(mp_image)

        # Get category mask
        category_mask = result.category_mask.numpy_view()

        # Create mask for what we want to keep:
        # Always include: 1 - hair, 2 - body-skin, 3 - face-skin
        # Conditionally include: 4 - clothes, 5 - accessories
        keep_mask = (
            (category_mask == 1) |  # hair
            (category_mask == 2) |  # body-skin (neck, ears)
            (category_mask == 3)    # face-skin
        )
        if keep_clothes:
            keep_mask = keep_mask | (category_mask == 4)  # clothes
        if keep_accessories:
            keep_mask = keep_mask | (category_mask == 5)  # accessories (glasses, earrings)
        keep_mask = keep_mask.astype(np.uint8)

        # Find bounding box based on kept regions (face + hair + accessories)
        coords = np.where(keep_mask > 0)

        if len(coords[0]) == 0:
            raise ValueError("No face detected in image")

        # Get tight bounding box around all kept regions
        y_min, y_max = coords[0].min(), coords[0].max()
        x_min, x_max = coords[1].min(), coords[1].max()

        # Calculate center and size of kept region
        center_x = (x_min + x_max) // 2
        center_y = (y_min + y_max) // 2
        region_w = x_max - x_min
        region_h = y_max - y_min

        # Apply padding to the region
        padded_w = int(region_w * (1 + padding * 2))
        padded_h = int(region_h * (1 + padding * 2))

        # Calculate crop coordinates (centered on face region)
        x1 = center_x - padded_w // 2
        y1 = center_y - padded_h // 2
        x2 = center_x + padded_w // 2
        y2 = center_y + padded_h // 2

        # Handle edge cases - pad with transparent if necessary
        pad_left = max(0, -x1)
        pad_top = max(0, -y1)
        pad_right = max(0, x2 - w)
        pad_bottom = max(0, y2 - h)

        # Clamp coordinates to image bounds
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(w, x2)
        y2 = min(h, y2)

        # Create RGBA image with transparency or full opacity
        if keep_background:
            alpha = np.full((h, w), 255, dtype=np.uint8)  # Fully opaque
        else:
            alpha = (keep_mask * 255).astype(np.uint8)  # Masked transparency
        rgba_image = np.dstack([rgb_image, alpha])

        # Crop the RGBA image (tight crop around kept regions)
        cropped = rgba_image[y1:y2, x1:x2]

        # Pad if necessary (with transparent pixels)
        if pad_left > 0 or pad_top > 0 or pad_right > 0 or pad_bottom > 0:
            cropped = cv2.copyMakeBorder(
                cropped,
                pad_top, pad_bottom, pad_left, pad_right,
                cv2.BORDER_CONSTANT,
                value=[0, 0, 0, 0]  # Transparent
            )

        # Output is always square
        out_h = output_size
        out_w = output_size

        # Fit cropped face into output dimensions (maintain proportions, center, pad)
        crop_h, crop_w = cropped.shape[:2]

        # Calculate scale to fit within output bounds
        scale_w = out_w / crop_w
        scale_h = out_h / crop_h
        scale = min(scale_w, scale_h)  # Use smaller scale to ensure face fits

        # Resize the cropped face
        new_w = int(crop_w * scale)
        new_h = int(crop_h * scale)
        resized = cv2.resize(cropped, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Create output canvas with transparent background
        output = np.zeros((out_h, out_w, 4), dtype=np.uint8)

        # Center the resized face on the canvas
        x_offset = (out_w - new_w) // 2
        y_offset = (out_h - new_h) // 2
        output[y_offset:y_offset + new_h, x_offset:x_offset + new_w] = resized

        return Image.fromarray(output, mode='RGBA')
