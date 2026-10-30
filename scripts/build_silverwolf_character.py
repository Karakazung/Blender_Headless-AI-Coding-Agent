#!/usr/bin/env python3
"""
build_silverwolf_character.py — Stylized Anime Character (Silver Wolf) Headless Pipeline
Part of the Blender Headless Universal AI Suite.

Implements the complete Stage A -> B -> C workflow with Self-Correction Loop:
  Stage A: Turnaround Proportion Specification (1.55m height, 6.5-head anime ratio, A-Pose)
  Stage B: Procedural Character Base Mesh + Spiral Drill Ponytail + Tactical Props + 18-Bone Armature
  Stage C: 4-Tier Geometry QA + Calibrated Exposure Gate with Automatic Energy Self-Correction
  Stage D: 4-in-1 Delivery (.blend, .glb, preview .png, overlay .png, qa_report.json, components.json)
"""

import os
import sys
import math
import json
import argparse
from typing import Any, List, Dict, Tuple, Optional

# Resolve local src package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    import bpy
    import bmesh
    import mathutils
    from mathutils import Vector, Matrix
except ImportError:
    print("[!] This script must be run via Blender Headless: blender --background --python <script>")
    sys.exit(1)

from src import quality_checker
from src import profile_loader
from src import shader_generator
from src import blueprint_verifier


# ==============================================================================
# STAGE A: TURNAROUND ANATOMY & PROPORTION SPECIFICATION (1.55m Anime A-Pose)
# ==============================================================================

STAGE_A_SPEC = {
    "character_name": "SilverWolf_Stylized_Anime",
    "target_height_m": 1.55,
    "pose_type": "A-Pose (40 deg arm spread)",
    "proportions_z": {
        "ground_base": 0.00,
        "boot_top": 0.28,
        "knee_center": 0.44,
        "crotch_pelvis": 0.78,
        "waist_navel": 0.94,
        "chest_sternum": 1.15,
        "shoulder_line": 1.24,
        "neck_base": 1.28,
        "head_center": 1.41,
        "head_crown": 1.55,
        "ribbon_tip": 1.68
    },
    "exposure_preset": "studio"
}


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Headless Anime Character (Silver Wolf) Builder")
    parser.add_argument("--image", default="", help="Optional reference turnaround sheet path")
    parser.add_argument("--out-dir", default="outputs/Blender/Model/silverwolf_character", help="Output directory")
    parser.add_argument("--profile", default="character", help="QA Profile name (default: character)")
    parser.add_argument("--max-retries", type=int, default=3, help="Max self-correction render iterations")
    return parser.parse_args(argv)


def clean_scene():
    """Reset Blender scene to empty metric state"""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.system = 'METRIC'
    bpy.context.scene.unit_settings.length_unit = 'METERS'


def add_bevel(obj, width=0.006, segments=2):
    """Apply clean bevel modifier for stylized hard-surface & apparel edges"""
    bevel = obj.modifiers.new(name="Bevel", type='BEVEL')
    bevel.width = width
    bevel.segments = segments


