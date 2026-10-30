#!/usr/bin/env python3
"""
Blender Headless QA Suite: Geometry, Scene & Exposure Quality Checker
Implements deterministic QA audits based on Capybala BPY engineering standards:
  1. AABB Fast-Path & BVH Mesh-level Interpenetration Audit (audit_interpenetration)
  2. Multi-point Raycast Floating & Submersion Audit (audit_floating)
  3. Surface-gap Attachment Contact Audit (audit_attachment_contact)
  4. Array & Pattern Spacing Drift Audit (audit_spacing)
  5. Calibrated Exposure & Luma Distribution Audit (audit_exposure)
"""

import sys
import os
from typing import List, Dict, Any, Optional, Tuple

try:
    import bpy
    import mathutils
    from mathutils.bvhtree import BVHTree
except ImportError:
    bpy = None
    mathutils = None
    BVHTree = None

try:
    import numpy as np
    from PIL import Image
except ImportError:
    np = None
    Image = None

# ==============================================================================
# Exposure Preset Bands (§10.2 Exposure Standards)
# ==============================================================================

EXPOSURE_PRESET_BANDS: Dict[str, Dict[str, Any]] = {
    "studio": {
        "mean_min": 100.0,
        "mean_max": 170.0,
        "max_clipping_pct": 1.5,
        "max_dark_pct": 35.0,
        "description": "Studio backdrop with 3-point key/fill/rim lighting."
    },
    "outdoor_golden": {
        "mean_min": 95.0,
        "mean_max": 175.0,
        "max_clipping_pct": 2.0,
        "max_dark_pct": 30.0,
        "description": "Natural daytime or golden hour lighting."
    },
    "night": {
        "mean_min": 15.0,
        "mean_max": 70.0,
        "max_clipping_pct": 2.5,
        "max_dark_pct": 55.0,
        "max_mean_median_diff": 18.0,
        "description": "Night scene with focused accent lights and subtle ambient fill."
    },
    "space": {
        "mean_min": 5.0,
        "mean_max": 60.0,
        "max_clipping_pct": 1.5,
        "max_dark_pct": 92.0,
        "description": "High contrast deep space / vacuum lighting."
    }
}

# ==============================================================================
# Helper Tags & Assembly Markers
# ==============================================================================

def mark_assembly_mate(obj_a, obj_b):
    """ทำเครื่องหมายยกเว้นการตรวจสอบการชนสำหรับชิ้นส่วนที่สวมประกบกันตามธรรมชาติ"""
    obj_a["_mate_with"] = obj_b.name
    obj_b["_mate_with"] = obj_a.name

def mark_side_attached(obj, host_obj):
    """ทำเครื่องหมายชิ้นส่วนที่ยึดติดผนัง/ด้านข้างของวัตถุแม่ (เช่น ป้าย, สวิตช์ไฟ)"""
    obj["_side_attached"] = True
    obj["_host_object"] = host_obj.name if hasattr(host_obj, "name") else str(host_obj)

def mark_joint_attached(obj, host_obj):
    """ทำเครื่องหมายชิ้นส่วนข้อต่อ/เพลาหมุนที่ประกบกับวัตถุแม่ (เช่น ลูกปืน, ดุมล้อ)"""
    obj["_joint_attached"] = True
    obj["_host_object"] = host_obj.name if hasattr(host_obj, "name") else str(host_obj)

# ==============================================================================
# 1. Geometry Helpers
# ==============================================================================

def get_world_aabb(obj) -> Tuple[Any, Any]:
    """คำนวณ Axis-Aligned Bounding Box (Min/Max) ในระบบพิกัดโลก (World Space)"""
    bbox_corners = [obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]
    min_coord = mathutils.Vector((
        min(c.x for c in bbox_corners),
        min(c.y for c in bbox_corners),
        min(c.z for c in bbox_corners)
    ))
    max_coord = mathutils.Vector((
        max(c.x for c in bbox_corners),
        max(c.y for c in bbox_corners),
        max(c.z for c in bbox_corners)
    ))
    return min_coord, max_coord

