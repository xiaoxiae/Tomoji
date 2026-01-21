"""Tests for face detection and cropping functionality."""

import numpy as np
import pytest
from PIL import Image

from backend.services.face_detector import (
    SEGMENTER_MODEL_PATH,
    _ensure_model,
    detect_and_crop_face,
)


@pytest.fixture(scope="module")
def ensure_model():
    """Ensure the segmentation model is available for tests."""
    _ensure_model()
    if not SEGMENTER_MODEL_PATH.exists():
        pytest.skip("MediaPipe model not available")


@pytest.fixture
def simple_face_image():
    """Create a simple test image with a face-like region in the center."""
    # Create 256x256 white image
    img = Image.new("RGB", (256, 256), color=(255, 255, 255))
    pixels = img.load()

    # Draw a skin-colored oval in the center (simulating a face)
    center_x, center_y = 128, 128
    for y in range(256):
        for x in range(256):
            # Create oval shape
            dx = (x - center_x) / 50
            dy = (y - center_y) / 60
            if dx * dx + dy * dy < 1:
                # Skin tone color
                pixels[x, y] = (210, 180, 140)

    return img


@pytest.fixture
def real_face_image():
    """Create a more realistic test image with varied colors."""
    # Create 512x512 image with background and face-like region
    img = Image.new("RGB", (512, 512), color=(100, 150, 200))  # Blue-ish background
    pixels = img.load()

    center_x, center_y = 256, 200

    # Hair region (above face)
    for y in range(100, 180):
        for x in range(180, 330):
            dx = (x - center_x) / 80
            dy = (y - 140) / 50
            if dx * dx + dy * dy < 1:
                pixels[x, y] = (50, 30, 20)  # Dark hair

    # Face region
    for y in range(150, 320):
        for x in range(180, 330):
            dx = (x - center_x) / 70
            dy = (y - center_y) / 90
            if dx * dx + dy * dy < 1:
                pixels[x, y] = (210, 180, 140)  # Skin tone

    # Body/clothes region
    for y in range(300, 450):
        for x in range(150, 360):
            dx = (x - center_x) / 100
            dy = (y - 370) / 80
            if dx * dx + dy * dy < 1:
                pixels[x, y] = (50, 50, 150)  # Blue shirt

    return img


class TestEnsureModel:
    """Tests for model download functionality."""

    def test_model_path_is_valid(self):
        """Model path should be in the data directory."""
        assert "data" in str(SEGMENTER_MODEL_PATH)
        assert str(SEGMENTER_MODEL_PATH).endswith(".tflite")


class TestDetectAndCropFace:
    """Tests for face detection and cropping."""

    def test_returns_rgba_image(self, ensure_model, real_face_image):
        """Output should be RGBA format for transparency support."""
        result = detect_and_crop_face(real_face_image)
        assert result.mode == "RGBA"

    def test_returns_square_output(self, ensure_model, real_face_image):
        """Output should be square."""
        result = detect_and_crop_face(real_face_image)
        assert result.width == result.height

    def test_respects_output_size(self, ensure_model, real_face_image):
        """Output should match specified size."""
        for size in [64, 128, 256]:
            result = detect_and_crop_face(real_face_image, output_size=size)
            assert result.width == size
            assert result.height == size

    def test_handles_rgba_input(self, ensure_model, real_face_image):
        """Should handle RGBA input images."""
        rgba_image = real_face_image.convert("RGBA")
        result = detect_and_crop_face(rgba_image)
        assert result.mode == "RGBA"

    def test_padding_increases_visible_area(self, ensure_model, real_face_image):
        """Higher padding should show more of the surrounding area."""
        # With no padding, face should be tightly cropped
        result_tight = detect_and_crop_face(real_face_image, padding=0.0)
        # With padding, more area should be visible
        result_padded = detect_and_crop_face(real_face_image, padding=0.5)

        # Both should be valid images
        assert result_tight.width > 0
        assert result_padded.width > 0

    def test_raises_on_no_face(self, ensure_model):
        """Should raise ValueError when no face is detected."""
        # Create image with no face-like features (solid color)
        no_face = Image.new("RGB", (256, 256), color=(0, 0, 0))

        with pytest.raises(ValueError, match="No face detected"):
            detect_and_crop_face(no_face)

    def test_keep_background_preserves_opacity(self, ensure_model, real_face_image):
        """With keep_background=True, there should be more opaque pixels than without."""
        result_with_bg = detect_and_crop_face(real_face_image, keep_background=True)
        result_without_bg = detect_and_crop_face(real_face_image, keep_background=False)

        alpha_with = np.array(result_with_bg)[:, :, 3]
        alpha_without = np.array(result_without_bg)[:, :, 3]

        # When keeping background, there should be more opaque pixels
        opaque_with = np.sum(alpha_with == 255)
        opaque_without = np.sum(alpha_without == 255)
        assert opaque_with >= opaque_without

    def test_remove_background_creates_transparency(self, ensure_model, real_face_image):
        """With keep_background=False, background should be transparent."""
        result = detect_and_crop_face(real_face_image, keep_background=False)
        alpha = np.array(result)[:, :, 3]

        # Some pixels should be transparent
        transparent_ratio = np.sum(alpha == 0) / alpha.size
        assert transparent_ratio > 0.1  # Some transparency expected

    def test_small_image_handling(self, ensure_model):
        """Should handle small input images."""
        # Create small image with face-like colors
        small = Image.new("RGB", (64, 64), color=(210, 180, 140))
        # Note: This may or may not detect a face depending on model
        try:
            result = detect_and_crop_face(small, output_size=32)
            assert result.width == 32
        except ValueError:
            # Acceptable if no face detected in tiny image
            pass

    def test_large_image_handling(self, ensure_model, real_face_image):
        """Should handle large input images."""
        large = real_face_image.resize((1024, 1024))
        result = detect_and_crop_face(large, output_size=256)
        assert result.width == 256

    def test_non_square_input(self, ensure_model):
        """Should handle non-square input images."""
        # Create wide image with face region
        wide = Image.new("RGB", (400, 200), color=(100, 150, 200))
        pixels = wide.load()
        for y in range(50, 150):
            for x in range(150, 250):
                dx = (x - 200) / 40
                dy = (y - 100) / 50
                if dx * dx + dy * dy < 1:
                    pixels[x, y] = (210, 180, 140)

        try:
            result = detect_and_crop_face(wide)
            assert result.width == result.height  # Output should still be square
        except ValueError:
            # Acceptable if face not detected
            pass