def build_helical_drill_hair(
    name: str,
    start_pos: Tuple[float, float, float],
    length: float = 0.52,
    top_radius: float = 0.055,
    bottom_radius: float = 0.015,
    spiral_radius: float = 0.032,
    turns: float = 3.5,
    steps: int = 28,
    ring_verts: int = 8,
    mat: Any = None
) -> Any:
    """
    Constructs Silver Wolf's signature spiral drill ponytail using BMesh lofting
    along a tapered helical trajectory.
    """
    mesh = bpy.data.meshes.new(name + "_Mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)

    bm = bmesh.new()
    sx, sy, sz = start_pos

    rings = []
    for i in range(steps + 1):
        t = i / float(steps)
        # Vertical drop along Z, slight backward sweep along +Y
        z = sz - t * length
        angle_helix = t * turns * 2.0 * math.pi
        # Envelope of spiral widens in middle and tapers at tip
        env = math.sin(t * math.pi)
        cx = sx + math.cos(angle_helix) * spiral_radius * env
        cy = sy + 0.04 * t + math.sin(angle_helix) * spiral_radius * env

        # Cross-section tube radius tapers smoothly toward the tip
        r_tube = top_radius * (1.0 - 0.75 * t) * (0.6 + 0.4 * math.sin(t * math.pi * 0.8 + 0.3))
        r_tube = max(bottom_radius * (1.0 - 0.5 * t), r_tube)

        ring = []
        for s in range(ring_verts):
            theta = (2.0 * math.pi * s) / ring_verts
            # Slight star/ribbonfluting on hair lock
            flute = 1.0 + 0.12 * math.cos(2 * theta)
            vx = cx + r_tube * flute * math.cos(theta)
            vy = cy + r_tube * flute * math.sin(theta)
            vz = z
            ring.append(bm.verts.new((vx, vy, vz)))
        rings.append(ring)

    # Stitch quad rings
    for i in range(steps):
        r1 = rings[i]
        r2 = rings[i + 1]
        for s in range(ring_verts):
            s_next = (s + 1) % ring_verts
            bm.faces.new([r1[s], r1[s_next], r2[s_next], r2[s]])

    # Cap top and bottom
    top_center = bm.verts.new((sx, sy, sz + 0.01))
    for s in range(ring_verts):
        s_next = (s + 1) % ring_verts
        bm.faces.new([rings[0][s_next], rings[0][s], top_center])

    tip_pos = (sx, sy + 0.04, sz - length - 0.015)
    bot_center = bm.verts.new(tip_pos)
    for s in range(ring_verts):
        s_next = (s + 1) % ring_verts
        bm.faces.new([rings[-1][s], rings[-1][s_next], bot_center])

    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()

    for p in mesh.polygons:
        p.use_smooth = True
    if mat:
        obj.data.materials.append(mat)
    return obj


# ==============================================================================
# STAGE B: CALIBRATED BUILDING (CHARACTER BASE + APPAREL + PROPS + RIG)
# ==============================================================================

def setup_character_materials() -> Dict[str, Any]:
    """Creates glTF-compatible PBR materials matching Silver Wolf's turnaround palette"""
    mats = {
        "skin": shader_generator.create_principled_material(
            "Mat_AnimeSkin", base_color=(0.96, 0.89, 0.86, 1.0), metallic=0.0, roughness=0.65, specular=0.25
        ),
        "hair_silver": shader_generator.create_principled_material(
            "Mat_SilverHair", base_color=(0.72, 0.76, 0.84, 1.0), metallic=0.1, roughness=0.45, specular=0.4
        ),
        "hair_cyan_tip": shader_generator.create_principled_material(
            "Mat_HairCyanAccent", base_color=(0.38, 0.68, 0.88, 1.0), metallic=0.15, roughness=0.4,
            emission_color=(0.2, 0.55, 0.85, 1.0), emission_strength=0.6
        ),
        "jacket_navy": shader_generator.create_principled_material(
            "Mat_JacketNavy", base_color=(0.12, 0.13, 0.20, 1.0), metallic=0.2, roughness=0.55
        ),
        "accent_violet": shader_generator.create_principled_material(
            "Mat_VioletTrim", base_color=(0.42, 0.38, 0.76, 1.0), metallic=0.25, roughness=0.45
        ),
        "crop_white": shader_generator.create_principled_material(
            "Mat_CrispWhite", base_color=(0.92, 0.94, 0.97, 1.0), metallic=0.05, roughness=0.5
        ),
        "fur_collar": shader_generator.create_principled_material(
            "Mat_WhiteFur", base_color=(0.90, 0.92, 0.96, 1.0), metallic=0.0, roughness=0.85
        ),
        "dark_leather": shader_generator.create_principled_material(
            "Mat_DarkLeather", base_color=(0.07, 0.07, 0.09, 1.0), metallic=0.35, roughness=0.45
        ),
        "gun_metal": shader_generator.create_principled_material(
            "Mat_CyberMetal", base_color=(0.22, 0.25, 0.30, 1.0), metallic=0.85, roughness=0.28
        ),
        "visor_lens": shader_generator.create_principled_material(
            "Mat_IridescentVisor", base_color=(0.98, 0.28, 0.58, 1.0), metallic=0.1, roughness=0.15,
            emission_color=(0.98, 0.25, 0.55, 1.0), emission_strength=2.2
        ),
        "neon_cyan": shader_generator.create_principled_material(
            "Mat_NeonCyan", base_color=(0.0, 0.88, 1.0, 1.0), metallic=0.1, roughness=0.2,
            emission_color=(0.0, 0.88, 1.0, 1.0), emission_strength=2.5
        )
    }
    return mats


def build_silverwolf_character(mats: Dict[str, Any]) -> Tuple[List[Any], Dict[str, str]]:
    """
    Builds the complete stylized Silver Wolf character in A-Pose (height 1.55m).
    Returns (list_of_mesh_objects, bone_assignment_map).
    """
    objs: List[Any] = []
    bone_map: Dict[str, str] = {}

    def reg(obj, bone_name: str, mate_obj=None, smooth=True):
        if smooth:
            for p in obj.data.polygons:
                p.use_smooth = True
        objs.append(obj)
        bone_map[obj.name] = bone_name
        if mate_obj is not None:
            quality_checker.mark_assembly_mate(obj, mate_obj)
        return obj

    # --------------------------------------------------------------------------
    # 1. PELVIS, TORSO, NECK & ANIME HEAD (Central Axis X=0)
    # --------------------------------------------------------------------------
    # Shorts / Pelvis Block (Z = 0.76 .. 0.88)
    bpy.ops.mesh.primitive_cylinder_add(vertices=14, radius=0.115, depth=0.13, location=(0, 0, 0.82))
    shorts = bpy.context.active_object
    shorts.name = "Shorts_Pelvis"
    shorts.scale = (1.05, 0.78, 1.0)
    shorts.data.materials.append(mats["dark_leather"])
    add_bevel(shorts, width=0.008, segments=1)
    reg(shorts, "Bone_Pelvis")

    #Exposed Midriff / Waist (Z = 0.88 .. 1.01)
    bpy.ops.mesh.primitive_cylinder_add(vertices=14, radius=0.088, depth=0.14, location=(0, 0, 0.94))
    waist = bpy.context.active_object
    waist.name = "Torso_Midriff"
    waist.scale = (1.0, 0.72, 1.0)
    waist.data.materials.append(mats["skin"])
    reg(waist, "Bone_Spine", mate_obj=shorts)

    # White Crop Top / Chest (Z = 1.01 .. 1.22)
    bpy.ops.mesh.primitive_cylinder_add(vertices=14, radius=0.108, depth=0.21, location=(0, -0.005, 1.11))
    chest = bpy.context.active_object
    chest.name = "Chest_CropTop"
    chest.scale = (1.06, 0.78, 1.0)
    chest.data.materials.append(mats["crop_white"])
    add_bevel(chest, width=0.01, segments=1)
    reg(chest, "Bone_Chest", mate_obj=waist)

    # Cropped Cyber Jacket Shell (Z = 0.99 .. 1.25)
    bpy.ops.mesh.primitive_cube_add(location=(0, 0.01, 1.12), scale=(0.135, 0.095, 0.13))
    jacket = bpy.context.active_object
    jacket.name = "Jacket_MainShell"
    jacket.data.materials.append(mats["jacket_navy"])
    add_bevel(jacket, width=0.015, segments=2)
    reg(jacket, "Bone_Chest", mate_obj=chest)

    # Jacket Violet Lapels (Front Left & Right)
    for side, sign in [("L", -1), ("R", 1)]:
        bpy.ops.mesh.primitive_cube_add(
            location=(sign * 0.085, -0.082, 1.13),
            rotation=(0, math.radians(sign * -12), 0),
            scale=(0.038, 0.012, 0.11)
        )
        lapel = bpy.context.active_object
        lapel.name = f"Jacket_Lapel_{side}"
        lapel.data.materials.append(mats["accent_violet"])
        add_bevel(lapel, width=0.004, segments=1)
        reg(lapel, "Bone_Chest", mate_obj=jacket)

    # Fluffy White Fur Collar (Z = 1.25)
    bpy.ops.mesh.primitive_torus_add(
        major_segments=16, minor_segments=8,
        major_radius=0.115, minor_radius=0.032,
        location=(0, 0.01, 1.255),
        rotation=(math.radians(10), 0, 0)
    )
    fur = bpy.context.active_object
    fur.name = "Jacket_FurCollar"
    fur.scale = (1.1, 0.85, 0.9)
    fur.data.materials.append(mats["fur_collar"])
    reg(fur, "Bone_Chest", mate_obj=jacket)

    # Neck & Tactical Choker (Z = 1.23 .. 1.32)
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.038, depth=0.10, location=(0, 0, 1.27))
    neck = bpy.context.active_object
    neck.name = "Neck_Column"
    neck.data.materials.append(mats["skin"])
    reg(neck, "Bone_Neck", mate_obj=chest)

    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.043, depth=0.024, location=(0, 0, 1.275))
    choker = bpy.context.active_object
    choker.name = "Neck_Choker"
    choker.data.materials.append(mats["dark_leather"])
    reg(choker, "Bone_Neck", mate_obj=neck)

    # Anime Head (Z = 1.31 .. 1.54)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=10, radius=0.115, location=(0, 0, 1.425))
    head = bpy.context.active_object
    head.name = "Head_AnimeBase"
    head.scale = (0.95, 0.98, 1.06)
    head.data.materials.append(mats["skin"])
    reg(head, "Bone_Head", mate_obj=neck)

    # --------------------------------------------------------------------------
    # 2. HAIR, BANGS, BUNNY RIBBON & SPIRAL DRILL PONYTAIL
    # --------------------------------------------------------------------------
    # Hair Scalp Dome
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=10, radius=0.124, location=(0, 0.008, 1.44))
    hair_dome = bpy.context.active_object
    hair_dome.name = "Hair_ScalpDome"
    hair_dome.scale = (0.98, 1.02, 1.04)
    hair_dome.data.materials.append(mats["hair_silver"])
    reg(hair_dome, "Bone_Head", mate_obj=head)

    # Front Swept Bangs & Side Framing Locks
    for side, sign in [("L", -1), ("R", 1)]:
        bpy.ops.mesh.primitive_cube_add(
            location=(sign * 0.075, -0.085, 1.40),
            rotation=(math.radians(8), math.radians(sign * -10), math.radians(sign * 12)),
            scale=(0.032, 0.022, 0.095)
        )
        lock = bpy.context.active_object
        lock.name = f"Hair_SideLock_{side}"
        lock.data.materials.append(mats["hair_silver"])
        add_bevel(lock, width=0.008, segments=1)
        reg(lock, "Bone_Head", mate_obj=hair_dome)

    bpy.ops.mesh.primitive_cube_add(
        location=(0.0, -0.108, 1.45),
        rotation=(math.radians(-12), 0, 0),
        scale=(0.065, 0.018, 0.055)
    )
    bangs = bpy.context.active_object
    bangs.name = "Hair_CenterBangs"
    bangs.data.materials.append(mats["hair_silver"])
    add_bevel(bangs, width=0.008, segments=1)
    reg(bangs, "Bone_Head", mate_obj=hair_dome)

    # Signature Bunny-Ear Hair Ribbons (Top Crown Z = 1.56 .. 1.68)
    for side, sign in [("L", -1), ("R", 1)]:
        bpy.ops.mesh.primitive_cube_add(
            location=(sign * 0.042, 0.02, 1.60),
            rotation=(math.radians(-10), math.radians(sign * 24), 0),
            scale=(0.024, 0.008, 0.068)
        )
        rib = bpy.context.active_object
        rib.name = f"Hair_BunnyRibbon_{side}"
        rib.data.materials.append(mats["jacket_navy"])
        add_bevel(rib, width=0.004, segments=1)
        reg(rib, "Bone_Head", mate_obj=hair_dome)

    # Iconic Spiral Drill Ponytail (Back of Head Z = 1.48 down to 0.94)
    drill_tail = build_helical_drill_hair(
        name="Hair_SpiralDrill_Ponytail",
        start_pos=(0.0, 0.11, 1.46),
        length=0.52,
        top_radius=0.062,
        bottom_radius=0.018,
        spiral_radius=0.028,
        turns=3.2,
        steps=24,
        ring_verts=8,
        mat=mats["hair_silver"]
    )
    reg(drill_tail, "Bone_Hair_Drill", mate_obj=hair_dome)

    # --------------------------------------------------------------------------
    # 3. TACTICAL VISOR SUNGLASSES (Forehead Rest Position Z = 1.49)
    # --------------------------------------------------------------------------
    bpy.ops.mesh.primitive_cube_add(location=(0, -0.105, 1.495), scale=(0.088, 0.012, 0.026))
    v_frame = bpy.context.active_object
    v_frame.name = "Visor_Frame"
    v_frame.data.materials.append(mats["dark_leather"])
    add_bevel(v_frame, width=0.003, segments=1)
    reg(v_frame, "Bone_Head", mate_obj=hair_dome)

    bpy.ops.mesh.primitive_cube_add(location=(0, -0.112, 1.495), scale=(0.082, 0.006, 0.022))
    v_lens = bpy.context.active_object
    v_lens.name = "Visor_Lens"
    v_lens.data.materials.append(mats["visor_lens"])
    add_bevel(v_lens, width=0.002, segments=1)
    reg(v_lens, "Bone_Head", mate_obj=v_frame)

    for side, sign in [("L", -1), ("R", 1)]:
        bpy.ops.mesh.primitive_cube_add(location=(sign * 0.090, -0.05, 1.495), scale=(0.006, 0.055, 0.010))
        v_arm = bpy.context.active_object
        v_arm.name = f"Visor_Arm_{side}"
        v_arm.data.materials.append(mats["dark_leather"])
        reg(v_arm, "Bone_Head", mate_obj=v_frame)

    # --------------------------------------------------------------------------
    # 4. ARMS IN 40-DEGREE A-POSE & FINGERLESS TACTICAL GLOVES
    # --------------------------------------------------------------------------
    for side, sign in [("L", -1), ("R", 1)]:
        # Puffy Jacket Shoulder Sleeve (Z = 1.18, X = +-0.18)
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=12, radius=0.058, depth=0.18,
            location=(sign * 0.19, 0.0, 1.15),
            rotation=(0, math.radians(sign * 50), 0)
        )
        sleeve = bpy.context.active_object
        sleeve.name = f"Jacket_Sleeve_{side}"
        sleeve.data.materials.append(mats["jacket_navy"])
        add_bevel(sleeve, width=0.008, segments=1)
        reg(sleeve, f"Bone_Arm_{side}", mate_obj=jacket)

        # Forearm (Z = 1.02, X = +-0.31)
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=12, radius=0.036, depth=0.18,
            location=(sign * 0.30, 0.0, 1.03),
            rotation=(0, math.radians(sign * 50), 0)
        )
        forearm = bpy.context.active_object
        forearm.name = f"Forearm_{side}"
        # Left arm has white cyber-sleeve in turnaround sheet
        forearm.data.materials.append(mats["crop_white"] if side == "L" else mats["skin"])
        reg(forearm, f"Bone_Forearm_{side}", mate_obj=sleeve)

        # Fingerless Tactical Glove (Z = 0.93, X = +-0.39)
        bpy.ops.mesh.primitive_cube_add(
            location=(sign * 0.39, 0.0, 0.94),
            rotation=(0, math.radians(sign * 50), 0),
            scale=(0.028, 0.035, 0.055)
        )
        glove = bpy.context.active_object
        glove.name = f"Tactical_Glove_{side}"
        glove.data.materials.append(mats["dark_leather"])
        add_bevel(glove, width=0.005, segments=1)
        reg(glove, f"Bone_Forearm_{side}", mate_obj=forearm)

    # --------------------------------------------------------------------------
    # 5. BELT, ASYMMETRICAL SKIRT CAPE, HOLSTER, PISTOL & LONG STRAP
    # --------------------------------------------------------------------------
    # White Tactical Belt & Gamepad Buckle (Z = 0.85)
    bpy.ops.mesh.primitive_cylinder_add(vertices=14, radius=0.122, depth=0.032, location=(0, 0, 0.85))
    belt = bpy.context.active_object
    belt.name = "Tactical_Belt"
    belt.scale = (1.06, 0.80, 1.0)
    belt.data.materials.append(mats["crop_white"])
    reg(belt, "Bone_Pelvis", mate_obj=shorts)

    bpy.ops.mesh.primitive_cylinder_add(
        vertices=12, radius=0.035, depth=0.018,
        location=(-0.05, -0.098, 0.85),
        rotation=(math.radians(90), 0, 0)
    )
    buckle = bpy.context.active_object
    buckle.name = "Controller_Buckle"
    buckle.data.materials.append(mats["visor_lens"])
    reg(buckle, "Bone_Pelvis", mate_obj=belt)

    # Left Asymmetrical Gradient Skirt Cape (X = -0.14, Z = 0.52 .. 0.84)
    bpy.ops.mesh.primitive_cube_add(
        location=(-0.135, 0.02, 0.68),
        rotation=(math.radians(6), math.radians(-14), 0),
        scale=(0.012, 0.105, 0.17)
    )
    cape = bpy.context.active_object
    cape.name = "Asym_SkirtCape_L"
    cape.data.materials.append(mats["accent_violet"])
    add_bevel(cape, width=0.004, segments=1)
    reg(cape, "Bone_Pelvis", mate_obj=shorts)

    # Right Thigh Strap, Gun Holster & Cyber Pistol (X = +0.14 .. +0.18, Z = 0.64 .. 0.78)
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.068, depth=0.024, location=(0.075, 0, 0.66))
    t_strap = bpy.context.active_object
    t_strap.name = "Thigh_Strap_R"
    t_strap.data.materials.append(mats["dark_leather"])
    reg(t_strap, "Bone_Thigh_R", mate_obj=shorts)

    bpy.ops.mesh.primitive_cube_add(location=(0.145, 0.0, 0.74), scale=(0.022, 0.048, 0.075))
    holster = bpy.context.active_object
    holster.name = "Gun_Holster_R"
    holster.data.materials.append(mats["dark_leather"])
    add_bevel(holster, width=0.004, segments=1)
    reg(holster, "Bone_Pelvis", mate_obj=shorts)

    bpy.ops.mesh.primitive_cube_add(location=(0.145, -0.01, 0.81), scale=(0.016, 0.042, 0.048))
    pistol = bpy.context.active_object
    pistol.name = "Pistol_Grip_R"
    pistol.data.materials.append(mats["gun_metal"])
    add_bevel(pistol, width=0.003, segments=1)
    reg(pistol, "Bone_Pelvis", mate_obj=holster)

    # Long Hanging Belt Ribbon Strap on Right Side (Z = 0.35 .. 0.82)
    bpy.ops.mesh.primitive_cube_add(
        location=(0.165, 0.01, 0.56),
        rotation=(0, math.radians(8), 0),
        scale=(0.006, 0.022, 0.22)
    )
    long_strap = bpy.context.active_object
    long_strap.name = "Hanging_BeltStrap_R"
    long_strap.data.materials.append(mats["crop_white"])
    reg(long_strap, "Bone_Thigh_R", mate_obj=holster)

    # --------------------------------------------------------------------------
    # 6. LEGS, CALF SHEATH & CYBER BOOTS (Grounded at Z = 0.00m)
    # --------------------------------------------------------------------------
    for side, sign in [("L", -1), ("R", 1)]:
        x_leg = sign * 0.075

        # Upper Thigh (Z = 0.44 .. 0.78)
        bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.058, depth=0.34, location=(x_leg, 0, 0.61))
        thigh = bpy.context.active_object
        thigh.name = f"Thigh_{side}"
        thigh.data.materials.append(mats["skin"])
        reg(thigh, f"Bone_Thigh_{side}", mate_obj=shorts)

        # Lower Calf (Z = 0.24 .. 0.46)
        bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.045, depth=0.22, location=(x_leg, 0.005, 0.35))
        calf = bpy.context.active_object
        calf.name = f"Calf_{side}"
        calf.data.materials.append(mats["skin"])
        reg(calf, f"Bone_Calf_{side}", mate_obj=thigh)

        # Cyber High-Top Boot Shaft (Z = 0.06 .. 0.26)
        bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.054, depth=0.20, location=(x_leg, 0.005, 0.16))
        boot_shaft = bpy.context.active_object
        boot_shaft.name = f"Boot_Shaft_{side}"
        boot_shaft.data.materials.append(mats["jacket_navy"])
        add_bevel(boot_shaft, width=0.006, segments=1)
        reg(boot_shaft, f"Bone_Calf_{side}", mate_obj=calf)

        # Boot Violet Cuff Flair (Z = 0.24)
        bpy.ops.mesh.primitive_cube_add(
            location=(x_leg, -0.045, 0.24),
            rotation=(math.radians(-15), 0, 0),
            scale=(0.045, 0.022, 0.045)
        )
        cuff = bpy.context.active_object
        cuff.name = f"Boot_CuffFlair_{side}"
        cuff.data.materials.append(mats["accent_violet"])
        add_bevel(cuff, width=0.004, segments=1)
        reg(cuff, f"Bone_Calf_{side}", mate_obj=boot_shaft)

        # Grounded Boot Sole & Foot (Z = 0.00 .. 0.08, strictly grounded at Z=0.0)
        bpy.ops.mesh.primitive_cube_add(location=(x_leg, -0.025, 0.04), scale=(0.056, 0.105, 0.04))
        boot_foot = bpy.context.active_object
        boot_foot.name = f"Boot_Foot_{side}"
        boot_foot.data.materials.append(mats["dark_leather"])
        add_bevel(boot_foot, width=0.008, segments=2)
        reg(boot_foot, f"Bone_Foot_{side}", mate_obj=boot_shaft)

        # Right Calf Tactical Knife Sheath (X = +0.13, Z = 0.28)
        if side == "R":
            bpy.ops.mesh.primitive_cube_add(location=(x_leg + 0.055, 0, 0.29), scale=(0.014, 0.028, 0.065))
            sheath = bpy.context.active_object
            sheath.name = "Calf_KnifeSheath_R"
            sheath.data.materials.append(mats["gun_metal"])
            add_bevel(sheath, width=0.003, segments=1)
            reg(sheath, "Bone_Calf_R", mate_obj=calf)

    # Apply Rotation & Scale Transforms cleanly
    for obj in objs:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    bpy.ops.object.select_all(action='DESELECT')

    return objs, bone_map