def aabb_intersect(min_a, max_a, min_b, max_b, tolerance: float = 1e-4) -> bool:
    """AABB Fast-path: ตรวจสอบการทับซ้อนของ Bounding Box ในพิกัด 3 มิติ"""
    return (
        (min_a.x <= max_b.x - tolerance and max_a.x >= min_b.x + tolerance) and
        (min_a.y <= max_b.y - tolerance and max_a.y >= min_b.y + tolerance) and
        (min_a.z <= max_b.z - tolerance and max_a.z >= min_b.z + tolerance)
    )

def get_base_probe_points(obj, probe_offset: float = 0.005) -> Tuple[List[Any], float]:
    """
    คำนวณจุดตรวจสอบ 5 จุดใต้ฐานวัตถุ (จุดกึ่งกลางฐานล่าง + 4 มุมฐาน)
    ยกขึ้นเล็กน้อยตามระยะ probe_offset เพื่อเป็นจุดเริ่มต้นยิง Raycast ลงพื้น
    """
    matrix = obj.matrix_world
    bbox = [matrix @ mathutils.Vector(corner) for corner in obj.bound_box]
    
    min_z = min(c.z for c in bbox)
    min_x = min(c.x for c in bbox)
    max_x = max(c.x for c in bbox)
    min_y = min(c.y for c in bbox)
    max_y = max(c.y for c in bbox)
    
    center_base = mathutils.Vector(((min_x + max_x) / 2.0, (min_y + max_y) / 2.0, min_z))
    
    probe_points = [
        center_base + mathutils.Vector((0, 0, probe_offset)),
        mathutils.Vector((min_x, min_y, min_z + probe_offset)),
        mathutils.Vector((max_x, min_y, min_z + probe_offset)),
        mathutils.Vector((min_x, max_y, min_z + probe_offset)),
        mathutils.Vector((max_x, max_y, min_z + probe_offset)),
    ]
    return probe_points, min_z

# ==============================================================================
# 2. Interpenetration Audit (ตรวจการชนกันของวัตถุจริง)
# ==============================================================================

def audit_interpenetration(
    objects: Optional[List[Any]] = None,
    use_bvh_refinement: bool = True,
    tolerance: float = 0.001
) -> List[Dict[str, Any]]:
    """
    ตรวจสอบการซ้อนทับกันของวัตถุ Mesh (AABB Fast-path -> BVH Mesh-level Mode)
    :param objects: รายการวัตถุที่ต้องการตรวจสอบ (หากเป็น None จะนำเข้า Mesh ทั้งหมดในฉาก)
    :param use_bvh_refinement: ตรวจสอบความถูกต้องระดับโพลีกอนด้วย BVHTree
    :param tolerance: พิกัดความเผื่อขั้นต่ำ (หน่วยเมตร)
    """
    if bpy is None:
        raise RuntimeError("Blender bpy module is required to execute audit_interpenetration.")

    if objects is None:
        objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    
    depsgraph = bpy.context.evaluated_depsgraph_get()
    interpenetrations = []
    
    for i in range(len(objects)):
        obj_a = objects[i]
        min_a, max_a = get_world_aabb(obj_a)
        
        for j in range(i + 1, len(objects)):
            obj_b = objects[j]
            
            # ตรวจสอบข้อยกเว้นการประกอบกันโดยตั้งใจ (Assembly Mate)
            if obj_a.get("_mate_with") == obj_b.name or obj_b.get("_mate_with") == obj_a.name:
                continue

            min_b, max_b = get_world_aabb(obj_b)
            
            # 1. AABB Fast-Path Check
            if not aabb_intersect(min_a, max_a, min_b, max_b, tolerance):
                continue
                
            # 2. BVH Mesh-Level Check (เมื่อ AABB ซ้อนทับกัน)
            if use_bvh_refinement:
                bvh_a = BVHTree.FromObject(obj_a, depsgraph)
                bvh_b = BVHTree.FromObject(obj_b, depsgraph)
                
                overlap_pairs = bvh_a.overlap(bvh_b)
                if overlap_pairs:
                    interpenetrations.append({
                        "object_a": obj_a.name,
                        "object_b": obj_b.name,
                        "overlap_count": len(overlap_pairs),
                        "status": "FAIL_BVH_INTERSECT"
                    })
            else:
                interpenetrations.append({
                    "object_a": obj_a.name,
                    "object_b": obj_b.name,
                    "status": "FAIL_AABB_OVERLAP"
                })

    return interpenetrations

