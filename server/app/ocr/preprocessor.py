"""ImagePreprocessor — stateless PIL-based image preprocessing for OCR.

Pipeline: resize (long-edge cap) → grayscale → adaptive threshold.

OpenCV (cv2) is intentionally NOT used here.  The LLD §11 (Q1) defers the
OpenCV vs PIL decision to Meeting 5.  This implementation uses PIL +
``numpy`` for the adaptive threshold to keep the dependency footprint small
(OpenCV adds ~50 MB to the wheel).

**Adaptive threshold without OpenCV**:
We implement a per-block Gaussian-weighted mean threshold using only
``numpy`` and ``PIL``.  The formula mirrors ``cv2.adaptiveThreshold`` with
``ADAPTIVE_THRESH_GAUSSIAN_C``: for each pixel at (r, c) the threshold is

    T(r,c) = Gaussian_weighted_mean(block(r,c)) - C

Pixels brighter than T(r,c) are set to 255 (white); others to 0 (black).

This produces virtually identical output to OpenCV for the block_size=31,
C=10 parameters used in production, with no GUI / Qt dependencies.

**Deviation from LLD §3.2** (see README.md):
LLD §3.2 references ``cv2.adaptiveThreshold``.  We implement the equivalent
in numpy to avoid the OpenCV dependency.  If OpenCV is later added to
``requirements.txt``, swap ``_adaptive_threshold_numpy`` for the cv2 call —
the public ``ImagePreprocessor.preprocess()`` interface is unchanged.

Reference: docs/design/ocr/design.md §3.2, §3.3
"""

from __future__ import annotations

import math
from io import BytesIO

import numpy as np
from PIL import Image


class ImagePreprocessor:
    """Stateless image preprocessor.

    All methods are pure functions (no side effects, no state).  The class
    exists only to provide a logical namespace and to make future injection
    easy.
    """

    def __init__(
        self,
        max_long_edge_px: int = 2000,
        threshold_block_size: int = 31,
        threshold_c: int = 10,
    ) -> None:
        if threshold_block_size % 2 == 0:
            raise ValueError(
                f"threshold_block_size must be odd; got {threshold_block_size}"
            )
        self.max_long_edge_px = max_long_edge_px
        self.threshold_block_size = threshold_block_size
        self.threshold_c = threshold_c

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def preprocess(self, image_bytes: bytes) -> Image.Image:
        """Run the full preprocessing pipeline on raw image bytes.

        Returns a grayscale, adaptively-thresholded ``PIL.Image.Image`` in
        mode ``"L"``.

        Raises ``PIL.UnidentifiedImageError`` if ``image_bytes`` cannot be
        decoded as an image — callers must handle this.
        """
        img = Image.open(BytesIO(image_bytes))
        img = self._resize(img)
        img = img.convert("L")
        arr = self._adaptive_threshold_numpy(
            np.array(img, dtype=np.uint8),
            block_size=self.threshold_block_size,
            c_value=self.threshold_c,
        )
        return Image.fromarray(arr)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resize(self, img: Image.Image) -> Image.Image:
        """Cap the long edge at ``max_long_edge_px``, preserving aspect ratio.

        Images already within the limit pass through untouched.
        """
        w, h = img.size
        long_edge = max(w, h)
        if long_edge <= self.max_long_edge_px:
            return img
        scale = self.max_long_edge_px / long_edge
        new_w = max(1, math.floor(w * scale))
        new_h = max(1, math.floor(h * scale))
        return img.resize((new_w, new_h), Image.LANCZOS)

    @staticmethod
    def _adaptive_threshold_numpy(
        gray: np.ndarray,
        block_size: int,
        c_value: int,
    ) -> np.ndarray:
        """Compute an adaptive Gaussian-mean threshold in pure numpy.

        Parameters mirror ``cv2.adaptiveThreshold`` with
        ``ADAPTIVE_THRESH_GAUSSIAN_C`` + ``THRESH_BINARY``:
        - ``block_size``: odd integer; neighbourhood size around each pixel.
        - ``c_value``: constant subtracted from the weighted mean.

        Returns a binary uint8 array (values 0 or 255).
        """
        half = block_size // 2

        # Build a 1-D Gaussian kernel for the block.
        sigma = half / 3.0 if half > 0 else 1.0
        x = np.arange(-half, half + 1, dtype=np.float32)
        kernel_1d = np.exp(-(x ** 2) / (2 * sigma ** 2))
        kernel_1d /= kernel_1d.sum()

        # Separable convolution: apply row-wise then col-wise.
        # np.pad with 'reflect' to handle borders — same as OpenCV's border
        # default (BORDER_REFLECT_101).
        padded = np.pad(
            gray.astype(np.float32),
            pad_width=half,
            mode="reflect",
        )

        # Row-wise convolution
        row_conv = np.apply_along_axis(
            lambda row: np.convolve(row, kernel_1d, mode="valid"),
            axis=1,
            arr=padded,
        )
        # Column-wise convolution
        col_conv = np.apply_along_axis(
            lambda col: np.convolve(col, kernel_1d, mode="valid"),
            axis=0,
            arr=row_conv,
        )

        # Threshold: pixel > (mean - C) → white (255); else black (0)
        threshold_map = col_conv - float(c_value)
        binary = np.where(
            gray.astype(np.float32) > threshold_map, 255, 0
        ).astype(np.uint8)
        return binary
