#!/usr/bin/env python3
"""
Profile Loader Module for Blender Headless AI Suite
Loads and validates JSON profiles from `profiles/*.json` defining:
  - Polycount budget (target and hard ceiling)
  - Grounding & pivot constraints
  - Geometry tolerances
  - Shading styles & exposure presets
"""

import os
import json
from typing import Dict, Any, Optional

DEFAULT_PROFILES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "profiles"))

DEFAULT_FALLBACK_PROFILE: Dict[str, Any] = {
    "profile_name": "default_generic",
    "polycount_budget": {
        "target_tris": 1000,
        "max_tris": 2500
    },
    "scale_metric": "meters",
    "grounding": {
        "enforce_pivot_base": True,
        "target_min_z": 0.0,
        "z_tolerance": 0.005
    },
    "geometry_tolerance": {
        "interpenetration_tolerance": 0.001,
        "floating_max_gap": 0.005,
        "floating_max_sink": -0.002,
        "spacing_tolerance_ratio": 0.05
    },
    "materials": {
        "style": "stylized_flat_pbr",
        "roughness_range": [0.4, 0.8],
        "metallic_default": 0.0
    },
    "exposure_preset": "studio"
}

def load_profile(profile_name_or_path: str, profiles_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    โหลดโปรไฟล์ตามชื่อ (เช่น 'lowpoly_prop') หรือเส้นทางไฟล์ตรง (.json)
    """
    base_dir = profiles_dir or DEFAULT_PROFILES_DIR
    
    if os.path.isfile(profile_name_or_path):
        filepath = profile_name_or_path
    else:
        # ลองค้นหาใน base_dir โดยเติม .json
        name = profile_name_or_path if profile_name_or_path.endswith(".json") else f"{profile_name_or_path}.json"
        filepath = os.path.join(base_dir, name)

    if not os.path.isfile(filepath):
        print(f"[WARN] Profile '{profile_name_or_path}' not found at '{filepath}'. Using default fallback profile.")
        fallback = dict(DEFAULT_FALLBACK_PROFILE)
        fallback["profile_name"] = str(profile_name_or_path)
        return fallback

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    # รวมค่าเริ่มต้นเพื่อป้องกันคีย์สูญหาย (Safe Merge)
    merged = dict(DEFAULT_FALLBACK_PROFILE)
    for k, v in data.items():
        if isinstance(v, dict) and k in merged and isinstance(merged[k], dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v

    return merged

def list_available_profiles(profiles_dir: Optional[str] = None) -> Dict[str, str]:
    """คืนค่ารายชื่อโปรไฟล์ที่มีอยู่ในโฟลเดอร์ profiles"""
    base_dir = profiles_dir or DEFAULT_PROFILES_DIR
    if not os.path.isdir(base_dir):
        return {}
    
    results = {}
    for filename in os.listdir(base_dir):
        if filename.endswith(".json"):
            profile_key = os.path.splitext(filename)[0]
            results[profile_key] = os.path.join(base_dir, filename)
    return results

if __name__ == "__main__":
    profiles = list_available_profiles()
    print("Available Profiles:", list(profiles.keys()))
    for p_name in profiles:
        loaded = load_profile(p_name)
        print(f"[{p_name}] max_tris={loaded['polycount_budget']['max_tris']}, preset={loaded['exposure_preset']}")