# ==============================================================================
# 3. Floating & Submersion Audit (ตรวจหาวัตถุลอยหรือจมดิน)
# ==============================================================================

def audit_floating(
    objects: Optional[List[Any]] = None,
    ground_objects: Optional[List[Any]] = None,
    max_gap: float = 0.005,
    max_sink: float = -0.002
) -> List[Dict[str, Any]]:
    """
    ตรวจสอบวัตถุลอยกลางอากาศ หรือจมดินเกินพิกัดความเผื่อ
    :param objects: รายการวัตถุที่ต้องการตรวจสอบ (Mesh)
    :param ground_objects: วัตถุที่ถือเป็นฐานรองรับ (หาก None จะคำนวณจาก Mesh อื่นทั้งหมด)
    :param max_gap: ระยะห่างสูงสุดที่ยอมรับได้ (ค่าบวก = ลอย) ค่าเริ่มต้น 5 มม.
    :param max_sink: ระยะจมลึกสูงสุดที่ยอมรับได้ (ค่าลบ = จมดิน) ค่าเริ่มต้น -2 มม.
    """
    if bpy is None:
        raise RuntimeError("Blender bpy module is required to execute audit_floating.")

    depsgraph = bpy.context.evaluated_depsgraph_get()
    
    if objects is None:
        objects = [o for o in bpy.context.scene.objects if o.type == 'MESH']
        
    floating_issues = []
    ray_dir = mathutils.Vector((0, 0, -1.0))
    probe_offset = 0.005
    
    for obj in objects:
        # ข้ามวัตถุที่ยึดติดด้านข้าง/ข้อต่อ (ตรวจสอบแยกใน audit_attachment_contact)
        if obj.get("_side_attached", False) or obj.get("_joint_attached", False):
            continue
            
        # ข้ามวัตถุประเภทพื้นดินหรือบรรยากาศ
        if any(token in obj.name for token in ("Ground", "Terrain", "Void", "Floor")):
            continue

        probe_points, min_z = get_base_probe_points(obj, probe_offset=probe_offset)
        
        potential_supports = ground_objects if ground_objects else [
            o for o in bpy.context.scene.objects 
            if o.type == 'MESH' and o != obj and (o.matrix_world.translation.z <= min_z + 0.1)
        ]
        
        if not potential_supports:
            if min_z > max_gap:
                floating_issues.append({
                    "object": obj.name,
                    "measured_base_z": round(min_z, 4),
                    "status": "FAIL_FLOATING_IN_VACUUM"
                })
            continue

        best_hit_dist = float("inf")

        for support in potential_supports:
            bvh = BVHTree.FromObject(support, depsgraph)
            inv_matrix = support.matrix_world.inverted()
            
            for probe in probe_points:
                local_origin = inv_matrix @ probe
                local_dir = inv_matrix.to_3x3() @ ray_dir
                
                loc, normal, index, dist = bvh.ray_cast(local_origin, local_dir)
                if loc is not None:
                    world_hit = support.matrix_world @ loc
                    gap = probe.z - world_hit.z - probe_offset
                    if abs(gap) < abs(best_hit_dist):
                        best_hit_dist = gap

        if best_hit_dist == float("inf") and min_z > max_gap:
            floating_issues.append({
                "object": obj.name,
                "measured_base_z": round(min_z, 4),
                "status": "FAIL_NO_SUPPORT_FOUND"
            })
        elif best_hit_dist > max_gap:
            floating_issues.append({
                "object": obj.name,
                "measured_gap_meters": round(best_hit_dist, 4),
                "status": "FAIL_FLOATING_GAP_EXCEEDED"
            })
        elif best_hit_dist < max_sink:
            floating_issues.append({
                "object": obj.name,
                "measured_sink_meters": round(best_hit_dist, 4),
                "status": "FAIL_SUBMERGED_TOO_DEEP"
            })

    return floating_issues

