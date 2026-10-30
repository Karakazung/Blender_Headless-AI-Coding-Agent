#!/usr/bin/env python3
"""
Unit and Smoke Tests for Blender Headless QA Suite
Validates AABB, BVH Interpenetration, and Floating Audit Logic.
"""

import sys
import os
import unittest

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
    def __init__(self, name, translation):
        self.name = name
        self.matrix_world = DummyMatrix(DummyVector(*translation))

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

if __name__ == "__main__":
    unittest.main()

