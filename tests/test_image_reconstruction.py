#!/usr/bin/env python3
"""
Unit and Integration Tests for Image-to-3D Reconstruction & Blueprint Verification
Validates:
  1. Silhouette Extraction & Bounding Box calculation
  2. Scale Calibration (pixels-to-meters)
  3. Half-profile Radii Sampling & Normalization
  4. Silhouette IoU (Intersection-over-Union) & Normalization
  5. Blueprint Verification & Inspection Composite Generation
"""

import sys
import os
import unittest
import tempfile
import numpy as np
from PIL import Image

# Ensure src module can be resolved
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src import image_reconstructor
from src import blueprint_verifier


class TestImageReconstruction(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_synthetic_mug_image(self, filename="synthetic_mug.png", w=300, h=400):
        filepath = os.path.join(self.temp_dir, filename)
        # Background: light gray (240)
        img_arr = np.full((h, w, 3), 240, dtype=np.uint8)

        # Draw dark mug body: centered, width ~120, height ~240
        # y from 100 to 340, x from 90 to 210
        img_arr[100:340, 90:210, :] = 40

        # Draw handle on right side: y from 140 to 300, x from 210 to 250
        img_arr[140:300, 210:250, :] = 40

        img = Image.fromarray(img_arr, mode="RGB")
        img.save(filepath)
        return filepath

    def test_extract_silhouette_and_bbox(self):
        img_path = self._create_synthetic_mug_image("mug_ref.png")
        sil = image_reconstructor.extract_silhouette_and_bbox(img_path)

        self.assertIn("mask", sil)
        self.assertIn("bbox", sil)
        self.assertIn("aspect_ratio", sil)

        xmin, ymin, xmax, ymax = sil["bbox"]
        # Body is x: 90..210 + handle to 250 -> xmin approx 90, xmax approx 249
        self.assertAlmostEqual(xmin, 90, delta=5)
        self.assertAlmostEqual(xmax, 249, delta=5)
        self.assertAlmostEqual(ymin, 100, delta=5)
        self.assertAlmostEqual(ymax, 339, delta=5)

    def test_calibrate_scale(self):
        bbox = (90, 100, 250, 340)  # height = 240px
        calib = image_reconstructor.calibrate_scale(bbox, real_dimension_m=0.095, axis="height")

        self.assertIn("pixels_per_meter", calib)
        self.assertAlmostEqual(calib["pixel_height"], 240.0)
        expected_ppm = 240.0 / 0.095
        self.assertAlmostEqual(calib["pixels_per_meter"], expected_ppm, delta=1.0)
        self.assertAlmostEqual(calib["real_height_m"], 0.095, delta=0.001)

    def test_extract_half_profile_radii(self):
        img_path = self._create_synthetic_mug_image("profile_mug.png")
        sil = image_reconstructor.extract_silhouette_and_bbox(img_path)

        profiles = image_reconstructor.extract_half_profile_radii(
            sil["mask"],
            sil["bbox"],
            target_height_m=0.095,
            target_radius_m=0.040,
            num_samples=16,
            ignore_handle=True
        )

        self.assertEqual(len(profiles), 16)
        # Check monotonic Z
        for i in range(1, len(profiles)):
            self.assertGreater(profiles[i][1], profiles[i-1][1])
            # Check radius is positive and realistic
            self.assertGreater(profiles[i][0], 0.01)
            self.assertLess(profiles[i][0], 0.08)

    def test_mask_iou_computation(self):
        mask_a = np.zeros((100, 100), dtype=bool)
        mask_a[20:60, 20:60] = True

        # Exactly identical mask
        mask_b = mask_a.copy()
        self.assertAlmostEqual(blueprint_verifier.compute_mask_iou(mask_a, mask_b), 1.0)

        # Disjoint mask
        mask_c = np.zeros((100, 100), dtype=bool)
        mask_c[70:90, 70:90] = True
        self.assertAlmostEqual(blueprint_verifier.compute_mask_iou(mask_a, mask_c), 0.0)

        # Partial overlap (50% overlap of A with B)
        mask_d = np.zeros((100, 100), dtype=bool)
        mask_d[20:60, 40:80] = True
        iou = blueprint_verifier.compute_mask_iou(mask_a, mask_d)
        # Intersection = 40x20 = 800, Union = 40x60 = 2400 -> IoU = 800/2400 = 0.3333
        self.assertAlmostEqual(iou, 1.0 / 3.0, places=3)

    def test_audit_silhouette_fidelity_and_overlay(self):
        ref_path = self._create_synthetic_mug_image("ref_mug.png")
        rnd_path = self._create_synthetic_mug_image("rnd_mug.png")

        rep = blueprint_verifier.audit_silhouette_fidelity(
            render_image_path=rnd_path,
            reference_image_path=ref_path,
            iou_target=0.85
        )

        self.assertEqual(rep["status"], "PASS")
        self.assertGreaterEqual(rep["iou_score"], 0.95)
        self.assertTrue(rep["verification_passed"])

        overlay_out = os.path.join(self.temp_dir, "overlay_test.png")
        created_path = blueprint_verifier.generate_blueprint_overlay(
            render_image_path=rnd_path,
            reference_image_path=ref_path,
            output_overlay_path=overlay_out
        )
        self.assertTrue(os.path.isfile(created_path))
        self.assertGreater(os.path.getsize(created_path), 1000)


if __name__ == "__main__":
    unittest.main()

