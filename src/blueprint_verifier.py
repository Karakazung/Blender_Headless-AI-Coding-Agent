#!/usr/bin/env python3
"""
blueprint_verifier.py — Closed-Loop Image-to-3D Verification & Silhouette IoU Auditor
Part of the Blender Headless Universal AI Suite.

Implements Stage 6 / Stage C Visual Closed-Loop Verification:
  1. Silhouette Extraction & Binarization
  2. Bounding Box & Aspect Ratio Concordance
  3. Intersection-over-Union (IoU) Calculation (Scale-Invariant)
  4. Inspection Blueprint Overlay Generation (Green=Match, Red=Render Extra, Blue=Ref Missing)
"""

from __future__ import annotations

import os
import sys
import json
from typing import Dict, Any, Tuple, Optional

try:
    import bpy
except ImportError:
    bpy = None

try:
    import numpy as np
except ImportError:
    np = None

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None

try:
    from .image_reconstructor import extract_silhouette_and_bbox
except ImportError:
    try:
        from image_reconstructor import extract_silhouette_and_bbox
    except ImportError:
        extract_silhouette_and_bbox = None


def normalize_mask_to_canvas(
    mask: np.ndarray,
    bbox: Tuple[int, int, int, int],
    canvas_size: int = 256
) -> np.ndarray:
    """
    Crops the foreground bbox from the mask and resamples it to standard canvas_size x canvas_size.
    Preserves aspect ratio with centered padding. Uses fast pure NumPy resampling.
    """
    if np is None:
        raise RuntimeError("NumPy is required for mask normalization.")

    xmin, ymin, xmax, ymax = bbox
    crop = mask[ymin:ymax+1, xmin:xmax+1]
    ch, cw = crop.shape

    if ch == 0 or cw == 0:
        return np.zeros((canvas_size, canvas_size), dtype=bool)

    # Scale to fit inside canvas with margin (e.g. 16px border)
    max_dim = canvas_size - 16
    scale = max_dim / float(max(cw, ch))
    rw = max(1, int(cw * scale))
    rh = max(1, int(ch * scale))

    # Nearest-neighbor 2D resampling via NumPy index grids
    row_idx = np.linspace(0, ch - 1, rh).astype(int)
    col_idx = np.linspace(0, cw - 1, rw).astype(int)
    resized = crop[row_idx[:, None], col_idx]

    canvas = np.zeros((canvas_size, canvas_size), dtype=bool)
    offset_x = (canvas_size - rw) // 2
    offset_y = (canvas_size - rh) // 2
    canvas[offset_y:offset_y+rh, offset_x:offset_x+rw] = resized
    return canvas


def compute_mask_iou(mask_a: np.ndarray, mask_b: np.ndarray) -> float:
    """
    Computes Intersection-over-Union (IoU) of two binary boolean masks.
    """
    if mask_a.shape != mask_b.shape:
        raise ValueError(f"Shape mismatch: {mask_a.shape} vs {mask_b.shape}")

    intersection = np.logical_and(mask_a, mask_b).sum()
    union = np.logical_or(mask_a, mask_b).sum()

    if union == 0:
        return 1.0 if intersection == 0 else 0.0

    return float(intersection) / float(union)


def audit_silhouette_fidelity(
    render_image_path: str,
    reference_image_path: str,
    iou_target: float = 0.85,
    max_aspect_ratio_diff_pct: float = 12.0,
    roi_reference: Optional[Tuple[int, int, int, int]] = None
) -> Dict[str, Any]:
    """
    Performs closed-loop verification between 3D model render preview and 2D reference image.
    Supports isolating panel via roi_reference=(xmin, ymin, xmax, ymax).
    """
    if extract_silhouette_and_bbox is None:
        raise RuntimeError("extract_silhouette_and_bbox could not be imported.")

    if not os.path.isfile(render_image_path):
        raise FileNotFoundError(f"Render image not found: {render_image_path}")
    if not os.path.isfile(reference_image_path):
        raise FileNotFoundError(f"Reference image not found: {reference_image_path}")

    # 1. Extract silhouettes
    ref_sil = extract_silhouette_and_bbox(reference_image_path, roi=roi_reference)
    render_sil = extract_silhouette_and_bbox(render_image_path)

    # 2. Aspect Ratio Comparison
    ar_ref = ref_sil["aspect_ratio"]
    ar_render = render_sil["aspect_ratio"]
    ar_diff_pct = abs(ar_render - ar_ref) / max(0.001, ar_ref) * 100.0

    # 3. Normalized Canvas IoU
    norm_ref = normalize_mask_to_canvas(ref_sil["mask"], ref_sil["bbox"], canvas_size=256)
    norm_render = normalize_mask_to_canvas(render_sil["mask"], render_sil["bbox"], canvas_size=256)

    iou = compute_mask_iou(norm_ref, norm_render)

    # Evaluate Status
    passed = (iou >= iou_target) and (ar_diff_pct <= max_aspect_ratio_diff_pct)
    if passed:
        status = "PASS"
    elif iou >= iou_target * 0.90:
        status = "WARN_LOW_IOU"
    else:
        status = "FAIL_SILHOUETTE_MISMATCH"

    return {
        "status": status,
        "iou_score": round(iou, 4),
        "target_iou": iou_target,
        "aspect_ratio_reference": round(ar_ref, 4),
        "aspect_ratio_render": round(ar_render, 4),
        "aspect_ratio_diff_pct": round(ar_diff_pct, 2),
        "reference_image": reference_image_path,
        "render_image": render_image_path,
        "verification_passed": passed
    }


