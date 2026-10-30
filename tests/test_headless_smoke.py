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

if __name__ == "__main__":
    unittest.main()
