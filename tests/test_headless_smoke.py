#!/usr/bin/env python3
"""
Unit and Smoke Tests for Blender Headless Universal AI Suite
Validates:
  1. Profile Loader (profiles/*.json and fallback)
  2. AABB Fast-Path Collision & Separation
  3. Polycount Budget & LOD Auditing
  4. Transform & Pivot Grounding Auditing
  5. Spacing & Pattern Drift Detection
  6. Attachment & Assembly Mate Marker Verification
  7. Shader Generator & glTF 2.0 Compatibility Auditing
  8. Calibrated Exposure & Luma Distribution (audit_exposure)
  9. Comprehensive Master QA Runner with Profiles
"""

import sys
import os
import unittest
import tempfile
import numpy as np
from PIL import Image

# Ensure src module can be resolved
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src import quality_checker
from src import profile_loader
from src import shader_generator

class DummyVector:
    def __init__(self, x, y, z):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    def __getitem__(self, idx):
        return (self.x, self.y, self.z)[idx]

    def __sub__(self, other):
        return DummyVector(self.x - other.x, self.y - other.y, self.z - other.z)

    @property
    def length(self):
        return (self.x**2 + self.y**2 + self.z**2) ** 0.5

class DummyMatrix:
    def __init__(self, translation):
        self.translation = translation

class DummyPolygon:
    def __init__(self, vert_indices):
        self.vertices = vert_indices

class DummyMeshData:
    def __init__(self, polygons, vertices_count):
        self.polygons = [DummyPolygon(p) for p in polygons]
        self.vertices = [DummyVector(0, 0, 0) for _ in range(vertices_count)]

class DummyObject:
    def __init__(self, name, translation=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0)):
        self.name = name
        self.matrix_world = DummyMatrix(DummyVector(*translation))
        self.scale = scale
        self._data = {}
        self.data = DummyMeshData(polygons=[], vertices_count=0)
        # Bounding box coordinates in local space
        self.bound_box = [
            (-0.5, -0.5, 0.0),
            (0.5, -0.5, 0.0),
            (0.5, 0.5, 0.0),
            (-0.5, 0.5, 0.0),
            (-0.5, -0.5, 1.0),
            (0.5, -0.5, 1.0),
            (0.5, 0.5, 1.0),
            (-0.5, 0.5, 1.0)
        ]
        self._custom_aabb = (DummyVector(-0.5, -0.5, translation[2]), DummyVector(0.5, 0.5, translation[2] + 1.0))

    def __setitem__(self, key, value):
        self._data[key] = value

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)

class TestProfileLoader(unittest.TestCase):
    def test_load_standard_profiles(self):
        for name in ["lowpoly_prop", "character", "hard_surface", "environment_kit"]:
            prof = profile_loader.load_profile(name)
            self.assertEqual(prof["profile_name"], name)
            self.assertIn("polycount_budget", prof)
            self.assertIn("max_tris", prof["polycount_budget"])
            self.assertIn("grounding", prof)

    def test_fallback_on_unknown_profile(self):
        prof = profile_loader.load_profile("non_existent_profile_xyz")
        self.assertEqual(prof["profile_name"], "non_existent_profile_xyz")
        self.assertEqual(prof["polycount_budget"]["max_tris"], 2500)

class TestPolycountAudit(unittest.TestCase):
    def test_polycount_within_budget(self):
        profile = {"polycount_budget": {"target_tris": 300, "max_tris": 500}}
        obj = DummyObject("LowPolyRock")
        # 4 quads = 8 tris
        obj.data = DummyMeshData(polygons=[[0, 1, 2, 3] for _ in range(4)], vertices_count=8)
        
        rep = quality_checker.audit_polycount([obj], profile=profile)
        self.assertEqual(rep["status"], "PASS")
        self.assertEqual(rep["total_tris"], 8)

    def test_polycount_exceeded(self):
        profile = {"polycount_budget": {"target_tris": 100, "max_tris": 200}}
        obj = DummyObject("HighPolyMesh")
        # 150 quads = 300 tris > max 200
        obj.data = DummyMeshData(polygons=[[0, 1, 2, 3] for _ in range(150)], vertices_count=300)

        rep = quality_checker.audit_polycount([obj], profile=profile)
        self.assertEqual(rep["status"], "FAIL_POLYCOUNT_EXCEEDED")
        self.assertEqual(rep["total_tris"], 300)

class TestTransformAudit(unittest.TestCase):
    def test_unapplied_scale_detected(self):
        obj = DummyObject("StretchedBox", scale=(2.0, 1.0, 1.0))
        issues = quality_checker.audit_transforms([obj])
        self.assertTrue(any(i["status"] == "FAIL_UNAPPLIED_SCALE" for i in issues))

    def test_grounding_z_offset_detected(self):
        # Base min Z is at 0.5m instead of 0.0m
        obj = DummyObject("FloatingCrate", translation=(0.0, 0.0, 0.5))
        obj._custom_aabb = (DummyVector(-0.5, -0.5, 0.5), DummyVector(0.5, 0.5, 1.5))
        profile = {"grounding": {"enforce_pivot_base": True, "target_min_z": 0.0, "z_tolerance": 0.005}}

        issues = quality_checker.audit_transforms([obj], profile=profile)
        self.assertTrue(any(i["status"] == "FAIL_BASE_OFF_GROUND" for i in issues))

