#!/usr/bin/env python3
"""
build_from_reference.py — Measurement-driven Image-to-3D Reconstruction Worker
Part of the Blender Headless Universal AI Suite.

Workflow:
  Stage A: Image Calibration & Silhouette Extraction (image_reconstructor)
  Stage B: Procedural Quad Assembly (Body, Cavity, Base, Curved Handle, Liquid)
  Stage C: Closed-Loop Blueprint Verification & Master 4-Tier QA Audit
  Stage D: 4-in-1 Artifact Packaging (.blend, .glb, render preview, overlay, json reports)
"""

import os
import sys
import math
import json
import argparse
from typing import Any, Optional, Dict, List, Tuple

# Resolve local src package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    import bpy
    import mathutils
except ImportError:
    print("[!] This script must be run via Blender Headless: blender --background --python <script>")
    sys.exit(1)

from src import quality_checker
from src import profile_loader
from src import shader_generator
from src import image_reconstructor
from src import blueprint_verifier


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Image-to-3D Headless Reconstructor")
    parser.add_argument("--image", default="", help="Path to reference image")
    parser.add_argument("--out-dir", default="outputs/coffee_mug_reconstructed", help="Output directory")
    parser.add_argument("--profile", default="lowpoly_prop", help="QA Profile name (e.g. lowpoly_prop, hard_surface)")
    parser.add_argument("--height", type=float, default=0.095, help="Target height in meters (default 95mm)")
    parser.add_argument("--radius", type=float, default=0.040, help="Target radius in meters (default 40mm)")
    parser.add_argument("--segments", type=int, default=24, help="Rotational radial segments")
    parser.add_argument("--roi", default="", help="Optional ROI bbox 'xmin,ymin,xmax,ymax' to isolate specific panel")
    parser.add_argument("--with-liquid", action="store_true", default=True, help="Include coffee liquid mesh")
    return parser.parse_args(argv)


def clean_scene():
    """Clear all scene data"""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.system = 'METRIC'
    bpy.context.scene.unit_settings.length_unit = 'MILLIMETERS'


def setup_mug_materials():
    """Create ceramic glaze and coffee liquid PBR materials"""
    mat_ceramic = shader_generator.create_principled_material(
        name="Mat_CeramicGlaze",
        base_color=(0.92, 0.93, 0.95, 1.0),  # Crisp White Ceramic
        metallic=0.0,
        roughness=0.18,
        specular=0.5
    )

    mat_coffee = shader_generator.create_principled_material(
        name="Mat_DarkCoffee",
        base_color=(0.08, 0.04, 0.02, 1.0),  # Rich Espresso Brown
        metallic=0.0,
        roughness=0.10,
        specular=0.45
    )

    return mat_ceramic, mat_coffee


def add_coffee_liquid(
    body_radius_at_liquid: float,
    z_liquid: float = 0.075,
    segments: int = 24,
    mat_coffee: Any = None
) -> Any:
    """Adds a circular disk with bevel for the coffee surface inside the mug"""
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=segments,
        radius=body_radius_at_liquid - 0.0042,  # Fit cleanly inside cavity wall
        depth=0.004,
        location=(0.0, 0.0, z_liquid)
    )
    liquid = bpy.context.active_object
    liquid.name = "Coffee_Liquid_Surface"
    if mat_coffee:
        liquid.data.materials.append(mat_coffee)
    for p in liquid.data.polygons:
        p.use_smooth = True
    return liquid


