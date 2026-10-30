#!/usr/bin/env python3
"""
Template Headless BPY Worker
Demonstrates deterministic geometry creation, PBR materials, Cycles rendering, and GLB export.
"""

import os
import sys
import json
import argparse

try:
    import bpy
    import mathutils
except ImportError:
    print("[!] This script must be executed via Blender Headless: blender --background --python <script>")
    sys.exit(1)

def parse_args():
    # Parse arguments passed after '--'
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Headless Blender Worker")
    parser.add_argument("--out-dir", default="out", help="Output directory for renders and assets")
    return parser.parse_args(argv)

def build_scene(out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    
    # 1. Reset Scene
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    # 2. Add Ground Plane
    bpy.ops.mesh.primitive_plane_add(size=20.0, location=(0, 0, 0))
    ground = bpy.context.active_object
    ground.name = "Env_Ground"
    
    # Ground Material
    mat_ground = bpy.data.materials.new(name="Mat_GroundDark")
    mat_ground.use_nodes = True
    bsdf_ground = mat_ground.node_tree.nodes.get("Principled BSDF")
    if bsdf_ground:
        bsdf_ground.inputs["Base Color"].default_value = (0.08, 0.08, 0.08, 1.0)
        bsdf_ground.inputs["Roughness"].default_value = 0.8
    ground.data.materials.append(mat_ground)

    # 3. Add Hero Object (Precision Beveled Box)
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 1.0))
    hero = bpy.context.active_object
    hero.name = "Mst_HeroObject"
    
    # Apply Bevel Modifier
    bevel = hero.modifiers.new(name="Bevel", type='BEVEL')
    bevel.width = 0.05
    bevel.segments = 3
    
    # Hero Material (PBR Metal)
    mat_hero = bpy.data.materials.new(name="Mat_BrushedMetal")
    mat_hero.use_nodes = True
    bsdf_hero = mat_hero.node_tree.nodes.get("Principled BSDF")
    if bsdf_hero:
        bsdf_hero.inputs["Base Color"].default_value = (0.7, 0.72, 0.75, 1.0)
        bsdf_hero.inputs["Metallic"].default_value = 0.95
        bsdf_hero.inputs["Roughness"].default_value = 0.25
    hero.data.materials.append(mat_hero)

    # 4. Lighting (Three-Point Studio AREA Lights)
    # Key Light (Warm)
    bpy.ops.object.light_add(type='AREA', radius=2.0, location=(-4.0, -5.0, 5.0))
    key = bpy.context.active_object
    key.name = "Lgt_KeyWarm"
    key.data.energy = 400.0
    key.data.color = (1.0, 0.95, 0.88)

    # Fill Light (Neutral)
    bpy.ops.object.light_add(type='AREA', radius=3.0, location=(5.0, -4.0, 3.0))
    fill = bpy.context.active_object
    fill.name = "Lgt_FillNeutral"
    fill.data.energy = 150.0
    fill.data.color = (0.9, 0.92, 1.0)

    # Rim Light (Cool)
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

    # Aim camera at hero center (0, 0, 1)
    direction = mathutils.Vector((0, 0, 1.0)) - cam.location
    cam.rotation_mode = 'QUATERNION'
    cam.rotation_quaternion = direction.to_track_quat("-Z", "Y")

    # 6. Render Configuration (Cycles CPU Thread-capped)
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = 6
    scene.cycles.samples = 128
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100

    render_path = os.path.join(out_dir, "render_sample.png")
    scene.render.filepath = render_path
    bpy.ops.render.render(write_still=True)
    print(f"[+] Render complete: {render_path}")

    # 7. GLB Model Export
    glb_path = os.path.join(out_dir, "hero_model.glb")
    bpy.ops.export_scene.gltf(filepath=glb_path, export_format='GLB', use_selection=False)
    print(f"[+] GLB export complete: {glb_path}")

    # 8. Blend File Archive
    blend_path = os.path.join(out_dir, "scene.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"[+] Project blend file saved: {blend_path}")

    # 9. Output Numerical Ground Truth State
    state = {
        "status": "SUCCESS",
        "objects": [{"name": o.name, "type": o.type, "loc": [round(v, 2) for v in o.location]} for o in bpy.data.objects],
        "render_file": render_path,
        "glb_file": glb_path
    }
    print("SCENE_STATE:" + json.dumps(state, ensure_ascii=False))

if __name__ == "__main__":
    args = parse_args()
    build_scene(args.out_dir)
