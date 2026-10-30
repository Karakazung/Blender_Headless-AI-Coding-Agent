#!/usr/bin/env python3
"""
Blender Headless QA Suite: Universal Multi-Genre Quality Checker
Implements comprehensive deterministic QA audits based on Capybala BPY engineering standards:
  1. Polycount Budget & LOD Audit (audit_polycount)
  2. Transform & Pivot Grounding Audit (audit_transforms)
  3. Mesh Topology & Manifold Audit (audit_mesh_topology)
  4. Material & glTF 2.0 Export Safety (audit_materials_compatibility)
  5. AABB Fast-Path & BVH Mesh-level Interpenetration (audit_interpenetration)
  6. Multi-point Raycast Floating & Submersion (audit_floating)
  7. Surface-gap Attachment Contact (audit_attachment_contact)
  8. Array & Pattern Spacing Drift (audit_spacing)
  9. Calibrated Exposure & Luma Distribution (audit_exposure)
  10. Headless glTF/GLB Export Verification (audit_glb_export)
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
except ImportError:
    np = None

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    from .profile_loader import load_profile
    from .shader_generator import audit_material_nodes
except ImportError:
    try:
        from profile_loader import load_profile
        from shader_generator import audit_material_nodes
    except ImportError:
        load_profile = None
        audit_material_nodes = None

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
    obj_a["_mate_with"] = obj_b.name if hasattr(obj_b, "name") else str(obj_b)
    obj_b["_mate_with"] = obj_a.name if hasattr(obj_a, "name") else str(obj_a)

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
    if hasattr(obj, "_custom_aabb") and obj._custom_aabb is not None:
        return obj._custom_aabb
    if mathutils is not None and hasattr(obj, "matrix_world") and hasattr(obj, "bound_box"):
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
    raise ValueError(f"Object {obj} does not support world AABB calculation.")

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
# 2. Polycount Budget & LOD Audit
# ==============================================================================

def audit_polycount(
    objects: Optional[List[Any]] = None,
    profile: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    ตรวจสอบจำนวนโพลีกอน (Triangles / Vertices) เทียบกับงบประมาณของ Profile
    """
    if objects is None:
        if bpy is not None:
            objects = [o for o in bpy.context.scene.objects if o.type == 'MESH']
        else:
            objects = []

    total_tris = 0
    total_verts = 0
    total_faces = 0
    breakdown = []

    if bpy is not None:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        for obj in objects:
            try:
                eval_obj = obj.evaluated_get(depsgraph)
                eval_mesh = eval_obj.to_mesh()
                eval_mesh.calc_loop_triangles()
                tris = len(eval_mesh.loop_triangles)
                verts = len(eval_mesh.vertices)
                faces = len(eval_mesh.polygons)
                eval_obj.to_mesh_clear()
            except Exception:
                tris = len(obj.data.polygons) * 2 if hasattr(obj, "data") and hasattr(obj.data, "polygons") else 0
                verts = len(obj.data.vertices) if hasattr(obj, "data") and hasattr(obj.data, "vertices") else 0
                faces = len(obj.data.polygons) if hasattr(obj, "data") and hasattr(obj.data, "polygons") else 0

            total_tris += tris
            total_verts += verts
            total_faces += faces
            breakdown.append({"object": obj.name, "tris": tris, "verts": verts, "faces": faces})
    else:
        # Fallback / Mock environment
        for obj in objects:
            tris = getattr(obj, "tris_count", 0)
            verts = getattr(obj, "verts_count", 0)
            faces = getattr(obj, "faces_count", 0)
            if hasattr(obj, "data"):
                if hasattr(obj.data, "polygons"):
                    faces = len(obj.data.polygons)
                    tris = sum(max(1, len(p.vertices) - 2) for p in obj.data.polygons)
                if hasattr(obj.data, "vertices"):
                    verts = len(obj.data.vertices)

            total_tris += tris
            total_verts += verts
            total_faces += faces
            breakdown.append({"object": getattr(obj, "name", "unknown"), "tris": tris, "verts": verts, "faces": faces})

    budget = profile.get("polycount_budget", {}) if profile else {}
    target_tris = budget.get("target_tris", 1000)
    max_tris = budget.get("max_tris", 2500)

    status = "PASS"
    issues = []
    if total_tris > max_tris:
        status = "FAIL_POLYCOUNT_EXCEEDED"
        issues.append(f"Total tris {total_tris} exceeds maximum allowed {max_tris} in profile.")
    elif total_tris > target_tris:
        status = "WARN_ABOVE_TARGET_TRIS"

    return {
        "status": status,
        "total_tris": total_tris,
        "total_verts": total_verts,
        "total_faces": total_faces,
        "target_tris": target_tris,
        "max_tris": max_tris,
        "issues": issues,
        "breakdown": breakdown
    }