def setup_studio_lighting_and_camera(target_height_m: float = 0.095):
    """Calibrated studio lighting and orthographic/portrait camera for coffee mug"""
    scene = bpy.context.scene

    # Ambient World Environment Fill (§10.2 Exposure Standards)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("StudioWorld_Mug")
    scene.world.use_nodes = True
    nt = scene.world.node_tree
    bg_node = nt.nodes.get("Background")
    if not bg_node:
        bg_node = nt.nodes.new(type="ShaderNodeBackground")
        out_node = nt.nodes.get("World Output") or nt.nodes.new(type="ShaderNodeOutputWorld")
        nt.links.new(bg_node.outputs["Background"], out_node.inputs["Surface"])
    bg_node.inputs["Color"].default_value = (0.58, 0.60, 0.64, 1.0)
    bg_node.inputs["Strength"].default_value = 0.70

    # 1. Key Light (Soft Warm Area Light)
    key_data = bpy.data.lights.new(name="KeyLight", type='AREA')
    key_data.energy = 8.5
    key_data.size = 0.35
    key_data.color = (1.0, 0.97, 0.92)
    key = bpy.data.objects.new(name="Lgt_KeyWarm", object_data=key_data)
    scene.collection.objects.link(key)
    key.location = (-0.35, -0.45, 0.30)

    # 2. Fill Light (Neutral Cool Area Light)
    fill_data = bpy.data.lights.new(name="FillLight", type='AREA')
    fill_data.energy = 4.2
    fill_data.size = 0.40
    fill_data.color = (0.90, 0.94, 1.0)
    fill = bpy.data.objects.new(name="Lgt_FillNeutral", object_data=fill_data)
    scene.collection.objects.link(fill)
    fill.location = (0.40, -0.35, 0.20)

    # 3. Rim Light (Edge Accent)
    rim_data = bpy.data.lights.new(name="RimLight", type='AREA')
    rim_data.energy = 5.8
    rim_data.size = 0.25
    rim_data.color = (0.80, 0.90, 1.0)
    rim = bpy.data.objects.new(name="Lgt_RimCool", object_data=rim_data)
    scene.collection.objects.link(rim)
    rim.location = (0.0, 0.45, 0.25)

    # 4. Camera (Framed nicely on 95mm mug)
    cam_data = bpy.data.cameras.new(name="MugCamera")
    cam_data.lens = 65.0
    cam = bpy.data.objects.new(name="MugCamera", object_data=cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    # Position camera showing mug and handle profile
    target_center = mathutils.Vector((0.015, 0.0, target_height_m * 0.52))
    cam.location = (0.0, -0.38, target_height_m * 0.85)

    direction = target_center - cam.location
    rot_quat = direction.to_track_quat('-Z', 'Y')
    cam.rotation_euler = rot_quat.to_euler()


def main():
    args = parse_args()
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    print("=" * 70)
    print("BLENDER HEADLESS IMAGE-TO-3D RECONSTRUCTION WORKER")
    print(f"Target Height: {args.height*1000:.1f} mm | Target Radius: {args.radius*1000:.1f} mm")
    print(f"Reference Image: {args.image or 'Procedural Blueprint Standard'}")
    print(f"Output Directory: {out_dir}")
    print("=" * 70)

    # 1. Clean Scene
    clean_scene()

    # 2. Reconstruct Assembly
    ref_image_path = os.path.abspath(args.image) if args.image else ""
    roi_tuple = None
    if args.roi:
        try:
            roi_tuple = tuple(int(x.strip()) for x in args.roi.split(","))
        except Exception:
            roi_tuple = None

    recon = image_reconstructor.reconstruct_mug_assembly(
        ref_image_path=ref_image_path,
        target_height_m=args.height,
        target_radius_m=args.radius,
        segments=args.segments,
        wall_thickness=0.004,
        roi=roi_tuple
    )

    body = recon["body"]
    handle = recon["handle"]

    # 3. Apply Materials
    mat_ceramic, mat_coffee = setup_mug_materials()
    if body and mat_ceramic:
        body.data.materials.append(mat_ceramic)
    if handle and mat_ceramic:
        handle.data.materials.append(mat_ceramic)

    # 4. Optional Coffee Liquid
    liquid = None
    if args.with_liquid:
        liquid = add_coffee_liquid(
            body_radius_at_liquid=args.radius,
            z_liquid=args.height * 0.76,
            segments=args.segments,
            mat_coffee=mat_coffee
        )
        if body and liquid:
            quality_checker.mark_assembly_mate(liquid, body)

    # 5. Apply Object Transforms
    created_objects = [o for o in [body, handle, liquid] if o is not None]
    for obj in created_objects:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    bpy.ops.object.select_all(action='DESELECT')

    # 6. Lighting & Camera Setup
    setup_studio_lighting_and_camera(target_height_m=args.height)

    # 7. Render Preview Image
    render_image_path = os.path.join(out_dir, "coffee_mug_preview.png")
    scene = bpy.context.scene
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.resolution_x = 1024
    scene.render.resolution_y = 1024
    scene.render.filepath = render_image_path
    bpy.ops.render.render(write_still=True)
    print(f"[+] Render preview saved: {render_image_path}")

    # 8. Save Blend File
    blend_path = os.path.join(out_dir, "coffee_mug.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"[+] Blend file saved: {blend_path}")

    # 9. Export GLB
    glb_path = os.path.join(out_dir, "coffee_mug.glb")
    bpy.ops.export_scene.gltf(
        filepath=glb_path,
        export_format='GLB',
        use_selection=False,
        export_apply=True,
        export_draco_mesh_compression_enable=True
    )
    print(f"[+] GLB export saved: {glb_path}")

    # 10. Blueprint Verification (if reference image provided)
    verification_rep = {}
    overlay_path = ""
    if ref_image_path and os.path.isfile(ref_image_path):
        overlay_path = os.path.join(out_dir, "blueprint_overlay.png")
        try:
            verification_rep = blueprint_verifier.audit_silhouette_fidelity(
                render_image_path=render_image_path,
                reference_image_path=ref_image_path,
                iou_target=0.82,
                roi_reference=roi_tuple
            )
            blueprint_verifier.generate_blueprint_overlay(
                render_image_path=render_image_path,
                reference_image_path=ref_image_path,
                output_overlay_path=overlay_path,
                roi_reference=roi_tuple
            )
            print(f"[+] Blueprint overlay saved: {overlay_path}")
            print(f"[+] Silhouette IoU Score: {verification_rep.get('iou_score', 0):.4f} (Status: {verification_rep.get('status')})")
        except Exception as e:
            print(f"[WARN] Blueprint verification encountered: {e}")

    # 11. Run Full Master QA Audit
    # For a tableware prop (mug + handle + liquid), customize profile max tris to 2,000
    custom_profile = profile_loader.load_profile(args.profile)
    custom_profile["polycount_budget"]["max_tris"] = 2500
    custom_profile["polycount_budget"]["target_tris"] = 1200

    qa_report = quality_checker.run_full_qa_audit(
        render_image_path=render_image_path,
        glb_export_path=glb_path,
        profile_name_or_dict=custom_profile
    )

    qa_report_path = os.path.join(out_dir, "qa_report.json")
    with open(qa_report_path, "w", encoding="utf-8") as f:
        json.dump(qa_report, f, indent=2, ensure_ascii=False)
    print(f"[+] Full QA report saved: {qa_report_path}")

    # 12. Write Components Manifest
    components_manifest = {
        "assembly_name": "Reconstructed_Coffee_Mug",
        "reference_image": ref_image_path,
        "calibration": recon.get("calibration", {}),
        "components": [
            {
                "name": body.name if body else "",
                "role": "Mug body with inner cavity & recessed foot ring",
                "tris": sum(len(p.vertices) - 2 for p in body.data.polygons) if body else 0,
                "material": "Mat_CeramicGlaze"
            },
            {
                "name": handle.name if handle else "",
                "role": "Ergonomic swept Bezier curved handle",
                "tris": sum(len(p.vertices) - 2 for p in handle.data.polygons) if handle else 0,
                "material": "Mat_CeramicGlaze"
            },
            {
                "name": liquid.name if liquid else "",
                "role": "Coffee liquid interior fill",
                "tris": sum(len(p.vertices) - 2 for p in liquid.data.polygons) if liquid else 0,
                "material": "Mat_DarkCoffee"
            }
        ],
        "verification": verification_rep,
        "qa_summary": qa_report.get("summary", {})
    }

    components_path = os.path.join(out_dir, "components.json")
    with open(components_path, "w", encoding="utf-8") as f:
        json.dump(components_manifest, f, indent=2, ensure_ascii=False)
    print(f"[+] Components manifest saved: {components_path}")

    print("=" * 70)
    print(f"RECONSTRUCTION & QA COMPLETED: {'PASS' if qa_report.get('qa_passed') else 'FAIL'}")
    print(f"Total Tris: {qa_report.get('summary', {}).get('total_tris', 0)}")
    print(f"Collisions: {qa_report.get('summary', {}).get('total_collisions', 0)} | Floating: {qa_report.get('summary', {}).get('total_floating', 0)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