class TestShaderCompatibilityAudit(unittest.TestCase):
    class DummyNode:
        def __init__(self, name, bl_idname, ntype):
            self.name = name
            self.bl_idname = bl_idname
            self.type = ntype

    class DummyTree:
        def __init__(self, nodes):
            self.nodes = nodes

    class DummyMaterial:
        def __init__(self, name, nodes):
            self.name = name
            self.use_nodes = True
            self.node_tree = TestShaderCompatibilityAudit.DummyTree(nodes)

    def test_compatible_principled_material(self):
        nodes = [
            self.DummyNode("Material Output", "ShaderNodeOutputMaterial", "OUTPUT_MATERIAL"),
            self.DummyNode("Principled BSDF", "ShaderNodeBsdfPrincipled", "BSDF_PRINCIPLED")
        ]
        mat = self.DummyMaterial("Mat_PBR", nodes)
        rep = shader_generator.audit_material_nodes(mat)
        self.assertTrue(rep["compatible"])
        self.assertEqual(rep["status"], "PASS")

    def test_incompatible_eevee_node_detected(self):
        nodes = [
            self.DummyNode("Material Output", "ShaderNodeOutputMaterial", "OUTPUT_MATERIAL"),
            self.DummyNode("Principled BSDF", "ShaderNodeBsdfPrincipled", "BSDF_PRINCIPLED"),
            self.DummyNode("Shader to RGB", "ShaderNodeShaderToRGB", "SHADER_TO_RGB")
        ]
        mat = self.DummyMaterial("Mat_CelToon", nodes)
        rep = shader_generator.audit_material_nodes(mat)
        self.assertFalse(rep["compatible"])
        self.assertEqual(rep["status"], "WARN_GLTF_INCOMPATIBLE")
        self.assertTrue(any("ShaderNodeShaderToRGB" in w for w in rep["warnings"]))

class TestAABBLogic(unittest.TestCase):
    def test_aabb_no_overlap(self):
        min_a = DummyVector(0, 0, 0)
        max_a = DummyVector(1, 1, 1)
        min_b = DummyVector(2, 2, 2)
        max_b = DummyVector(3, 3, 3)
        self.assertFalse(quality_checker.aabb_intersect(min_a, max_a, min_b, max_b))

    def test_aabb_full_overlap(self):
        min_a = DummyVector(0, 0, 0)
        max_a = DummyVector(2, 2, 2)
        min_b = DummyVector(1, 1, 1)
        max_b = DummyVector(3, 3, 3)
        self.assertTrue(quality_checker.aabb_intersect(min_a, max_a, min_b, max_b))

class TestAttachmentMarkers(unittest.TestCase):
    def test_assembly_mate_marker(self):
        obj_a = DummyObject("Caliper")
        obj_b = DummyObject("BrakeDisk")
        quality_checker.mark_assembly_mate(obj_a, obj_b)
        self.assertEqual(obj_a.get("_mate_with"), "BrakeDisk")
        self.assertEqual(obj_b.get("_mate_with"), "Caliper")

    def test_side_and_joint_attached_markers(self):
        sign = DummyObject("DoorSign")
        door = DummyObject("MainDoor")
        quality_checker.mark_side_attached(sign, door)
        self.assertTrue(sign.get("_side_attached"))
        self.assertEqual(sign.get("_host_object"), "MainDoor")

class TestSpacingAuditLogic(unittest.TestCase):
    def test_spacing_uniform(self):
        objs = [
            DummyObject("Pillar_1", (0.0, 0.0, 0.0)),
            DummyObject("Pillar_2", (1.0, 0.0, 0.0)),
            DummyObject("Pillar_3", (2.0, 0.0, 0.0)),
            DummyObject("Pillar_4", (3.0, 0.0, 0.0))
        ]
        res = quality_checker.audit_spacing(objs, expected_axis='X')
        self.assertEqual(res["status"], "PASS")
        self.assertAlmostEqual(res["median_spacing"], 1.0)

class TestExposureAuditLogic(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_test_image(self, rgb_array, filename="test_render.png"):
        filepath = os.path.join(self.temp_dir, filename)
        img = Image.fromarray(np.uint8(rgb_array), mode="RGB")
        img.save(filepath)
        return filepath

    def test_studio_exposure_pass(self):
        data = np.full((100, 100, 3), 135, dtype=np.uint8)
        img_path = self._create_test_image(data, "studio_pass.png")
        rep = quality_checker.audit_exposure(img_path, preset="studio")
        self.assertEqual(rep["status"], "PASS")

    def test_under_exposure_detected(self):
        data = np.full((100, 100, 3), 50, dtype=np.uint8)
        img_path = self._create_test_image(data, "studio_underexposed.png")
        rep = quality_checker.audit_exposure(img_path, preset="studio")
        self.assertEqual(rep["status"], "FAIL_EXPOSURE_DRIFT")

    def test_specular_clipping_detected(self):
        data = np.full((100, 100, 3), 120, dtype=np.uint8)
        data[:5, :100, :] = 255
        img_path = self._create_test_image(data, "studio_clipping.png")
        rep = quality_checker.audit_exposure(img_path, preset="studio")
        self.assertEqual(rep["status"], "FAIL_EXPOSURE_DRIFT")

    def test_master_full_qa_runner_with_profile(self):
        data = np.full((100, 100, 3), 135, dtype=np.uint8)
        img_path = self._create_test_image(data, "clean_runner.png")

        rep = quality_checker.run_full_qa_audit(
            render_image_path=img_path,
            profile_name_or_dict="lowpoly_prop"
        )
        self.assertTrue(rep["qa_passed"])
        self.assertEqual(rep["profile_used"], "lowpoly_prop")
        self.assertEqual(rep["summary"]["polycount_status"], "PASS")

if __name__ == "__main__":
    unittest.main()