# ==============================================================================
# 3. Transform & Pivot Grounding Audit
# ==============================================================================

def audit_transforms(
    objects: Optional[List[Any]] = None,
    profile: Optional[Dict[str, Any]] = None,
    scale_tolerance: float = 1e-4
) -> List[Dict[str, Any]]:
    """
    ตรวจสอบความถูกต้องของ Transform (Scale ต้องเป็น 1.0, Origin และการแนบพื้น)
    """
    if objects is None:
        if bpy is not None:
            objects = [o for o in bpy.context.scene.objects if o.type == 'MESH']
        else:
            objects = []

    grounding_cfg = profile.get("grounding", {}) if profile else {}
    enforce_base = grounding_cfg.get("enforce_pivot_base", True)
    target_min_z = grounding_cfg.get("target_min_z", 0.0)
    z_tolerance = grounding_cfg.get("z_tolerance", 0.005)

    issues = []

    for obj in objects:
        # 1. ตรวจสอบ Unapplied Scale
        if hasattr(obj, "scale"):
            scale = obj.scale
            if (abs(scale[0] - 1.0) > scale_tolerance or 
                abs(scale[1] - 1.0) > scale_tolerance or 
                abs(scale[2] - 1.0) > scale_tolerance):
                issues.append({
                    "object": obj.name,
                    "status": "FAIL_UNAPPLIED_SCALE",
                    "measured_scale": (round(scale[0], 4), round(scale[1], 4), round(scale[2], 4)),
                    "message": "Object scale is not applied (1.0, 1.0, 1.0)."
                })

        # 2. ตรวจสอบการแนบระนาบพื้นฐานล่าง (Z=0 Grounding)
        if enforce_base:
            # ข้ามวัตถุที่เป็นพื้นดิน, มี Parent หรือเป็นชิ้นส่วนย่อยใน Hierarchy
            if (obj.get("_side_attached") or 
                obj.get("_joint_attached") or 
                obj.get("_mate_with") or 
                getattr(obj, "parent", None) is not None or 
                "Floor" in obj.name or 
                "Ground" in obj.name):
                continue

            try:
                min_coord, _ = get_world_aabb(obj)
                diff = abs(min_coord.z - target_min_z)
                if diff > z_tolerance:
                    issues.append({
                        "object": obj.name,
                        "status": "FAIL_BASE_OFF_GROUND",
                        "measured_min_z": round(min_coord.z, 4),
                        "target_min_z": target_min_z,
                        "diff": round(diff, 4),
                        "allowed_tolerance": z_tolerance,
                        "message": f"Object base min Z is {min_coord.z:.4f}m, expected {target_min_z:.4f}m."
                    })
            except Exception:
                pass

    return issues

# ==============================================================================
# 4. Mesh Topology & Manifold Audit
# ==============================================================================