# ==============================================================================
# 4. Attachment Contact Audit (§13.9 Attachment Contact Audit)
# ==============================================================================

def audit_attachment_contact(
    objects: Optional[List[Any]] = None,
    max_gap: float = 0.005
) -> List[Dict[str, Any]]:
    """
    ตรวจสอบระยะแนบสนิท (Surface-gap check) ของชิ้นส่วนที่ติดกับวัตถุแม่
    (สำหรับวัตถุที่ติดป้าย _side_attached หรือ _joint_attached)
    :param objects: รายการวัตถุที่ต้องการตรวจสอบ (หาก None จะตรวจค้นวัตถุที่มี Tag ทั้งหมดในฉาก)
    :param max_gap: ระยะห่างสูงสุดที่ยอมรับได้ (เมตร) ค่าเริ่มต้น 5 มม.
    """
    if bpy is None:
        raise RuntimeError("Blender bpy module is required to execute audit_attachment_contact.")

    depsgraph = bpy.context.evaluated_depsgraph_get()
    
    if objects is None:
        objects = [
            o for o in bpy.context.scene.objects 
            if o.type == 'MESH' and (o.get("_side_attached", False) or o.get("_joint_attached", False))
        ]

    attachment_issues = []

    for obj in objects:
        host_name = obj.get("_host_object")
        if not host_name:
            attachment_issues.append({
                "object": obj.name,
                "status": "FAIL_MISSING_HOST_REFERENCE",
                "message": "Object is marked attached but has no _host_object defined"
            })
            continue

        host_obj = bpy.data.objects.get(host_name)
        if not host_obj:
            attachment_issues.append({
                "object": obj.name,
                "host": host_name,
                "status": "FAIL_HOST_NOT_FOUND"
            })
            continue

        # ยิง Raycast ระหว่างจุดกึ่งกลางของ Bounding box ของวัตถุ ไปยัง Bounding box ของ Host
        obj_center = obj.matrix_world.translation
        host_center = host_obj.matrix_world.translation
        ray_dir = (host_center - obj_center).normalized()
        
        # Raycast เข้าหาพื้นผิว Host Mesh ด้วย BVHTree
        bvh_host = BVHTree.FromObject(host_obj, depsgraph)
        inv_matrix_host = host_obj.matrix_world.inverted()
        local_origin = inv_matrix_host @ obj_center
        local_dir = inv_matrix_host.to_3x3() @ ray_dir
        
        loc, normal, index, dist = bvh_host.ray_cast(local_origin, local_dir)
        
        if loc is not None:
            world_hit = host_obj.matrix_world @ loc
            # คำนวณระยะห่างผิวสัมผัสขั้นต่ำ
            # หักลบด้วยขอบเขตวัตถุตัวมันเองคร่าวๆ ตามแนวรัศมี
            obj_min, obj_max = get_world_aabb(obj)
            approx_radius = (obj_max - obj_min).length / 2.0
            surface_gap = max(0.0, (world_hit - obj_center).length - approx_radius)

            if surface_gap > max_gap:
                attachment_issues.append({
                    "object": obj.name,
                    "host": host_name,
                    "measured_surface_gap": round(surface_gap, 4),
                    "allowed_max_gap": max_gap,
                    "status": "FAIL_ATTACHMENT_GAP_EXCEEDED"
                })
        else:
            # ตรวจสอบ AABB Distance สำรอง
            min_a, max_a = get_world_aabb(obj)
            min_b, max_b = get_world_aabb(host_obj)
            if not aabb_intersect(min_a, max_a, min_b, max_b, tolerance=max_gap):
                attachment_issues.append({
                    "object": obj.name,
                    "host": host_name,
                    "status": "FAIL_NO_CONTACT_RAY_HIT"
                })

    return attachment_issues