def create_character_armature(objs: List[Any], bone_map: Dict[str, str]) -> Any:
    """Builds an 18-bone skeletal rig and parents character meshes to bones"""
    bpy.ops.object.armature_add(location=(0, 0, 0))
    arm_obj = bpy.context.active_object
    arm_obj.name = "Armature_SilverWolf"
    arm_data = arm_obj.data
    arm_data.name = "SilverWolf_Skeleton"

    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm_data.edit_bones

    root = eb[0]
    root.name = "Bone_Root"
    root.head = (0, 0, 0)
    root.tail = (0, 0, 0.15)

    def add_bone(name, head, tail, parent):
        b = eb.new(name)
        b.head = head
        b.tail = tail
        b.parent = parent
        return b

    pelvis = add_bone("Bone_Pelvis", (0, 0, 0.78), (0, 0, 0.88), root)
    spine = add_bone("Bone_Spine", (0, 0, 0.88), (0, 0, 1.02), pelvis)
    chest = add_bone("Bone_Chest", (0, 0, 1.02), (0, 0, 1.24), spine)
    neck = add_bone("Bone_Neck", (0, 0, 1.24), (0, 0, 1.32), chest)
    head = add_bone("Bone_Head", (0, 0, 1.32), (0, 0, 1.55), neck)
    add_bone("Bone_Hair_Drill", (0, 0.11, 1.46), (0, 0.15, 0.94), head)

    for side, sign in [("L", -1), ("R", 1)]:
        sh = add_bone(f"Bone_Shoulder_{side}", (sign * 0.08, 0, 1.20), (sign * 0.14, 0, 1.20), chest)
        arm = add_bone(f"Bone_Arm_{side}", (sign * 0.14, 0, 1.20), (sign * 0.25, 0, 1.09), sh)
        add_bone(f"Bone_Forearm_{side}", (sign * 0.25, 0, 1.09), (sign * 0.42, 0, 0.92), arm)

        thigh = add_bone(f"Bone_Thigh_{side}", (sign * 0.075, 0, 0.78), (sign * 0.075, 0, 0.44), pelvis)
        calf = add_bone(f"Bone_Calf_{side}", (sign * 0.075, 0, 0.44), (sign * 0.075, 0, 0.08), thigh)
        add_bone(f"Bone_Foot_{side}", (sign * 0.075, 0, 0.08), (sign * 0.075, -0.10, 0.02), calf)

    bpy.ops.object.mode_set(mode='OBJECT')

    # Parent meshes to their designated bones
    for obj in objs:
        target_bone = bone_map.get(obj.name)
        if target_bone and target_bone in arm_obj.pose.bones:
            obj.parent = arm_obj
            obj.parent_type = 'BONE'
            obj.parent_bone = target_bone

    return arm_obj


