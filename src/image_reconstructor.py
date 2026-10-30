#!/usr/bin/env python3
"""
image_reconstructor.py — Measurement-driven Image-to-3D Reconstruction Module
Part of the Blender Headless Universal AI Suite.

Implements the Capybala BPY Measurement & Reconstruction paradigm:
  Stage 0: Image & Silhouette Analysis (Otsu/Adaptive binarization, bbox, aspect ratio)
  Stage 1: Metric Calibration (pixels-to-meters / pixels-to-mm)
  Stage 2: Rotational Half-Profile Extraction (for lathe/revolve geometry)
  Stage 3: Procedural BMesh Reconstruction (clean quads, wall thickness, recessed base)
  Stage 4: Curved Compound Assembly (ergonomic swept handle, mate markers)
"""

from __future__ import annotations

import os
import sys
import math
from typing import List, Tuple, Dict, Any, Optional

try:
    import numpy as np
except ImportError:
    np = None

try:
    from PIL import Image, ImageFilter
except ImportError:
    Image = None

try:
    import bpy
    import bmesh
    from mathutils import Vector, Matrix
except ImportError:
    bpy = None
    bmesh = None
    Vector = None
    Matrix = None


# ------------------------------------------------------------------------------
# Stage 0 & 1: Silhouette Extraction & Calibration (Pure Python / NumPy / PIL)
# ------------------------------------------------------------------------------

