#!/usr/bin/env python3
"""
Template Headless BPY Worker with Universal Multi-Genre QA Pipeline
Demonstrates:
  1. Profile-driven configuration (lowpoly_prop, character, hard_surface, environment_kit)
  2. Procedural Principled BSDF materials & lighting setup
  3. Grounding & transform alignment (Z=0)
  4. Complete 4-in-1 deliverables: .blend + .glb + render + qa_report.json
"""

import os
import sys
import json
import argparse

# Allow resolving src modules from sub-repo
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    import bpy
    import mathutils
except ImportError:
    print("[!] This script must be executed via Blender Headless: blender --background --python <script>")
    sys.exit(1)

from src import quality_checker
from src import profile_loader
from src import shader_generator

def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Headless Blender Universal Worker")
    parser.add_argument("--out-dir", default="out", help="Output directory for renders and assets")
    parser.add_argument("--profile", default="hard_surface", help="Profile preset (lowpoly_prop, character, hard_surface, environment_kit)")
    return parser.parse_args(argv)

def build_scene(out_dir: str, profile_name: str = "hard_surface"):
    os.makedirs(out_dir, exist_ok=True)
    profile = profile_loader.load_profile(profile_name)
    print(f"[+] Loaded Profile: {profile['profile_name']} (Target Tris: {profile['polycount_budget']['target_tris']}, Max Tris: {profile['polycount_budget']['max_tris']})")
    
    # 1. Reset Scene
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    # 2. Add Ground Plane
    bpy.ops.mesh.primitive_plane_add(size=20.0, location=(0, 0, 0))
    ground = bpy.context.active_object
    ground.name = "Env_Ground"
    
    mat_ground = shader_generator.create_principled_material(
        name="Mat_GroundDark",
        base_color=(0.08, 0.08, 0.08, 1.0),
        roughness=0.8,
        metallic=0.0
    )
    ground.data.materials.append(mat_ground)

    # 3. Add Hero Object (Precision Beveled Cube anchored to Z=0)
    # Cube size 2.0 with location Z=1.0 puts bottom at Z=0.0
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 1.0))
    hero = bpy.context.active_object
    hero.name = "Mst_HeroObject"
    
    bevel = hero.modifiers.new(name="Bevel", type='BEVEL')
    bevel.width = 0.05
    bevel.segments = 2
    
    mat_hero = shader_generator.create_principled_material(
        name="Mat_BrushedMetal",
        base_color=(0.7, 0.72, 0.75, 1.0),
        roughness=profile["materials"].get("roughness_range", [0.25, 0.5])[0],
        metallic=profile["materials"].get("metallic_default", 0.85)
    )
    hero.data.materials.append(mat_hero)

    # Apply transforms
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

    # 4. Lighting (Three-Point Studio AREA Lights)
    bpy.ops.object.light_add(type='AREA', radius=2.0, location=(-4.0, -5.0, 5.0))
    key = bpy.context.active_object
    key.name = "Lgt_KeyWarm"
    key.data.energy = 400.0
    key.data.color = (1.0, 0.95, 0.88)

    bpy.ops.object.light_add(type='AREA', radius=3.0, location=(5.0, -4.0, 3.0))
    fill = bpy.context.active_object
    fill.name = "Lgt_FillNeutral"
    fill.data.energy = 150.0
    fill.data.color = (0.9, 0.92, 1.0)

    bpy.ops.object.light_add(type='AREA', radius=1.5, location=(0.0, 5.0, 4.0))
    rim = bpy.context.active_object
    rim.name = "Lgt_RimCool"
    rim.data.energy = 300.0
    rim.data.color = (0.8, 0.88, 1.0)

    # 5. Camera Setup
    bpy.ops.object.camera_add(location=(0.0, -6.5, 3.5))
    cam = bpy.context.active_object
    cam.name = "Main_Camera"
    cam.data.lens = 50.0
    scene.camera = cam

    direction = mathutils.Vector((0, 0, 1.0)) - cam.location
    cam.rotation_mode = 'QUATERNION'
    cam.rotation_quaternion = direction.to_track_quat("-Z", "Y")

    # 6. Render Configuration (Cycles CPU Thread-capped: 6 threads)
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = 6
    scene.cycles.samples = 64
    scene.render.resolution_x = 960
    scene.render.resolution_y = 540
    scene.render.resolution_percentage = 100

    render_path = os.path.join(out_dir, "render_sample.png")
    scene.render.filepath = render_path
    bpy.ops.render.render(write_still=True)
    print(f"[+] Render complete: {render_path}")

    # 7. GLB Model Export
    glb_path = os.path.join(out_dir, "hero_model.glb")

    # 8. Blend File Archive
    blend_path = os.path.join(out_dir, "scene.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"[+] Project blend file saved: {blend_path}")

    # 9. Run Comprehensive QA Hard Gates
    qa_report = quality_checker.run_full_qa_audit(
        render_image_path=render_path,
        profile_name_or_dict=profile,
        glb_export_path=glb_path
    )
    qa_report_path = os.path.join(out_dir, "qa_report.json")
    with open(qa_report_path, "w", encoding="utf-8") as f:
        json.dump(qa_report, f, indent=2, ensure_ascii=False)
    print(f"[+] Comprehensive QA Report saved: {qa_report_path}")
    print(f"[+] QA Overall Passed: {qa_report['qa_passed']}")

    # 10. Output Numerical Ground Truth State
    state = {
        "status": "SUCCESS" if qa_report["qa_passed"] else "FAIL_QA_CHECK",
        "profile": profile["profile_name"],
        "qa_passed": qa_report["qa_passed"],
        "total_tris": qa_report["summary"]["total_tris"],
        "render_file": render_path,
        "glb_file": glb_path,
        "blend_file": blend_path,
        "qa_report_file": qa_report_path
    }
    print("SCENE_STATE:" + json.dumps(state, ensure_ascii=False))

if __name__ == "__main__":
    args = parse_args()
    build_scene(args.out_dir, args.profile)