def audit_mesh_topology(objects: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
    """
    ตรวจสอบสุขอนามัยของ Mesh (Non-manifold edges, Loose vertices)
    """
    if bpy is None:
        return []

    try:
        import bmesh
    except ImportError:
        return []

    if objects is None:
        objects = [o for o in bpy.context.scene.objects if o.type == 'MESH']

    topology_issues = []
    for obj in objects:
        mesh = obj.data
        if not hasattr(mesh, "vertices") or len(mesh.vertices) == 0:
            continue

        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            bm.edges.ensure_lookup_table()
            non_manifold_count = sum(1 for e in bm.edges if not e.is_manifold)
            loose_edge_count = sum(1 for e in bm.edges if len(e.link_faces) == 0)
        except Exception:
            non_manifold_count = 0
            loose_edge_count = 0
        finally:
            bm.free()

        if non_manifold_count > 0:
            topology_issues.append({
                "object": obj.name,
                "status": "WARN_NON_MANIFOLD_EDGES",
                "non_manifold_edges": non_manifold_count,
                "message": f"Found {non_manifold_count} non-manifold edges. Check for internal faces."
            })

        if loose_edge_count > 0:
            topology_issues.append({
                "object": obj.name,
                "status": "WARN_LOOSE_EDGES",
                "loose_edges": loose_edge_count,
                "message": f"Found {loose_edge_count} loose edges without attached faces."
            })

    return topology_issues

# ==============================================================================
# 5. Material & glTF Compatibility Audit
# ==============================================================================

def audit_materials_compatibility(objects: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
    """
    ตรวจสอบวัสดุในฉากว่ารองรับการ Export ไปยัง glTF 2.0 / Godot 4.x หรือไม่
    """
    if audit_material_nodes is None:
        return []

    if objects is None and bpy is not None:
        objects = [o for o in bpy.context.scene.objects if o.type == 'MESH']

    material_reports = []
    checked_materials = set()

    for obj in (objects or []):
        mat_slots = getattr(obj, "material_slots", [])
        for slot in mat_slots:
            mat = slot.material
            if mat and mat.name not in checked_materials:
                checked_materials.add(mat.name)
                rep = audit_material_nodes(mat)
                if not rep["compatible"]:
                    material_reports.append(rep)

    return material_reports

# ==============================================================================
# 6. Interpenetration Audit (ตรวจการชนกันของวัตถุจริง)
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
            
            # ข้ามการตรวจสอบการชนกับพื้นดินหรือระนาบรองรับ
            if any(k in obj_a.name for k in ("Ground", "Floor", "Terrain")) or any(k in obj_b.name for k in ("Ground", "Floor", "Terrain")):
                continue

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
# 7. Floating & Submersion Audit (ตรวจหาวัตถุลอยหรือจมดิน)
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
        # ข้ามวัตถุที่ยึดติดด้านข้าง/ข้อต่อ/มี Parent หรือเป็นชิ้นส่วนประกอบร่วม
        if (obj.get("_side_attached", False) or 
            obj.get("_joint_attached", False) or 
            obj.get("_mate_with") or 
            getattr(obj, "parent", None) is not None):
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
# 8. Attachment Contact Audit (§13.9 Attachment Contact Audit)
# ==============================================================================

def audit_attachment_contact(
    objects: Optional[List[Any]] = None,
    max_gap: float = 0.005
) -> List[Dict[str, Any]]:
    """
    ตรวจสอบระยะแนบสนิท (Surface-gap check) ของชิ้นส่วนที่ติดกับวัตถุแม่
    """
    if bpy is None:
        return []

    if objects is None:
        objects = [
            o for o in bpy.context.scene.objects 
            if o.type == 'MESH' and (o.get("_side_attached", False) or o.get("_joint_attached", False))
        ]

    attachment_issues = []

    for obj in objects:
        # ข้ามชิ้นส่วนที่ถูกเชื่อมโยงผ่านโครงกระดูก Armature แล้ว
        if getattr(obj, "parent_type", None) == 'BONE' or (getattr(obj, "parent", None) and getattr(obj.parent, "type", None) == 'ARMATURE'):
            continue

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

        # คำนวณ Surface Gap ขั้นต่ำระหว่าง Bounding Box ของวัตถุและ Host
        min_a, max_a = get_world_aabb(obj)
        min_b, max_b = get_world_aabb(host_obj)

        gap_x = max(0.0, max(min_a.x - max_b.x, min_b.x - max_a.x))
        gap_y = max(0.0, max(min_a.y - max_b.y, min_b.y - max_a.y))
        gap_z = max(0.0, max(min_a.z - max_b.z, min_b.z - max_a.z))
        surface_gap = (gap_x**2 + gap_y**2 + gap_z**2) ** 0.5

        if surface_gap > max_gap:
            attachment_issues.append({
                "object": obj.name,
                "host": host_name,
                "measured_surface_gap": round(surface_gap, 4),
                "allowed_max_gap": max_gap,
                "status": "FAIL_ATTACHMENT_GAP_EXCEEDED"
            })

    return attachment_issues

# ==============================================================================
# 9. Spacing & Pattern Drift Audit
# ==============================================================================

def audit_spacing(
    object_group: List[Any],
    expected_axis: str = 'X',
    tolerance_ratio: float = 0.05,
    min_drift_threshold: float = 0.001
) -> Dict[str, Any]:
    """
    ตรวจสอบระยะห่างของแถววัตถุ (Array/Pattern) ว่าเท่ากันอย่างสม่ำเสมอหรือไม่
    """
    if len(object_group) < 3:
        return {
            "status": "PASS",
            "message": "ชิ้นส่วนน้อยกว่า 3 ชิ้น ไม่ต้องตรวจวัด Pattern สม่ำเสมอ"
        }

    axis_idx = {'X': 0, 'Y': 1, 'Z': 2}.get(expected_axis.upper(), 0)
    sorted_objs = sorted(object_group, key=lambda o: o.matrix_world.translation[axis_idx])

    spacings = []
    for i in range(len(sorted_objs) - 1):
        p1 = sorted_objs[i].matrix_world.translation
        p2 = sorted_objs[i+1].matrix_world.translation
        dist = (p2 - p1).length
        spacings.append((sorted_objs[i].name, sorted_objs[i+1].name, dist))

    distances = [s[2] for s in spacings]
    sorted_distances = sorted(distances)
    median_spacing = sorted_distances[len(sorted_distances) // 2]

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
# 10. Calibrated Exposure & Luma Distribution Audit
# ==============================================================================

def compute_luma_from_rgb(rgb_array: Any) -> Any:
    """คำนวณค่า Luma จาก RGB (Rec. 709)"""
    if np is None:
        raise RuntimeError("numpy module is required to compute luma statistics.")
    weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    return np.tensordot(rgb_array[..., :3], weights, axes=([ -1 ], [ 0 ]))

def audit_exposure(
    image_filepath: str,
    preset: str = "studio",
    custom_band: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    ตรวจสอบค่าการรับแสงและการกระจายตัวของ Luma จากภาพเรนเดอร์เทียบกับพรีเซ็ต
    """
    if preset not in EXPOSURE_PRESET_BANDS and custom_band is None:
        raise ValueError(f"Unknown preset: '{preset}'. Available: {list(EXPOSURE_PRESET_BANDS.keys())}")

    band = custom_band if custom_band else EXPOSURE_PRESET_BANDS[preset]

    luma = None
    if bpy is not None and os.path.exists(image_filepath):
        try:
            img = bpy.data.images.load(image_filepath)
            width, height = img.size
            channels = img.channels
            total_pixels = width * height
            if np is not None:
                raw_pixels = np.empty(total_pixels * channels, dtype=np.float32)
                img.pixels.foreach_get(raw_pixels)
                raw_pixels = raw_pixels.reshape((height, width, channels))
                rgb_data = (raw_pixels[:, :, :3] * 255.0).clip(0, 255)
                luma = compute_luma_from_rgb(rgb_data)
            else:
                px = list(img.pixels)
                luma = [
                    (0.2126 * px[i] + 0.7152 * px[i+1] + 0.0722 * px[i+2]) * 255.0
                    for i in range(0, len(px), channels)
                ]
            bpy.data.images.remove(img)
        except Exception:
            luma = None

    if luma is None:
        if not os.path.exists(image_filepath):
            raise FileNotFoundError(f"Rendered image file not found: {image_filepath}")
        if Image is None or np is None:
            raise RuntimeError("PIL (Pillow) and numpy are required to audit exposure outside Blender.")
        img = Image.open(image_filepath).convert("RGB")
        rgb_data = np.array(img, dtype=np.float32)
        luma = compute_luma_from_rgb(rgb_data)

    if isinstance(luma, list):
        sorted_luma = sorted(luma)
        total_pixels = len(luma)
        mean_luma = float(sum(luma) / total_pixels) if total_pixels > 0 else 0.0
        median_luma = float(sorted_luma[total_pixels // 2]) if total_pixels > 0 else 0.0
        min_luma = float(sorted_luma[0]) if total_pixels > 0 else 0.0
        max_luma = float(sorted_luma[-1]) if total_pixels > 0 else 0.0
        clipping_count = sum(1 for v in luma if v >= 250.0)
        dark_count = sum(1 for v in luma if v <= 15.0)
    else:
        total_pixels = luma.size
        mean_luma = float(np.mean(luma))
        median_luma = float(np.median(luma))
        min_luma = float(np.min(luma))
        max_luma = float(np.max(luma))
        clipping_count = int(np.count_nonzero(luma >= 250.0))
        dark_count = int(np.count_nonzero(luma <= 15.0))

    clipping_pct = (clipping_count / total_pixels) * 100.0 if total_pixels > 0 else 0.0
    dark_pct = (dark_count / total_pixels) * 100.0 if total_pixels > 0 else 0.0

    issues = []
    recommendations = []

    mean_min = band["mean_min"]
    mean_max = band["mean_max"]
    if mean_luma < mean_min:
        issues.append(f"UNDER_EXPOSED: Mean luma {mean_luma:.1f} is below minimum {mean_min:.1f}")
        recommendations.append("Increase Key Light wattage or adjust camera exposure/ISO.")
    elif mean_luma > mean_max:
        issues.append(f"OVER_EXPOSED: Mean luma {mean_luma:.1f} exceeds maximum {mean_max:.1f}")
        recommendations.append("Reduce Key/Fill Light power or increase camera F-stop.")

    max_clipping = band.get("max_clipping_pct", 1.5)
    if clipping_pct > max_clipping:
        issues.append(f"SPECULAR_BURNOUT: Clipping {clipping_pct:.2f}% exceeds limit {max_clipping:.2f}%")
        recommendations.append("Dim bright area lamps or reduce specular roughness on blown-out materials.")

    max_dark = band.get("max_dark_pct", 35.0)
    if dark_pct > max_dark:
        issues.append(f"EXCESSIVE_DARKNESS: Dark area {dark_pct:.1f}% exceeds limit {max_dark:.1f}%")
        recommendations.append("Add subtle Fill light or increase ambient bounce.")

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
# 11. Headless GLTF / GLB Export Verification
# ==============================================================================

def audit_glb_export(
    export_filepath: str,
    objects: Optional[List[Any]] = None
) -> Dict[str, Any]:
    """
    ตรวจสอบการ Export ไฟล์เป็น glTF/GLB พร้อมวัดขนาดไฟล์และความสมบูรณ์
    """
    if bpy is None:
        return {
            "status": "SKIP_NO_BLENDER",
            "filepath": export_filepath,
            "message": "Blender environment required for glTF export."
        }

    os.makedirs(os.path.dirname(os.path.abspath(export_filepath)), exist_ok=True)

    try:
        bpy.ops.export_scene.gltf(
            filepath=export_filepath,
            export_format='GLB',
            use_selection=False,
            export_apply=True
        )
        if os.path.exists(export_filepath) and os.path.getsize(export_filepath) > 0:
            size_kb = round(os.path.getsize(export_filepath) / 1024.0, 2)
            return {
                "status": "PASS",
                "filepath": export_filepath,
                "file_size_kb": size_kb
            }
        else:
            return {
                "status": "FAIL_FILE_NOT_CREATED",
                "filepath": export_filepath,
                "message": "GLB export completed without errors but destination file is empty or missing."
            }
    except Exception as e:
        return {
            "status": "FAIL_EXPORT_ERROR",
            "filepath": export_filepath,
            "error": str(e)
        }

# ==============================================================================
# 12. Comprehensive Master QA Runner
# ==============================================================================

def run_full_qa_audit(
    render_image_path: Optional[str] = None,
    preset: Optional[str] = None,
    profile_name_or_dict: Optional[Any] = None,
    array_groups: Optional[Dict[str, List[Any]]] = None,
    glb_export_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    รันการตรวจสอบคุณภาพรอบด้าน 5 มิติแบบสมบูรณ์
    :param render_image_path: เส้นทางรูปภาพเรนเดอร์สำหรับการตรวจสอบแสง (Optional)
    :param preset: พรีเซ็ตการจัดแสง (ถ้ามีระบุใน profile จะถูกแทนที่ด้วย profile)
    :param profile_name_or_dict: ชื่อโปรไฟล์ (เช่น 'lowpoly_prop') หรือ dict ของโปรไฟล์
    :param array_groups: ดิกชันนารีของกลุ่มวัตถุที่จัดเรียงเป็นอาเรย์
    :param glb_export_path: เส้นทางส่งออก GLB เพื่อทดสอบการส่งออกจริง (Optional)
    """
    # 1. Resolve Profile
    active_profile = None
    if isinstance(profile_name_or_dict, dict):
        active_profile = profile_name_or_dict
    elif isinstance(profile_name_or_dict, str) and load_profile is not None:
        active_profile = load_profile(profile_name_or_dict)
    elif load_profile is not None:
        active_profile = load_profile("default_generic")

    selected_preset = preset or (active_profile.get("exposure_preset", "studio") if active_profile else "studio")

    interpenetrations = []
    floating = []
    attachments = []
    transform_issues = []
    topology_issues = []
    material_issues = []

    if bpy is not None:
        interpenetrations = audit_interpenetration()
        floating = audit_floating()
        attachments = audit_attachment_contact()
        transform_issues = audit_transforms(profile=active_profile)
        topology_issues = audit_mesh_topology()
        material_issues = audit_materials_compatibility()

    polycount_rep = audit_polycount(profile=active_profile)
    polycount_passed = polycount_rep["status"] in ("PASS", "WARN_ABOVE_TARGET_TRIS")

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
        exposure_report = audit_exposure(render_image_path, preset=selected_preset)
        if exposure_report["status"] != "PASS":
            exposure_passed = False

    glb_report = None
    glb_passed = True
    if glb_export_path:
        glb_report = audit_glb_export(glb_export_path)
        if glb_report["status"] not in ("PASS", "SKIP_NO_BLENDER"):
            glb_passed = False

    passed = (
        (len(interpenetrations) == 0) and 
        (len(floating) == 0) and 
        (len(attachments) == 0) and 
        (len(transform_issues) == 0) and 
        polycount_passed and 
        spacing_passed and 
        exposure_passed and 
        glb_passed
    )

    report = {
        "qa_passed": passed,
        "profile_used": active_profile.get("profile_name", "none") if active_profile else "none",
        "polycount_audit": polycount_rep,
        "transform_issues": transform_issues,
        "topology_issues": topology_issues,
        "material_issues": material_issues,
        "interpenetration_issues": interpenetrations,
        "floating_issues": floating,
        "attachment_issues": attachments,
        "spacing_issues": spacing_reports,
        "exposure_audit": exposure_report,
        "glb_export_audit": glb_report,
        "summary": {
            "total_collisions": len(interpenetrations),
            "total_floating": len(floating),
            "total_attachment_issues": len(attachments),
            "total_transform_issues": len(transform_issues),
            "total_topology_warnings": len(topology_issues),
            "total_tris": polycount_rep["total_tris"],
            "polycount_status": polycount_rep["status"],
            "exposure_audited": render_image_path is not None,
            "glb_audited": glb_export_path is not None
        }
    }
    return report

if __name__ == "__main__":
    if bpy is not None:
        res = run_full_qa_audit(profile_name_or_dict="lowpoly_prop")
        import json
        print("GEOMETRY_QA_REPORT:" + json.dumps(res, indent=2, ensure_ascii=False))