def extract_silhouette_and_bbox(
    image_path: str,
    target_max_dim: int = 1024,
    invert: Optional[bool] = None,
    roi: Optional[Tuple[int, int, int, int]] = None
) -> Dict[str, Any]:
    """
    Extracts binary foreground mask and bounding box from a reference image.
    Uses automatic Otsu thresholding and border luminance detection.
    Supports both PIL (workspace Python) and bpy.data.images (Blender internal Python).
    If roi=(xmin, ymin, xmax, ymax) is provided, extracts specifically within that region.
    """
    if np is None:
        raise RuntimeError("NumPy is required for silhouette extraction.")

    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Reference image not found: {image_path}")

    img_arr = None
    if Image is not None:
        with Image.open(image_path) as pil_img:
            w, h = pil_img.size
            if max(w, h) > target_max_dim:
                scale = target_max_dim / float(max(w, h))
                new_w, new_h = int(w * scale), int(h * scale)
                pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
            gray_img = pil_img.convert("L")
            img_arr = np.array(gray_img, dtype=np.uint8)
    elif bpy is not None:
        # Load natively via Blender BPY image datablock
        abs_path = os.path.abspath(image_path)
        b_img = bpy.data.images.load(abs_path)
        w, h = b_img.size[0], b_img.size[1]
        raw_px = np.empty(w * h * 4, dtype=np.float32)
        b_img.pixels.foreach_get(raw_px)
        rgba = raw_px.reshape((h, w, 4))
        # Blender pixels are bottom-up; flip vertically so row 0 is top
        rgba = np.flipud(rgba)
        # Rec. 709 Grayscale conversion
        gray = 0.2126 * rgba[:, :, 0] + 0.7152 * rgba[:, :, 1] + 0.0722 * rgba[:, :, 2]
        img_arr = (gray * 255.0).astype(np.uint8)
        bpy.data.images.remove(b_img)
    else:
        raise RuntimeError("Either Pillow or Blender bpy is required for image extraction.")

    h, w = img_arr.shape
    if roi is not None:
        rx0, ry0, rx1, ry1 = roi
        rx0 = max(0, min(rx0, w - 1))
        rx1 = max(rx0 + 1, min(rx1, w))
        ry0 = max(0, min(ry0, h - 1))
        ry1 = max(ry0 + 1, min(ry1, h))
        img_arr = img_arr[ry0:ry1, rx0:rx1]
        h, w = img_arr.shape

    # Determine background luminance from image borders (10% border margin)
    border_pixels = np.concatenate([
        img_arr[:max(2, h // 20), :].flatten(),
        img_arr[-max(2, h // 20):, :].flatten(),
        img_arr[:, :max(2, w // 20)].flatten(),
        img_arr[:, -max(2, w // 20):].flatten()
    ])
    border_mean = float(np.mean(border_pixels))

    # Otsu thresholding
    hist, bin_edges = np.histogram(img_arr, bins=256, range=(0, 256))
    total = img_arr.size
    current_max, threshold = 0.0, 128
    weight_bg, sum_bg = 0, 0
    sum_total = np.dot(np.arange(256), hist)

    for i in range(256):
        weight_bg += hist[i]
        if weight_bg == 0:
            continue
        weight_fg = total - weight_bg
        if weight_fg == 0:
            break
        sum_bg += i * hist[i]
        mean_bg = sum_bg / weight_bg
        mean_fg = (sum_total - sum_bg) / weight_fg
        var_between = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
        if var_between > current_max:
            current_max = var_between
            threshold = i

    # Robust foreground selection based on border luminance vs threshold
    if invert is None:
        if border_mean < threshold:
            # Background is darker than threshold; foreground is bright
            mask = (img_arr >= threshold)
        else:
            # Background is brighter than threshold; foreground is dark
            mask = (img_arr <= threshold)
    elif invert:
        mask = (img_arr <= threshold)
    else:
        mask = (img_arr >= threshold)

    # Clean isolated noise pixels using simple 3x3 morphology if needed
    # Find bounding box
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)

    if not np.any(rows) or not np.any(cols):
        # Fallback to entire image if mask is empty
        bbox = (0, 0, w, h)
        aspect_ratio = w / float(h)
    else:
        ymin, ymax = np.where(rows)[0][[0, -1]]
        xmin, xmax = np.where(cols)[0][[0, -1]]
        bbox = (int(xmin), int(ymin), int(xmax), int(ymax))
        bbox_w = max(1, xmax - xmin)
        bbox_h = max(1, ymax - ymin)
        aspect_ratio = bbox_w / float(bbox_h)

    return {
        "mask": mask,
        "bbox": bbox,
        "aspect_ratio": aspect_ratio,
        "image_size": (w, h),
        "threshold_used": int(threshold),
        "border_mean_luma": border_mean
    }


def calibrate_scale(
    bbox: Tuple[int, int, int, int],
    real_dimension_m: float,
    axis: str = "height"
) -> Dict[str, float]:
    """
    Calculates conversion ratios between image pixels and real-world meters.
    """
    xmin, ymin, xmax, ymax = bbox
    pixel_w = max(1, xmax - xmin)
    pixel_h = max(1, ymax - ymin)

    ref_pixel = pixel_h if axis == "height" else pixel_w
    pixels_per_meter = float(ref_pixel) / float(real_dimension_m)
    meters_per_pixel = 1.0 / pixels_per_meter

    return {
        "pixels_per_meter": pixels_per_meter,
        "meters_per_pixel": meters_per_pixel,
        "pixel_width": float(pixel_w),
        "pixel_height": float(pixel_h),
        "real_width_m": float(pixel_w * meters_per_pixel),
        "real_height_m": float(pixel_h * meters_per_pixel)
    }


def extract_half_profile_radii(
    mask: np.ndarray,
    bbox: Tuple[int, int, int, int],
    target_height_m: float = 0.095,
    target_radius_m: float = 0.040,
    num_samples: int = 32,
    ignore_handle: bool = True
) -> List[Tuple[float, float]]:
    """
    Extracts a smooth (radius_m, z_m) profile from base to top along the central axis.
    Ideal for rotational lathe / revolve geometry (cups, mugs, bottles, vases).
    """
    xmin, ymin, xmax, ymax = bbox
    center_x = (xmin + xmax) // 2
    bbox_h = max(1, ymax - ymin)

    # In image coordinates, y=ymax is base (Z=0), y=ymin is top (Z=H)
    profile: List[Tuple[float, float]] = []

    # If the object has a handle on one side (e.g. mug), the handle creates asymmetry.
    # We analyze both left and right radius from center. The symmetric cup body has
    # consistent radius on the non-handle side, while the handle extends outward.
    for i in range(num_samples):
        # Sample vertically from base (Z=0) to top (Z=target_height_m)
        t = i / float(num_samples - 1)
        z_m = t * target_height_m
        y_pixel = int(ymax - t * bbox_h)
        y_pixel = min(max(0, y_pixel), mask.shape[0] - 1)

        row = mask[y_pixel, :]
        fg_cols = np.where(row)[0]

        if len(fg_cols) == 0:
            # Fallback to target radius
            r_m = target_radius_m
        else:
            left_edge = fg_cols[0]
            right_edge = fg_cols[-1]

            left_r_px = abs(center_x - left_edge)
            right_r_px = abs(right_edge - center_x)

            if ignore_handle:
                # The smaller radius side is the clean body wall (avoiding the handle protrusion)
                r_px = min(left_r_px, right_r_px)
            else:
                r_px = (left_r_px + right_r_px) / 2.0

            # Scale to meters
            r_m = (r_px / float(bbox_h)) * target_height_m

        profile.append((r_m, z_m))

    # Normalize profile: smooth slight tapering or flare while clamping to realistic bounds
    smoothed_profile: List[Tuple[float, float]] = []
    radii = [p[0] for p in profile]
    # Simple moving average filter (window 3)
    for i in range(len(radii)):
        start_idx = max(0, i - 1)
        end_idx = min(len(radii), i + 2)
        avg_r = sum(radii[start_idx:end_idx]) / float(end_idx - start_idx)
        # Clamp to reasonable fraction of target_radius_m (e.g. 70% to 125%)
        clamped_r = max(target_radius_m * 0.70, min(target_radius_m * 1.25, avg_r))
        smoothed_profile.append((clamped_r, profile[i][1]))

    return smoothed_profile


# ------------------------------------------------------------------------------
# Stage 2 & 3: Procedural BMesh Reconstruction in Blender (Headless)
# ------------------------------------------------------------------------------

def build_revolved_cup_mug(
    profile_points: List[Tuple[float, float]],
    segments: int = 24,
    wall_thickness: float = 0.004,
    base_recess: float = 0.002,
    name: str = "Reconstructed_Mug_Body"
) -> Optional[Any]:
    """
    Constructs a manifold, pure-quad rotational body (mug/cup) in Blender using BMesh.
    Features:
      - Outer wall following profile
      - Inner cavity with uniform wall thickness
      - Recessed bottom base (standard ceramic foot ring)
      - Smooth rounded lip rim
    """
    if bpy is None or bmesh is None:
        print(f"[WARN] Blender environment not detected. Skipping BMesh build for {name}.")
        return None

    mesh = bpy.data.meshes.new(name + "_Mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)

    bm = bmesh.new()

    num_levels = len(profile_points)
    # 1. Outer rings from base (level 0) to rim (level N-1)
    outer_rings: List[List[Any]] = []
    for r_outer, z in profile_points:
        ring = []
        for s in range(segments):
            angle = (2.0 * math.pi * s) / segments
            x = r_outer * math.cos(angle)
            y = r_outer * math.sin(angle)
            v = bm.verts.new((x, y, z))
            ring.append(v)
        outer_rings.append(ring)

    # 2. Inner cavity rings from rim down to interior base
    inner_rings: List[List[Any]] = []
    # Bottom thickness is approx 1.5x wall thickness
    bottom_thickness = wall_thickness * 1.5
    for r_outer, z in reversed(profile_points):
        # Inner radius clamped to not collapse
        r_inner = max(0.005, r_outer - wall_thickness)
        z_inner = max(bottom_thickness, z)
        ring = []
        for s in range(segments):
            angle = (2.0 * math.pi * s) / segments
            x = r_inner * math.cos(angle)
            y = r_inner * math.sin(angle)
            v = bm.verts.new((x, y, z_inner))
            ring.append(v)
        inner_rings.append(ring)

    # 3. Base foot ring (recessed bottom)
    # Central bottom vertex slightly lifted for recessed cavity
    r_base = profile_points[0][0]
    r_foot_inner = max(0.005, r_base - wall_thickness * 1.8)
    foot_inner_ring = []
    for s in range(segments):
        angle = (2.0 * math.pi * s) / segments
        x = r_foot_inner * math.cos(angle)
        y = r_foot_inner * math.sin(angle)
        v = bm.verts.new((x, y, base_recess))
        foot_inner_ring.append(v)

    center_base_v = bm.verts.new((0.0, 0.0, base_recess))

    # Stitch Outer Wall Quads
    for l in range(num_levels - 1):
        r1 = outer_rings[l]
        r2 = outer_rings[l + 1]
        for s in range(segments):
            s_next = (s + 1) % segments
            bm.faces.new([r1[s], r1[s_next], r2[s_next], r2[s]])

    # Stitch Rim Bridge (Lip) between outer top ring and inner top ring
    top_outer = outer_rings[-1]
    top_inner = inner_rings[0]
    for s in range(segments):
        s_next = (s + 1) % segments
        bm.faces.new([top_outer[s], top_inner[s], top_inner[s_next], top_outer[s_next]])

    # Stitch Inner Wall Quads
    for l in range(len(inner_rings) - 1):
        r1 = inner_rings[l]
        r2 = inner_rings[l + 1]
        for s in range(segments):
            s_next = (s + 1) % segments
            bm.faces.new([r1[s], r2[s], r2[s_next], r1[s_next]])

    # Close Interior Bottom Face with central vertex
    bottom_inner = inner_rings[-1]
    center_inner_v = bm.verts.new((0.0, 0.0, bottom_thickness))
    for s in range(segments):
        s_next = (s + 1) % segments
        bm.faces.new([bottom_inner[s], center_inner_v, bottom_inner[s_next]])

    # Stitch Recessed Base Underneath
    bottom_outer = outer_rings[0]
    for s in range(segments):
        s_next = (s + 1) % segments
        bm.faces.new([bottom_outer[s], bottom_outer[s_next], foot_inner_ring[s_next], foot_inner_ring[s]])
        bm.faces.new([foot_inner_ring[s], foot_inner_ring[s_next], center_base_v])

    # Finalize Mesh
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()

    # Set Smooth Shading
    for p in mesh.polygons:
        p.use_smooth = True

    return obj


def build_curved_handle(
    body_radius_top: float,
    body_radius_bottom: float,
    z_top: float = 0.075,
    z_bottom: float = 0.025,
    protrusion: float = 0.035,
    width_radius: float = 0.006,
    thickness_radius: float = 0.0035,
    curve_segments: int = 14,
    ring_segments: int = 8,
    name: str = "Reconstructed_Mug_Handle"
) -> Optional[Any]:
    """
    Constructs an ergonomic curved handle along an arc anchored to the mug body.
    Cross section is an oval quad ring.
    """
    if bpy is None or bmesh is None:
        return None

    mesh = bpy.data.meshes.new(name + "_Mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)

    bm = bmesh.new()

    # Define Bezier-like cubic arc curve points along X-Z plane (handle extends along +X)
    # Anchor points sink slightly into body (-0.0015m) to ensure solid join
    p0 = Vector((body_radius_bottom - 0.0015, 0.0, z_bottom))
    p1 = Vector((body_radius_bottom + protrusion * 1.05, 0.0, z_bottom + 0.008))
    p2 = Vector((body_radius_top + protrusion * 1.10, 0.0, z_top - 0.008))
    p3 = Vector((body_radius_top - 0.0015, 0.0, z_top))

    # Sample cubic Bezier points
    spine_points: List[Vector] = []
    for step in range(curve_segments + 1):
        t = step / float(curve_segments)
        # Cubic bezier formula
        pt = (
            (1 - t)**3 * p0 +
            3 * (1 - t)**2 * t * p1 +
            3 * (1 - t) * t**2 * p2 +
            t**3 * p3
        )
        spine_points.append(pt)

    # For each spine point, generate oriented oval ring
    rings: List[List[Any]] = []
    for i, pt in enumerate(spine_points):
        # Calculate tangent
        if i == 0:
            tangent = (spine_points[1] - spine_points[0]).normalized()
        elif i == len(spine_points) - 1:
            tangent = (spine_points[-1] - spine_points[-2]).normalized()
        else:
            tangent = (spine_points[i + 1] - spine_points[i - 1]).normalized()

        # Normal vector perpendicular to tangent in X-Z plane
        normal = Vector((-tangent.z, 0.0, tangent.x)).normalized()
        binormal = Vector((0.0, 1.0, 0.0))  # along Y axis

        ring_verts = []
        for s in range(ring_segments):
            angle = (2.0 * math.pi * s) / ring_segments
            offset = (
                normal * (thickness_radius * math.cos(angle)) +
                binormal * (width_radius * math.sin(angle))
            )
            v = bm.verts.new(pt + offset)
            ring_verts.append(v)
        rings.append(ring_verts)

    # Stitch Handle Tube Quads
    for step in range(curve_segments):
        r1 = rings[step]
        r2 = rings[step + 1]
        for s in range(ring_segments):
            s_next = (s + 1) % ring_segments
            bm.faces.new([r1[s], r1[s_next], r2[s_next], r2[s]])

    # Close end caps
    end_bottom = rings[0]
    center_b = bm.verts.new(p0)
    for s in range(ring_segments):
        s_next = (s + 1) % ring_segments
        bm.faces.new([end_bottom[s], center_b, end_bottom[s_next]])

    end_top = rings[-1]
    center_t = bm.verts.new(p3)
    for s in range(ring_segments):
        s_next = (s + 1) % ring_segments
        bm.faces.new([end_top[s], end_top[s_next], center_t])

    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()

    for p in mesh.polygons:
        p.use_smooth = True

    return obj


def reconstruct_mug_assembly(
    ref_image_path: Optional[str] = None,
    target_height_m: float = 0.095,
    target_radius_m: float = 0.040,
    segments: int = 24,
    wall_thickness: float = 0.004,
    roi: Optional[Tuple[int, int, int, int]] = None
) -> Dict[str, Any]:
    """
    Orchestrates end-to-end reconstruction from reference image.
    Extracts calibration data, generates body and handle, and sets assembly mate markers.
    """
    calib = {}
    if ref_image_path and os.path.isfile(ref_image_path) and np is not None:
        try:
            sil_data = extract_silhouette_and_bbox(ref_image_path, roi=roi)
            calib = calibrate_scale(sil_data["bbox"], target_height_m, axis="height")
            profile_points = extract_half_profile_radii(
                sil_data["mask"],
                sil_data["bbox"],
                target_height_m=target_height_m,
                target_radius_m=target_radius_m,
                num_samples=24,
                ignore_handle=True
            )
        except Exception as e:
            print(f"[WARN] Failed to extract silhouette from '{ref_image_path}': {e}. Using procedural standard profile.")
            profile_points = [
                (target_radius_m * 0.94, 0.0),
                (target_radius_m * 0.96, target_height_m * 0.25),
                (target_radius_m * 1.00, target_height_m * 0.65),
                (target_radius_m * 1.02, target_height_m * 0.95),
                (target_radius_m * 1.00, target_height_m)
            ]
    else:
        # Standard procedural coffee mug profile
        profile_points = [
            (target_radius_m * 0.94, 0.0),
            (target_radius_m * 0.96, target_height_m * 0.25),
            (target_radius_m * 1.00, target_height_m * 0.65),
            (target_radius_m * 1.02, target_height_m * 0.95),
            (target_radius_m * 1.00, target_height_m)
        ]

    # Build Revolved Body in Blender
    body = build_revolved_cup_mug(
        profile_points=profile_points,
        segments=segments,
        wall_thickness=wall_thickness,
        base_recess=0.002,
        name="Coffee_Mug_Body"
    )

    # Build Curved Handle
    r_top = profile_points[-1][0]
    r_bottom = profile_points[1][0]
    handle = build_curved_handle(
        body_radius_top=r_top,
        body_radius_bottom=r_bottom,
        z_top=target_height_m * 0.82,
        z_bottom=target_height_m * 0.25,
        protrusion=target_radius_m * 0.85,
        name="Coffee_Mug_Handle"
    )

    # Mark Assembly Mate between Handle and Body
    if body and handle:
        handle["_mate_with"] = body.name
        body["_mate_with"] = handle.name

    return {
        "body": body,
        "handle": handle,
        "profile_points": profile_points,
        "calibration": calib
    }
