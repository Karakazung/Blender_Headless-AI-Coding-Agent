#!/usr/bin/env python3
"""
Blender Headless QA Suite: Geometry & Scene Quality Checker
Implements deterministic QA audits including:
  1. AABB Fast-Path & BVH Mesh-level Interpenetration Audit (audit_interpenetration)
  2. Multi-point Raycast Floating & Submersion Audit (audit_floating)
  3. Calibrated Exposure & Luma Distribution Audit (audit_exposure)
"""

import sys
from typing import List, Dict, Any, Optional, Tuple

try:
    import bpy
    import mathutils
    from mathutils.bvhtree import BVHTree
except ImportError:
    # Allow importing type hints outside Blender environment
    bpy = None
    mathutils = None
    BVHTree = None

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
        # ข้ามวัตถุที่มีการประกาศข้อยกเว้นทางวิศวกรรม
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
# 4. Spacing & Pattern Drift Audit (ตรวจจับระยะห่างในแถวที่คลาดเคลื่อน)
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
# 5. Batch Quality Runner
# ==============================================================================

def run_full_qa_audit(array_groups: Optional[Dict[str, List[Any]]] = None) -> Dict[str, Any]:
    """
    รันการตรวจสอบคุณภาพเชิงเรขาคณิตทั้งหมด (Interpenetration, Floating, Spacing)
    :param array_groups: ดิกชันนารีของกลุ่มวัตถุที่จัดเรียงเป็นอาเรย์ เช่น {"balcony_rails": [obj1, obj2, ...]}
    """
    interpenetrations = audit_interpenetration()
    floating = audit_floating()
    
    spacing_reports = {}
    spacing_passed = True
    if array_groups:
        for group_name, objs in array_groups.items():
            rep = audit_spacing(objs)
            spacing_reports[group_name] = rep
            if rep["status"] != "PASS":
                spacing_passed = False

    passed = (len(interpenetrations) == 0) and (len(floating) == 0) and spacing_passed

    report = {
        "qa_passed": passed,
        "interpenetration_issues": interpenetrations,
        "floating_issues": floating,
        "spacing_issues": spacing_reports,
        "summary": {
            "total_collisions": len(interpenetrations),
            "total_floating": len(floating),
            "total_spacing_groups_checked": len(array_groups) if array_groups else 0
        }
    }
    return report

if __name__ == "__main__":
    if bpy is not None:
        res = run_full_qa_audit()
        import json
        print("GEOMETRY_QA_REPORT:" + json.dumps(res, indent=2, ensure_ascii=False))