def setup_calibrated_studio_rig() -> Dict[str, Any]:
    """Sets up 3-Point Studio Lighting, Seamless World Background, and 85mm Portrait Camera"""
    scene = bpy.context.scene

    if scene.world is None:
        scene.world = bpy.data.worlds.new("StudioWorld_SilverWolf")
    scene.world.use_nodes = True
    nt = scene.world.node_tree
    bg_node = nt.nodes.get("Background")
    if not bg_node:
        bg_node = nt.nodes.new(type="ShaderNodeBackground")
        out_node = nt.nodes.get("World Output") or nt.nodes.new(type="ShaderNodeOutputWorld")
        nt.links.new(bg_node.outputs["Background"], out_node.inputs["Surface"])
    bg_node.inputs["Color"].default_value = (0.55, 0.57, 0.62, 1.0)
    bg_node.inputs["Strength"].default_value = 0.68

    # Key Light (Warm Key)
    key_data = bpy.data.lights.new(name="Key_Light", type='AREA')
    key_data.energy = 160.0
    key_data.size = 1.6
    key_data.color = (1.0, 0.96, 0.92)
    key_obj = bpy.data.objects.new("Key_Light", key_data)
    scene.collection.objects.link(key_obj)
    key_obj.location = (-1.6, -2.4, 2.1)
    direction = Vector((0, 0, 0.9)) - key_obj.location
    key_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

    # Fill Light (Cool Neutral Fill)
    fill_data = bpy.data.lights.new(name="Fill_Light", type='AREA')
    fill_data.energy = 85.0
    fill_data.size = 2.0
    fill_data.color = (0.88, 0.93, 1.0)
    fill_obj = bpy.data.objects.new("Fill_Light", fill_data)
    scene.collection.objects.link(fill_obj)
    fill_obj.location = (1.9, -2.0, 1.4)
    direction = Vector((0, 0, 0.85)) - fill_obj.location
    fill_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

    # Rim Light (Cyber Violet/Cyan Rim)
    rim_data = bpy.data.lights.new(name="Rim_Light", type='AREA')
    rim_data.energy = 140.0
    rim_data.size = 1.4
    rim_data.color = (0.78, 0.85, 1.0)
    rim_obj = bpy.data.objects.new("Rim_Light", rim_data)
    scene.collection.objects.link(rim_obj)
    rim_obj.location = (0.0, 2.2, 2.1)
    direction = Vector((0, 0, 1.0)) - rim_obj.location
    rim_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

    # 85mm Portrait Camera
    cam_data = bpy.data.cameras.new(name="Main_Camera")
    cam_data.lens = 65.0
    cam_obj = bpy.data.objects.new("Main_Camera", cam_data)
    scene.collection.objects.link(cam_obj)
    scene.camera = cam_obj
    cam_obj.location = (0.0, -3.3, 0.92)
    cam_dir = Vector((0.0, 0.0, 0.84)) - cam_obj.location
    cam_obj.rotation_euler = cam_dir.to_track_quat('-Z', 'Y').to_euler()

    return {"key": key_data, "fill": fill_data, "rim": rim_data, "bg": bg_node}


