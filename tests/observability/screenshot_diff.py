"""
ScreenshotDiffer — Pixel-based image comparison using Pillow (no OpenCV).

Outputs a diff image with changed pixels highlighted and a diff ratio (0.0-1.0)
representing the fraction of changed pixels.

Designed for head-to-head comparison of SketchUp or Blender screenshots
before and after model mutations.
"""

import os

try:
    from PIL import Image, ImageChops
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False


class ScreenshotDiffer:
    """Compare two images pixel-wise and produce a diff image + ratio.

    Parameters:
        threshold: perceptual tolerance (0-255). Pixels whose per-channel
                   absolute difference is below this threshold in all channels
                   are considered unchanged. Default: 10 (ignores minor
                   rendering noise from anti-aliasing, JPEG artifacts).
    """

    def __init__(self, threshold=10):
        if not HAS_PILLOW:
            raise ImportError(
                "Pillow is required for screenshot diffing. "
                "Install it with: uv add Pillow"
            )
        self._threshold = max(0, min(255, threshold))

    def compare(self, before_path, after_path, diff_output_path=None):
        """Compare two image files.

        Args:
            before_path: path to the 'before' image.
            after_path: path to the 'after' image.
            diff_output_path: optional path to write the diff image.
                              If None, no diff image is written.

        Returns:
            dict with keys:
                diff_ratio: float 0.0 (identical) to 1.0 (completely different).
                changed_pixels: int count of changed pixels.
                total_pixels: int total pixel count.
                diff_path: str or None (path to diff image if written).
                dimensions_match: bool — True if both images are same size.
                error: str or None if an error occurred.

        Raises:
            FileNotFoundError: if either input path doesn't exist.
        """
        for p in (before_path, after_path):
            if not os.path.exists(p):
                raise FileNotFoundError(f"Image not found: {p}")

        try:
            img_a = Image.open(before_path).convert("RGB")
            img_b = Image.open(after_path).convert("RGB")
        except Exception as exc:
            return {
                "diff_ratio": 1.0,
                "changed_pixels": 0,
                "total_pixels": 0,
                "diff_path": None,
                "dimensions_match": False,
                "error": f"Failed to open images: {exc}",
            }

        # Check dimensions
        if img_a.size != img_b.size:
            # Resize B to match A for comparison
            img_b = img_b.resize(img_a.size, Image.LANCZOS)
            dimensions_match = False
        else:
            dimensions_match = True

        # Pixel-wise absolute difference
        diff_img = ImageChops.difference(img_a, img_b)

        # Apply threshold: pixels where max channel diff <= threshold are black
        if self._threshold > 0:
            # Create a mask of pixels that exceed the threshold
            bands = diff_img.split()
            mask = bands[0].point(lambda x: 255 if x > self._threshold else 0)
            for band in bands[1:]:
                band_mask = band.point(lambda x: 255 if x > self._threshold else 0)
                mask = ImageChops.logical_or(mask, band_mask)
            # Highlight changed pixels in bright red
            highlight = Image.new("RGB", diff_img.size, (255, 0, 0))
            diff_img = Image.composite(highlight, Image.new("RGB", diff_img.size, (0, 0, 0)), mask)

        # Count changed pixels
        # A pixel is "changed" if any channel differs beyond threshold
        extrema = diff_img.getextrema()
        total_pixels = img_a.size[0] * img_a.size[1]
        # Count non-black pixels in the diff image
        gray = diff_img.convert("L")
        changed_pixels = gray.point(lambda x: 1 if x > 0 else 0).getdata().count(1)

        diff_ratio = changed_pixels / max(total_pixels, 1)

        result = {
            "diff_ratio": round(diff_ratio, 6),
            "changed_pixels": changed_pixels,
            "total_pixels": total_pixels,
            "dimensions_match": dimensions_match,
            "error": None,
        }

        # Write diff image
        if diff_output_path:
            os.makedirs(os.path.dirname(diff_output_path) or ".", exist_ok=True)
            diff_img.save(diff_output_path)
            result["diff_path"] = diff_output_path
        else:
            result["diff_path"] = None

        return result