def generate_blueprint_overlay(
    render_image_path: str,
    reference_image_path: str,
    output_overlay_path: str,
    roi_reference: Optional[Tuple[int, int, int, int]] = None
) -> str:
    """
    Creates an inspection blueprint composite comparing render vs reference:
      Panel 1: Reference image
      Panel 2: 3D Render preview
      Panel 3: Silhouette Overlap Analysis (Green = Match, Red = Render extra, Blue = Ref missing)
    """
    if Image is None and bpy is None:
        raise RuntimeError("Either Pillow or Blender bpy is required for overlay generation.")

    ref_sil = extract_silhouette_and_bbox(reference_image_path, roi=roi_reference)
    render_sil = extract_silhouette_and_bbox(render_image_path)

    norm_ref = normalize_mask_to_canvas(ref_sil["mask"], ref_sil["bbox"], canvas_size=320)
    norm_render = normalize_mask_to_canvas(render_sil["mask"], render_sil["bbox"], canvas_size=320)

    # Create Overlap RGB visualization
    overlap_rgb = np.zeros((320, 320, 3), dtype=np.uint8)
    # Background: dark slate
    overlap_rgb[:, :] = [25, 30, 38]

    match = np.logical_and(norm_ref, norm_render)
    render_only = np.logical_and(norm_render, ~norm_ref)
    ref_only = np.logical_and(norm_ref, ~norm_render)

    # Green for Match
    overlap_rgb[match] = [46, 204, 113]
    # Coral Red for Render Only
    overlap_rgb[render_only] = [231, 76, 60]
    # Sky Blue for Reference Only
    overlap_rgb[ref_only] = [52, 152, 219]

    if Image is not None:
        overlap_img = Image.fromarray(overlap_rgb, mode="RGB")

        # Load and resize reference & render for side-by-side
        with Image.open(reference_image_path) as ref_im:
            ref_thumb = ref_im.resize((320, 320), Image.Resampling.LANCZOS).convert("RGB")

        with Image.open(render_image_path) as rnd_im:
            rnd_thumb = rnd_im.resize((320, 320), Image.Resampling.LANCZOS).convert("RGB")

        # Composite 3 panels horizontally with title header
        comp_w = 320 * 3 + 40
        comp_h = 320 + 80
        composite = Image.new("RGB", (comp_w, comp_h), (18, 20, 24))

        # Paste panels
        composite.paste(ref_thumb, (10, 60))
        composite.paste(rnd_thumb, (340, 60))
        composite.paste(overlap_img, (670, 60))

        # Draw Text Labels
        draw = ImageDraw.Draw(composite)
        draw.text((10, 15), "STAGE C: BLUEPRINT VERIFICATION & SILHOUETTE ALIGNMENT", fill=(240, 240, 240))
        draw.text((10, 40), "1. Reference Target", fill=(180, 180, 180))
        draw.text((340, 40), "2. 3D Headless Render", fill=(180, 180, 180))
        draw.text((670, 40), "3. Silhouette Overlap (Green=Match, Red=3D, Blue=Ref)", fill=(46, 204, 113))

        os.makedirs(os.path.dirname(os.path.abspath(output_overlay_path)), exist_ok=True)
        composite.save(output_overlay_path)
        return output_overlay_path
    elif bpy is not None:
        # Save overlay natively in Blender without PIL
        abs_out = os.path.abspath(output_overlay_path)
        os.makedirs(os.path.dirname(abs_out), exist_ok=True)
        h, w, c = overlap_rgb.shape
        rgba = np.full((h, w, 4), 1.0, dtype=np.float32)
        rgba[:, :, :3] = np.flipud(overlap_rgb).astype(np.float32) / 255.0
        b_img = bpy.data.images.new("BlueprintOverlay", width=w, height=h, alpha=False)
        b_img.pixels.foreach_set(rgba.flatten())
        b_img.filepath_raw = abs_out
        b_img.file_format = 'PNG'
        b_img.save()
        bpy.data.images.remove(b_img)
        return output_overlay_path