def render_preview(filepath: str):
    """Renders 1024x1280 portrait preview"""
    scene = bpy.context.scene
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.resolution_x = 1024
    scene.render.resolution_y = 1280
    scene.render.filepath = filepath
    bpy.ops.render.render(write_still=True)


# ==============================================================================
# STAGE C: MASTER QA & SELF-CORRECTION EXPOSURE LOOP
# ==============================================================================

def main():
    args = parse_args()
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    print("=" * 72)
    print("▶ EXECUTING HEADLESS ANIME CHARACTER PIPELINE: STAGE A -> B -> C")
    print(f"Character: {STAGE_A_SPEC['character_name']} | Target Height: {STAGE_A_SPEC['target_height_m']}m")
    print(f"Output Directory: {out_dir}")
    print("=" * 72)

    clean_scene()
    mats = setup_character_materials()
    objs, bone_map = build_silverwolf_character(mats)
    arm_obj = create_character_armature(objs, bone_map)
    lights = setup_calibrated_studio_rig()

    render_path = os.path.join(out_dir, "silverwolf_preview.png")
    blend_path = os.path.join(out_dir, "silverwolf_character.blend")
    glb_path = os.path.join(out_dir, "silverwolf_character.glb")

    # Export GLB once prior to QA check
    bpy.ops.export_scene.gltf(
        filepath=glb_path,
        export_format='GLB',
        use_selection=False,
        export_apply=True,
        export_draco_mesh_compression_enable=True
    )

    qa_report = {}
    # Self-Correction Render Loop for Calibrated Studio Exposure
    for attempt in range(1, args.max_retries + 1):
        print(f"\n[Iteration {attempt}/{args.max_retries}] Rendering & Running 4-Tier QA...")
        render_preview(render_path)

        qa_report = quality_checker.run_full_qa_audit(
            render_image_path=render_path,
            glb_export_path=glb_path,
            profile_name_or_dict=args.profile
        )

        exp_rep = qa_report.get("exposure_audit", {})
        mean_luma = exp_rep.get("mean_luma", 135.0)
        exp_status = exp_rep.get("status", "PASS")

        print(f" - Polycount: {qa_report['summary']['total_tris']} Tris ({qa_report['summary']['polycount_status']})")
        print(f" - Collisions: {qa_report['summary']['total_collisions']} | Floating: {qa_report['summary']['total_floating']}")
        print(f" - Exposure Mean Luma: {mean_luma:.2f} (Target: 100.0 - 170.0) -> {exp_status}")

        if qa_report.get("qa_passed"):
            print(f"✓ [PASS] All QA Gates Succeeded on Iteration {attempt}!")
            break

        # Self-Correction: adjust light & world energy if exposure drifted
        if exp_status != "PASS":
            target_mid = 135.0
            factor = target_mid / max(mean_luma, 10.0)
            factor = max(0.5, min(2.0, factor))
            print(f" ! [Self-Correction] Scaling Studio Light Energies by factor {factor:.2f}...")
            lights["key"].energy *= factor
            lights["fill"].energy *= factor
            lights["rim"].energy *= factor
            lights["bg"].inputs["Strength"].default_value *= factor

    # Save Final Blend File
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"[+] Blend file saved: {blend_path}")
    print(f"[+] GLB file saved: {glb_path}")

    # Optional Blueprint Overlay against Reference Turnaround Sheet (Front View ROI)
    ref_image_path = os.path.abspath(args.image) if args.image else ""
    verification_rep = {}
    if ref_image_path and os.path.isfile(ref_image_path):
        overlay_path = os.path.join(out_dir, "blueprint_overlay.png")
        try:
            # Front view A-Pose on turnaround sheet is in left half: (15, 25, 480, 960)
            front_roi = (15, 25, 480, 960)
            verification_rep = blueprint_verifier.audit_silhouette_fidelity(
                render_image_path=render_path,
                reference_image_path=ref_image_path,
                iou_target=0.60,
                roi_reference=front_roi
            )
            blueprint_verifier.generate_blueprint_overlay(
                render_image_path=render_path,
                reference_image_path=ref_image_path,
                output_overlay_path=overlay_path,
                roi_reference=front_roi
            )
            print(f"[+] Blueprint overlay saved: {overlay_path}")
        except Exception as e:
            print(f"[WARN] Blueprint overlay skipped: {e}")

    # Save QA Report & Components Manifest
    qa_report_path = os.path.join(out_dir, "qa_report.json")
    with open(qa_report_path, "w", encoding="utf-8") as f:
        json.dump(qa_report, f, indent=2, ensure_ascii=False)

    components_manifest = {
        "character_name": STAGE_A_SPEC["character_name"],
        "target_height_m": STAGE_A_SPEC["target_height_m"],
        "armature": arm_obj.name,
        "total_bones": len(arm_obj.data.bones),
        "total_mesh_parts": len(objs),
        "total_tris": qa_report["summary"]["total_tris"],
        "qa_passed": qa_report["qa_passed"],
        "verification": verification_rep,
        "components": [
            {
                "name": o.name,
                "bone": bone_map.get(o.name, ""),
                "tris": sum(len(p.vertices) - 2 for p in o.data.polygons)
            }
            for o in objs
        ]
    }
    comp_path = os.path.join(out_dir, "components.json")
    with open(comp_path, "w", encoding="utf-8") as f:
        json.dump(components_manifest, f, indent=2, ensure_ascii=False)

    print("=" * 72)
    print(f"PIPELINE COMPLETED: {'PASS' if qa_report.get('qa_passed') else 'FAIL'}")
    print("=" * 72)


if __name__ == "__main__":
    main()