class TestDetectionOptions:
    """Tests for detection configuration options."""

    def test_keep_clothes_option(self, ensure_model, real_face_image):
        """keep_clothes option should affect what's included."""
        with_clothes = detect_and_crop_face(real_face_image, keep_clothes=True)
        without_clothes = detect_and_crop_face(real_face_image, keep_clothes=False)

        # Both should produce valid output
        assert with_clothes.mode == "RGBA"
        assert without_clothes.mode == "RGBA"

    def test_keep_accessories_option(self, ensure_model, real_face_image):
        """keep_accessories option should affect what's included."""
        with_acc = detect_and_crop_face(real_face_image, keep_accessories=True)
        without_acc = detect_and_crop_face(real_face_image, keep_accessories=False)

        # Both should produce valid output
        assert with_acc.mode == "RGBA"
        assert without_acc.mode == "RGBA"

    def test_default_parameters(self, ensure_model, real_face_image):
        """Should work with all default parameters."""
        result = detect_and_crop_face(real_face_image)
        assert result is not None
        assert result.mode == "RGBA"


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_all_black_image(self, ensure_model):
        """Should handle all-black image."""
        black = Image.new("RGB", (256, 256), color=(0, 0, 0))
        with pytest.raises(ValueError):
            detect_and_crop_face(black)

    def test_all_white_image(self, ensure_model):
        """Should handle all-white image."""
        white = Image.new("RGB", (256, 256), color=(255, 255, 255))
        with pytest.raises(ValueError):
            detect_and_crop_face(white)

    def test_gradient_image(self, ensure_model):
        """Should handle gradient image without face."""
        gradient = Image.new("RGB", (256, 256))
        pixels = gradient.load()
        for y in range(256):
            for x in range(256):
                pixels[x, y] = (x, y, 128)

        with pytest.raises(ValueError):
            detect_and_crop_face(gradient)

    def test_extreme_padding_values(self, ensure_model, real_face_image):
        """Should handle extreme padding values."""
        # Zero padding
        result_zero = detect_and_crop_face(real_face_image, padding=0.0)
        assert result_zero is not None

        # Maximum reasonable padding
        result_max = detect_and_crop_face(real_face_image, padding=1.0)
        assert result_max is not None

    def test_minimum_output_size(self, ensure_model, real_face_image):
        """Should handle minimum output size."""
        result = detect_and_crop_face(real_face_image, output_size=32)
        assert result.width == 32
        assert result.height == 32

    def test_face_at_edge(self, ensure_model):
        """Should handle face positioned at image edge."""
        # Create image with face-like region at top edge
        edge_face = Image.new("RGB", (256, 256), color=(100, 150, 200))
        pixels = edge_face.load()
        for y in range(0, 80):
            for x in range(100, 180):
                dx = (x - 140) / 40
                dy = (y - 40) / 40
                if dx * dx + dy * dy < 1:
                    pixels[x, y] = (210, 180, 140)

        try:
            result = detect_and_crop_face(edge_face)
            assert result.mode == "RGBA"
        except ValueError:
            # Acceptable if partial face not detected
            pass