# ==============================================================================
# 5. Spacing & Pattern Drift Audit (ตรวจจับระยะห่างในแถวที่คลาดเคลื่อน)
# ==============================================================================

def audit_spacing(
    object_group: List[Any],
    expected_axis: str = 'X',
    tolerance_ratio: float = 0.05,
    min_drift_threshold: float = 0.001
) -> Dict[str, Any]:
    """
    ตรวจสอบระยะห่างของแถววัตถุ (Array/Pattern) ว่าเท่ากันอย่างสม่ำเสมอหรือไม่
    :param object_group: รายชื่อวัตถุในแถวเดียวกัน
    :param expected_axis: แกนหลักของการเรียงตัว ('X', 'Y', หรือ 'Z')
    :param tolerance_ratio: อัตราส่วนความคลาดเคลื่อนที่ยอมรับได้ (เช่น 0.05 = 5% ของระยะมัธยฐาน)
    :param min_drift_threshold: เกณฑ์คลาดเคลื่อนขั้นต่ำเป็นเมตร (สำหรับวัตถุขนาดเล็ก ป้องกันเกณฑ์เข้มงวดเกินไป)
    """
    if len(object_group) < 3:
        return {
            "status": "PASS",
            "message": "ชิ้นส่วนน้อยกว่า 3 ชิ้น ไม่ต้องตรวจวัด Pattern สม่ำเสมอ"
        }

    # 1. เรียงลำดับวัตถุตามแกนหลักที่กำหนด
    axis_idx = {'X': 0, 'Y': 1, 'Z': 2}.get(expected_axis.upper(), 0)
    sorted_objs = sorted(object_group, key=lambda o: o.matrix_world.translation[axis_idx])

    # 2. คำนวณระยะห่างระหว่างวัตถุที่อยู่ติดกันทีละคู่
    spacings = []
    for i in range(len(sorted_objs) - 1):
        p1 = sorted_objs[i].matrix_world.translation
        p2 = sorted_objs[i+1].matrix_world.translation
        dist = (p2 - p1).length
        spacings.append((sorted_objs[i].name, sorted_objs[i+1].name, dist))

    # 3. คำนวณค่ามัธยฐาน (Median Spacing) เพื่อใช้เป็นเกณฑ์อ้างอิง
    distances = [s[2] for s in spacings]
    sorted_distances = sorted(distances)
    median_spacing = sorted_distances[len(sorted_distances) // 2]

    # คำนวณ Adaptive Tolerance
    allowed_drift = max(median_spacing * tolerance_ratio, min_drift_threshold)

    drifted_items = []
    for obj_a, obj_b, dist in spacings:
        diff = abs(dist - median_spacing)
        if diff > allowed_drift:
            drifted_items.append({
                "pair": (obj_a, obj_b),
                "measured_distance": round(dist, 4),
                "expected_distance": round(median_spacing, 4),
                "diff": round(diff, 4),
                "allowed_drift": round(allowed_drift, 4)
            })

    # 4. รายงานผลลัพธ์
    if drifted_items:
        return {
            "status": "FAIL_SPACING_DRIFT",
            "median_spacing": round(median_spacing, 4),
            "drift_count": len(drifted_items),
            "details": drifted_items
        }

    return {
        "status": "PASS",
        "median_spacing": round(median_spacing, 4),
        "total_checked_pairs": len(spacings)
    }

# ==============================================================================
# 6. Exposure & Luma Distribution Audit (§10.2 Calibrated Luma Bands)
# ==============================================================================

def compute_luma_from_rgb(rgb_array: Any) -> Any:
    """
    คำนวณค่า Luma (ความสว่าง) จากช่องสี RGB ตามมาตรฐาน Rec. 709
    Y = 0.2126 * R + 0.7152 * G + 0.0722 * B
    """
    if np is None:
        raise RuntimeError("numpy module is required to compute luma statistics.")
    
    # rgb_array should be shaped (..., 3) in range [0, 255]
    weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    return np.tensordot(rgb_array[..., :3], weights, axes=([ -1 ], [ 0 ]))

def audit_exposure(
    image_filepath: str,
    preset: str = "studio",
    custom_band: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    ตรวจสอบค่าการรับแสงและการกระจายตัวของ Luma จากภาพเรนเดอร์เทียบกับพรีเซ็ต
    :param image_filepath: เส้นทางไฟล์ภาพเรนเดอร์ (.png, .jpg, .exr)
    :param preset: พรีเซ็ตแสงเป้าหมาย ('studio', 'outdoor_golden', 'night', 'space')
    :param custom_band: กำหนดช่วงความสว่างเฉพาะกิจ (ถ้ามี)
    """
    if preset not in EXPOSURE_PRESET_BANDS and custom_band is None:
        raise ValueError(f"Unknown preset: '{preset}'. Available: {list(EXPOSURE_PRESET_BANDS.keys())}")

    band = custom_band if custom_band else EXPOSURE_PRESET_BANDS[preset]

    # โหลดพิกเซลภาพ
    rgb_data = None
    if bpy is not None:
        try:
            img = bpy.data.images.load(image_filepath)
            width, height = img.size
            total_pixels = width * height
            raw_pixels = np.empty(total_pixels * img.channels, dtype=np.float32)
            img.pixels.foreach_get(raw_pixels)
            raw_pixels = raw_pixels.reshape((height, width, img.channels))
            # สเกลเป็น [0, 255]
            rgb_data = (raw_pixels[:, :, :3] * 255.0).clip(0, 255)
            # เคลียร์หน่วยความจำภาพใน bpy
            bpy.data.images.remove(img)
        except Exception:
            rgb_data = None

    # สแตนด์อโลน fallback โหลดผ่าน PIL
    if rgb_data is None:
        if not os.path.exists(image_filepath):
            raise FileNotFoundError(f"Rendered image file not found: {image_filepath}")
        if Image is None or np is None:
            raise RuntimeError("PIL (Pillow) and numpy are required to audit exposure outside Blender.")
        img = Image.open(image_filepath).convert("RGB")
        rgb_data = np.array(img, dtype=np.float32)

    luma = compute_luma_from_rgb(rgb_data)
    total_pixels = luma.size

    mean_luma = float(np.mean(luma))
    median_luma = float(np.median(luma))
    min_luma = float(np.min(luma))
    max_luma = float(np.max(luma))

    # คำนวณร้อยละของพื้นที่ตัดยอด (Clipping >= 250) และพื้นที่มืดสนิท (Dark <= 15)
    clipping_count = int(np.count_nonzero(luma >= 250.0))
    dark_count = int(np.count_nonzero(luma <= 15.0))

    clipping_pct = (clipping_count / total_pixels) * 100.0
    dark_pct = (dark_count / total_pixels) * 100.0

    issues = []
    recommendations = []

    # 1. ตรวจสอบ Mean Luma ให้อยู่ในช่วงมาตรฐาน
    mean_min = band["mean_min"]
    mean_max = band["mean_max"]
    if mean_luma < mean_min:
        issues.append(f"UNDER_EXPOSED: Mean luma {mean_luma:.1f} is below minimum {mean_min:.1f}")
        recommendations.append("Increase Key Light wattage or adjust camera exposure/ISO.")
    elif mean_luma > mean_max:
        issues.append(f"OVER_EXPOSED: Mean luma {mean_luma:.1f} exceeds maximum {mean_max:.1f}")
        recommendations.append("Reduce Key/Fill Light power or increase camera F-stop.")

    # 2. ตรวจสอบพื้นที่ตัดยอด (Clipping)
    max_clipping = band.get("max_clipping_pct", 1.5)
    if clipping_pct > max_clipping:
        issues.append(f"SPECULAR_BURNOUT: Clipping {clipping_pct:.2f}% exceeds limit {max_clipping:.2f}%")
        recommendations.append("Dim bright area lamps or reduce specular roughness on blown-out materials.")

    # 3. ตรวจสอบพื้นที่มืดทึบ (Crushed Blacks)
    max_dark = band.get("max_dark_pct", 35.0)
    if dark_pct > max_dark:
        issues.append(f"EXCESSIVE_DARKNESS: Dark area {dark_pct:.1f}% exceeds limit {max_dark:.1f}%")
        recommendations.append("Add subtle Fill light or increase ambient bounce.")

    # 4. ตรวจสอบ Hotspot Drift สำหรับฉากกลางคืน (§10.2 กฎเหล็กข้อ 4)
    if preset == "night":
        max_diff = band.get("max_mean_median_diff", 18.0)
        diff = abs(mean_luma - median_luma)
        if diff > max_diff and dark_pct > 40.0:
            issues.append(f"HOTSPOT_DRIFT: |Mean - Median| is {diff:.1f} (> {max_diff:.1f}) with {dark_pct:.1f}% dark pixels")
            recommendations.append("Scene is dominated by tiny intense pinpoint lights. Call auto_night_fill() to add low ambient scene illumination.")

    status = "PASS" if len(issues) == 0 else "FAIL_EXPOSURE_DRIFT"

    return {
        "status": status,
        "preset": preset,
        "mean_luma": round(mean_luma, 2),
        "median_luma": round(median_luma, 2),
        "min_luma": round(min_luma, 2),
        "max_luma": round(max_luma, 2),
        "clipping_pct": round(clipping_pct, 2),
        "dark_pct": round(dark_pct, 2),
        "target_band": {
            "mean_min": mean_min,
            "mean_max": mean_max,
            "max_clipping_pct": max_clipping,
            "max_dark_pct": max_dark
        },
        "issues": issues,
        "recommendations": recommendations
    }

# ==============================================================================
# 7. Comprehensive Master QA Runner
# ==============================================================================

def run_full_qa_audit(
    render_image_path: Optional[str] = None,
    preset: str = "studio",
    array_groups: Optional[Dict[str, List[Any]]] = None
) -> Dict[str, Any]:
    """
    รันการตรวจสอบคุณภาพรอบด้าน (Geometry, Attachment, Spacing, Exposure)
    :param render_image_path: เส้นทางรูปภาพเรนเดอร์สำหรับการตรวจสอบแสง (Optional)
    :param preset: พรีเซ็ตการจัดแสงสำหรับการตรวจสอบ Luma ('studio', 'outdoor_golden', 'night', 'space')
    :param array_groups: ดิกชันนารีของกลุ่มวัตถุที่จัดเรียงเป็นอาเรย์
    """
    interpenetrations = []
    floating = []
    attachments = []

    if bpy is not None:
        interpenetrations = audit_interpenetration()
        floating = audit_floating()
        attachments = audit_attachment_contact()
    
    spacing_reports = {}
    spacing_passed = True
    if array_groups:
        for group_name, objs in array_groups.items():
            rep = audit_spacing(objs)
            spacing_reports[group_name] = rep
            if rep["status"] != "PASS":
                spacing_passed = False

    exposure_report = None
    exposure_passed = True
    if render_image_path:
        exposure_report = audit_exposure(render_image_path, preset=preset)
        if exposure_report["status"] != "PASS":
            exposure_passed = False

    passed = (
        (len(interpenetrations) == 0) and 
        (len(floating) == 0) and 
        (len(attachments) == 0) and 
        spacing_passed and 
        exposure_passed
    )

    report = {
        "qa_passed": passed,
        "interpenetration_issues": interpenetrations,
        "floating_issues": floating,
        "attachment_issues": attachments,
        "spacing_issues": spacing_reports,
        "exposure_audit": exposure_report,
        "summary": {
            "total_collisions": len(interpenetrations),
            "total_floating": len(floating),
            "total_attachment_issues": len(attachments),
            "total_spacing_groups_checked": len(array_groups) if array_groups else 0,
            "exposure_audited": render_image_path is not None
        }
    }
    return report

if __name__ == "__main__":
    if bpy is not None:
        res = run_full_qa_audit()
        import json
        print("GEOMETRY_QA_REPORT:" + json.dumps(res, indent=2, ensure_ascii=False))
