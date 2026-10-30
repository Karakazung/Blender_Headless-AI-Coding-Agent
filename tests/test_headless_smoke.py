#!/usr/bin/env python3
"""
Unit and Smoke Tests for Blender Headless QA Suite
Validates:
  1. AABB Fast-Path Collision & Separation
  2. Spacing & Pattern Drift Detection
  3. Attachment & Assembly Mate Marker Verification
  4. Calibrated Exposure & Luma Distribution (audit_exposure)
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

    def test_aabb_edge_touching_with_tolerance(self):
        min_a = DummyVector(0, 0, 0)
        max_a = DummyVector(1, 1, 1)
        min_b = DummyVector(1, 0, 0)
        max_b = DummyVector(2, 1, 1)
        # Touching faces with tolerance should not be classified as deep collision
        self.assertFalse(quality_checker.aabb_intersect(min_a, max_a, min_b, max_b, tolerance=0.001))

class DummyMatrix:
    def __init__(self, translation):
        self.translation = translation

class DummyObject:
    def __init__(self, name, translation=(0.0, 0.0, 0.0)):
        self.name = name
        self.matrix_world = DummyMatrix(DummyVector(*translation))
        self._data = {}

    def __setitem__(self, key, value):
        self._data[key] = value

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)

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

        bearing = DummyObject("Bearing_Inner")
        shaft = DummyObject("Axle_Shaft")
        quality_checker.mark_joint_attached(bearing, shaft)
        self.assertTrue(bearing.get("_joint_attached"))
        self.assertEqual(bearing.get("_host_object"), "Axle_Shaft")

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

    def test_spacing_drift_detected(self):
        objs = [
            DummyObject("Rail_1", (0.0, 0.0, 0.0)),
            DummyObject("Rail_2", (1.0, 0.0, 0.0)),
            DummyObject("Rail_3", (2.3, 0.0, 0.0)),  # Drifted by 0.3m (30%)
            DummyObject("Rail_4", (3.3, 0.0, 0.0))
        ]
        res = quality_checker.audit_spacing(objs, expected_axis='X', tolerance_ratio=0.05)
        self.assertEqual(res["status"], "FAIL_SPACING_DRIFT")
        self.assertEqual(res["drift_count"], 1)
        self.assertEqual(res["details"][0]["pair"], ("Rail_2", "Rail_3"))

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
        # Create an image with uniform medium-gray (Luma ~ 135)
        data = np.full((100, 100, 3), 135, dtype=np.uint8)
        img_path = self._create_test_image(data, "studio_pass.png")
        
        rep = quality_checker.audit_exposure(img_path, preset="studio")
        self.assertEqual(rep["status"], "PASS")
        self.assertAlmostEqual(rep["mean_luma"], 135.0, places=1)
        self.assertEqual(rep["clipping_pct"], 0.0)
        self.assertEqual(rep["dark_pct"], 0.0)
        self.assertEqual(len(rep["issues"]), 0)

    def test_under_exposure_detected(self):
        # Create an image that is too dark for studio (Luma ~ 50 < 100)
        data = np.full((100, 100, 3), 50, dtype=np.uint8)
        img_path = self._create_test_image(data, "studio_underexposed.png")

        rep = quality_checker.audit_exposure(img_path, preset="studio")
        self.assertEqual(rep["status"], "FAIL_EXPOSURE_DRIFT")
        self.assertTrue(any("UNDER_EXPOSED" in issue for issue in rep["issues"]))

    def test_specular_clipping_detected(self):
        # Create an image with 5% blown-out white pixels (255)
        data = np.full((100, 100, 3), 120, dtype=np.uint8)
        data[:5, :100, :] = 255  # 500 / 10000 = 5% clipping (> 1.5%)
        img_path = self._create_test_image(data, "studio_clipping.png")

        rep = quality_checker.audit_exposure(img_path, preset="studio")
        self.assertEqual(rep["status"], "FAIL_EXPOSURE_DRIFT")
        self.assertTrue(any("SPECULAR_BURNOUT" in issue for issue in rep["issues"]))

    def test_night_hotspot_drift(self):
        # Night scene: 95% pitch dark (Luma 2) + 5% intense specular hotspot (Luma 250)
        # Mean = 0.95 * 2 + 0.05 * 250 = 14.4 (near lower bound)
        # Median = 2.0 -> |Mean - Median| = 12.4
        # If 90% dark and 10% intense: Mean = 0.9*5 + 0.1*250 = 29.5
        # Median = 5.0 -> diff = 24.5 > 18.0 with dark_pct = 90% > 40%
        data = np.full((100, 100, 3), 5, dtype=np.uint8)
        data[:10, :100, :] = 245  # high intensity but not clipping 250 to isolate hotspot
        img_path = self._create_test_image(data, "night_hotspot.png")

        rep = quality_checker.audit_exposure(img_path, preset="night")
        self.assertEqual(rep["status"], "FAIL_EXPOSURE_DRIFT")
        self.assertTrue(any("HOTSPOT_DRIFT" in issue for issue in rep["issues"]))

    def test_master_full_qa_runner_clean(self):
        # Run master QA runner with passing studio image
        data = np.full((100, 100, 3), 135, dtype=np.uint8)
        img_path = self._create_test_image(data, "clean_runner.png")

        rep = quality_checker.run_full_qa_audit(render_image_path=img_path, preset="studio")
        self.assertTrue(rep["qa_passed"])
        self.assertIsNotNone(rep["exposure_audit"])
        self.assertEqual(rep["exposure_audit"]["status"], "PASS")

if __name__ == "__main__":
    unittest.main()
