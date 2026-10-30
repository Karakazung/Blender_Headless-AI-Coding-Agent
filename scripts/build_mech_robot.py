#!/usr/bin/env python3
"""
Stylized Low-Poly Mech Robot Generator with Procedural Rigging & QA
Builds a production-ready Low-Poly Mech character using:
  1. Hard-surface procedural geometry & bevel modifiers
  2. Principled BSDF PBR & Glow materials
  3. Single-hierarchy Armature Rigging (Root, Spine, Head, Arms, Legs)
  4. Comprehensive 4-Tier QA Verification (Polycount, Grounding, Interpenetration, GLB Export)
  5. 4-in-1 Delivery (.blend, .glb, preview .png, qa_report.json, components.json)
"""

import os
import sys
import math
import json
import argparse

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

def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Headless Mech Robot Builder")
    parser.add_argument("--out-dir", default="outputs/mech_robot", help="Output directory")
    parser.add_argument("--with-rig", action="store_true", default=True, help="Generate skeletal armature rig")
    return parser.parse_args(argv)

def clean_scene():
    """ล้างข้อมูลฉากเดิมออกทั้งหมด"""
    bpy.ops.wm.read_factory_settings(use_empty=True)

def add_bevel(obj, width=0.02, segments=2):
    """เพิ่ม Bevel Modifier เพื่อลบมุมขอบคมตามหลัก Hard-Surface"""
    bevel = obj.modifiers.new(name="Bevel", type='BEVEL')
    bevel.width = width
    bevel.segments = segments

def build_mech_character(profile: dict):
    """สร้างชิ้นส่วนเรขาคณิตและวัสดุของหุ่นยนต์ Mech"""
    # 1. สร้าง Materials ด้วย Principled BSDF
    mat_armor = shader_generator.create_principled_material(
        name="Mat_MechArmor",
        base_color=(0.15, 0.22, 0.32, 1.0),  # Steel Navy
        metallic=0.85,
        roughness=0.3
    )
    mat_joint = shader_generator.create_principled_material(
        name="Mat_MechJoint",
        base_color=(0.06, 0.07, 0.08, 1.0),  # Dark Carbon
        metallic=0.9,
        roughness=0.45
    )
    mat_glow = shader_generator.create_principled_material(
        name="Mat_MechVisorGlow",
        base_color=(0.0, 0.85, 1.0, 1.0),    # Cyan Neon Glow
        metallic=0.0,
        roughness=0.1,
        emission_color=(0.0, 0.85, 1.0, 1.0),
        emission_strength=6.0
    )
    mat_accent = shader_generator.create_principled_material(
        name="Mat_MechAccent",
        base_color=(0.95, 0.55, 0.1, 1.0),   # Warning Amber
        metallic=0.7,
        roughness=0.35
    )

    created_objects = []

    # 2. พื้นโชว์ตัวเคสสตูดิโอ (Turntable Showcase Floor §10.3)
    mat_floor = shader_generator.create_principled_material(
        name="Mat_ShowcaseFloor",
        base_color=(0.70, 0.72, 0.75, 1.0),  # Medium Neutral Studio Gray
        roughness=0.6,
        metallic=0.05
    )
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=3.2, depth=0.1, location=(0, 0, -0.05))
    floor = bpy.context.active_object
    floor.name = "Env_GroundFloor"
    floor.data.materials.append(mat_floor)
    created_objects.append(floor)

    # 3. ลำตัว (Torso)
    bpy.ops.mesh.primitive_cube_add(location=(0, 0, 1.7), scale=(0.5, 0.35, 0.55))
    torso = bpy.context.active_object
    torso.name = "Mech_Torso"
    torso.data.materials.append(mat_armor)
    add_bevel(torso, width=0.035, segments=2)
    created_objects.append(torso)

    # แผ่นเกราะหน้าอก (Chest Armor Plate)
    bpy.ops.mesh.primitive_cube_add(location=(0, -0.36, 1.78), scale=(0.38, 0.04, 0.3))
    chest = bpy.context.active_object
    chest.name = "Mech_ChestPlate"
    chest.data.materials.append(mat_accent)
    add_bevel(chest, width=0.02, segments=2)
    quality_checker.mark_side_attached(chest, torso)
    created_objects.append(chest)

    # 4. ศีรษะ (Head)
    bpy.ops.mesh.primitive_cube_add(location=(0, 0, 2.45), scale=(0.28, 0.28, 0.22))
    head = bpy.context.active_object
    head.name = "Mech_Head"
    head.data.materials.append(mat_armor)
    add_bevel(head, width=0.025, segments=2)
    quality_checker.mark_joint_attached(head, torso)
    created_objects.append(head)

    # Visor หน้ากากเรืองแสง
    bpy.ops.mesh.primitive_cube_add(location=(0, -0.29, 2.46), scale=(0.22, 0.02, 0.07))
    visor = bpy.context.active_object
    visor.name = "Mech_Visor"
    visor.data.materials.append(mat_glow)
    quality_checker.mark_side_attached(visor, head)
    created_objects.append(visor)

    # เสาอากาศสื่อสาร (Antenna)
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, location=(0.22, 0.0, 2.75), scale=(0.02, 0.02, 0.18))
    antenna = bpy.context.active_object
    antenna.name = "Mech_Antenna"
    antenna.data.materials.append(mat_joint)
    quality_checker.mark_side_attached(antenna, head)
    created_objects.append(antenna)

    # 5. กระเป๋าหลัง / Thruster Jetpack
    bpy.ops.mesh.primitive_cube_add(location=(0, 0.38, 1.72), scale=(0.35, 0.14, 0.4))
    jetpack = bpy.context.active_object
    jetpack.name = "Mech_Jetpack"
    jetpack.data.materials.append(mat_armor)
    add_bevel(jetpack, width=0.02, segments=2)
    quality_checker.mark_side_attached(jetpack, torso)
    created_objects.append(jetpack)

    # ท่อไอพ่นซ้าย-ขวา
    for side, sign in [("L", -1), ("R", 1)]:
        bpy.ops.mesh.primitive_cylinder_add(vertices=14, location=(sign * 0.2, 0.48, 1.45), scale=(0.07, 0.07, 0.14))
        thruster = bpy.context.active_object
        thruster.name = f"Mech_Thruster_{side}"
        thruster.data.materials.append(mat_joint)
        quality_checker.mark_joint_attached(thruster, jetpack)
        created_objects.append(thruster)

    # 6. แขนและข้อต่อไหล่ (Arms & Joints)
    for side, sign in [("L", -1), ("R", 1)]:
        # ข้อต่อไหล่ทรงกลม (Low-poly 12x8)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, location=(sign * 0.58, 0, 2.05), scale=(0.11, 0.11, 0.11))
        joint_sh = bpy.context.active_object
        joint_sh.name = f"Shoulder_Joint_{side}"
        joint_sh.data.materials.append(mat_joint)
        quality_checker.mark_joint_attached(joint_sh, torso)
        created_objects.append(joint_sh)

        # แขนท่อนบน
        bpy.ops.mesh.primitive_cylinder_add(vertices=14, location=(sign * 0.65, 0, 1.65), scale=(0.08, 0.08, 0.28))
        upper_arm = bpy.context.active_object
        upper_arm.name = f"UpperArm_{side}"
        upper_arm.data.materials.append(mat_armor)
        add_bevel(upper_arm, width=0.015, segments=2)
        quality_checker.mark_joint_attached(upper_arm, joint_sh)
        created_objects.append(upper_arm)

        # ข้อศอก
        bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, location=(sign * 0.65, 0, 1.32), scale=(0.08, 0.08, 0.08))
        elbow = bpy.context.active_object
        elbow.name = f"Elbow_Joint_{side}"
        elbow.data.materials.append(mat_joint)
        quality_checker.mark_assembly_mate(upper_arm, elbow)
        created_objects.append(elbow)

        # แขนท่อนล่าง
        bpy.ops.mesh.primitive_cube_add(location=(sign * 0.65, -0.05, 1.02), scale=(0.09, 0.11, 0.22))
        forearm = bpy.context.active_object
        forearm.name = f"Forearm_{side}"
        forearm.data.materials.append(mat_armor)
        add_bevel(forearm, width=0.015, segments=2)
        quality_checker.mark_assembly_mate(elbow, forearm)
        created_objects.append(forearm)

        # มือ / Hand
        bpy.ops.mesh.primitive_cube_add(location=(sign * 0.65, -0.05, 0.74), scale=(0.07, 0.09, 0.07))
        hand = bpy.context.active_object
        hand.name = f"Hand_{side}"
        hand.data.materials.append(mat_joint)
        add_bevel(hand, width=0.01, segments=2)
        quality_checker.mark_assembly_mate(forearm, hand)
        created_objects.append(hand)

    # 7. สะโพก ขา และเท้า (Hips, Legs & Feet)
    # ข้อต่อกระดูกเชิงกรานกลาง
    bpy.ops.mesh.primitive_cube_add(location=(0, 0, 1.1), scale=(0.3, 0.25, 0.12))
    pelvis = bpy.context.active_object
    pelvis.name = "Mech_Pelvis"
    pelvis.data.materials.append(mat_joint)
    add_bevel(pelvis, width=0.02, segments=2)
    quality_checker.mark_joint_attached(pelvis, torso)
    created_objects.append(pelvis)

    for side, sign in [("L", -1), ("R", 1)]:
        # ข้อต่อสะโพก
        bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, location=(sign * 0.24, 0, 1.02), scale=(0.09, 0.09, 0.09))
        hip = bpy.context.active_object
        hip.name = f"Hip_Joint_{side}"
        hip.data.materials.append(mat_joint)
        quality_checker.mark_assembly_mate(hip, pelvis)
        created_objects.append(hip)

        # ขาท่อนบน (Upper Leg)
        bpy.ops.mesh.primitive_cube_add(location=(sign * 0.24, 0, 0.76), scale=(0.12, 0.14, 0.22))
        upper_leg = bpy.context.active_object
        upper_leg.name = f"UpperLeg_{side}"
        upper_leg.data.materials.append(mat_armor)
        add_bevel(upper_leg, width=0.02, segments=2)
        quality_checker.mark_assembly_mate(upper_leg, hip)
        created_objects.append(upper_leg)

        # หัวเข่า (Knee Joint)
        bpy.ops.mesh.primitive_cylinder_add(vertices=14, location=(sign * 0.24, 0, 0.52), scale=(0.07, 0.07, 0.06))
        knee = bpy.context.active_object
        knee.name = f"Knee_Joint_{side}"
        knee.data.materials.append(mat_joint)
        quality_checker.mark_assembly_mate(knee, upper_leg)
        created_objects.append(knee)

        # ขาท่อนล่าง (Lower Leg)
        bpy.ops.mesh.primitive_cube_add(location=(sign * 0.24, 0.02, 0.30), scale=(0.13, 0.15, 0.20))
        lower_leg = bpy.context.active_object
        lower_leg.name = f"LowerLeg_{side}"
        lower_leg.data.materials.append(mat_armor)
        add_bevel(lower_leg, width=0.02, segments=2)
        quality_checker.mark_assembly_mate(lower_leg, knee)
        created_objects.append(lower_leg)

        # เท้า (Foot) - แนบระนาบพื้น Z=0 พอดี
        bpy.ops.mesh.primitive_cube_add(location=(sign * 0.24, -0.06, 0.08), scale=(0.15, 0.24, 0.08))
        foot = bpy.context.active_object
        foot.name = f"Foot_{side}"
        foot.data.materials.append(mat_joint)
        add_bevel(foot, width=0.015, segments=2)
        quality_checker.mark_assembly_mate(foot, lower_leg)
        created_objects.append(foot)

    # 7. Apply Transforms across all objects
    for obj in created_objects:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    bpy.ops.object.select_all(action='DESELECT')

    return created_objects

def create_armature_rig(character_objects):
    """สร้างโครงกระดูก Armature และเชื่อมต่อกระดูกเข้ากับชิ้นส่วนหุ่นยนต์"""
    bpy.ops.object.armature_add(location=(0, 0, 0))
    arm_obj = bpy.context.active_object
    arm_obj.name = "Armature_Mech"
    arm_data = arm_obj.data
    arm_data.name = "Mech_Skel"

    bpy.ops.object.mode_set(mode='EDIT')
    edit_bones = arm_data.edit_bones

    # Bone: Root
    root = edit_bones[0]
    root.name = "Bone_Root"
    root.head = (0, 0, 0)
    root.tail = (0, 0, 0.2)

    # Bone: Pelvis
    pelvis = edit_bones.new("Bone_Pelvis")
    pelvis.head = (0, 0, 1.0)
    pelvis.tail = (0, 0, 1.15)
    pelvis.parent = root

    # Bone: Spine/Torso
    spine = edit_bones.new("Bone_Torso")
    spine.head = (0, 0, 1.15)
    spine.tail = (0, 0, 2.25)
    spine.parent = pelvis

    # Bone: Head
    head_bone = edit_bones.new("Bone_Head")
    head_bone.head = (0, 0, 2.25)
    head_bone.tail = (0, 0, 2.8)
    head_bone.parent = spine

    # Bones: Arms
    for side, sign in [("L", -1), ("R", 1)]:
        sh = edit_bones.new(f"Bone_Shoulder_{side}")
        sh.head = (sign * 0.35, 0, 2.05)
        sh.tail = (sign * 0.65, 0, 2.05)
        sh.parent = spine

        u_arm = edit_bones.new(f"Bone_UpperArm_{side}")
        u_arm.head = (sign * 0.65, 0, 2.05)
        u_arm.tail = (sign * 0.65, 0, 1.32)
        u_arm.parent = sh

        f_arm = edit_bones.new(f"Bone_Forearm_{side}")
        f_arm.head = (sign * 0.65, 0, 1.32)
        f_arm.tail = (sign * 0.65, 0, 0.74)
        f_arm.parent = u_arm

        # Bones: Legs
        thigh = edit_bones.new(f"Bone_Thigh_{side}")
        thigh.head = (sign * 0.24, 0, 1.02)
        thigh.tail = (sign * 0.24, 0, 0.52)
        thigh.parent = pelvis

        shin = edit_bones.new(f"Bone_Shin_{side}")
        shin.head = (sign * 0.24, 0, 0.52)
        shin.tail = (sign * 0.24, 0, 0.08)
        shin.parent = thigh

        foot_b = edit_bones.new(f"Bone_Foot_{side}")
        foot_b.head = (sign * 0.24, 0, 0.08)
        foot_b.tail = (sign * 0.24, -0.25, 0.0)
        foot_b.parent = shin

    bpy.ops.object.mode_set(mode='OBJECT')

    # เชื่อมโยง Parent Bone สำหรับชิ้นส่วนหลัก
    bone_mapping = {
        "Mech_Torso": "Bone_Torso",
        "Mech_ChestPlate": "Bone_Torso",
        "Mech_Jetpack": "Bone_Torso",
        "Mech_Thruster_L": "Bone_Torso",
        "Mech_Thruster_R": "Bone_Torso",
        "Mech_Head": "Bone_Head",
        "Mech_Visor": "Bone_Head",
        "Mech_Antenna": "Bone_Head",
        "Mech_Pelvis": "Bone_Pelvis",
        "Shoulder_Joint_L": "Bone_Shoulder_L",
        "Shoulder_Joint_R": "Bone_Shoulder_R",
        "UpperArm_L": "Bone_UpperArm_L",
        "UpperArm_R": "Bone_UpperArm_R",
        "Elbow_Joint_L": "Bone_UpperArm_L",
        "Elbow_Joint_R": "Bone_UpperArm_R",
        "Forearm_L": "Bone_Forearm_L",
        "Forearm_R": "Bone_Forearm_R",
        "Hand_L": "Bone_Forearm_L",
        "Hand_R": "Bone_Forearm_R",
        "Hip_Joint_L": "Bone_Pelvis",
        "Hip_Joint_R": "Bone_Pelvis",
        "UpperLeg_L": "Bone_Thigh_L",
        "UpperLeg_R": "Bone_Thigh_R",
        "Knee_Joint_L": "Bone_Thigh_L",
        "Knee_Joint_R": "Bone_Thigh_R",
        "LowerLeg_L": "Bone_Shin_L",
        "LowerLeg_R": "Bone_Shin_R",
        "Foot_L": "Bone_Foot_L",
        "Foot_R": "Bone_Foot_R"
    }

    for obj in character_objects:
        if obj.name in bone_mapping:
            target_bone = bone_mapping[obj.name]
            obj.parent = arm_obj
            obj.parent_type = 'BONE'
            obj.parent_bone = target_bone

    return arm_obj

def setup_studio_lighting_and_camera():
    """จัดแสงสตูดิโอ 3 ทิศทาง และมุมกล้องสัดส่วนทองคำ 50mm"""
    scene = bpy.context.scene

    # Ambient World Environment Fill (Seamless Studio Gray §10.2)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("StudioWorld")
    scene.world.use_nodes = True
    nt = scene.world.node_tree
    bg_node = nt.nodes.get("Background")
    if not bg_node:
        bg_node = nt.nodes.new(type="ShaderNodeBackground")
        out_node = nt.nodes.get("World Output") or nt.nodes.new(type="ShaderNodeOutputWorld")
        nt.links.new(bg_node.outputs["Background"], out_node.inputs["Surface"])
    bg_node.inputs["Color"].default_value = (0.58, 0.60, 0.64, 1.0)
    bg_node.inputs["Strength"].default_value = 0.65

    # 1. Key Light (Warm 4000K, 380W)
    key_data = bpy.data.lights.new(name="KeyLight", type='AREA')
    key_data.energy = 380.0
    key_data.size = 3.0
    key_data.color = (1.0, 0.96, 0.90)
    key = bpy.data.objects.new(name="Lgt_KeyWarm", object_data=key_data)
    scene.collection.objects.link(key)
    key.location = (-2.8, -4.2, 4.0)

    # 2. Fill Light (Cool Neutral, 180W)
    fill_data = bpy.data.lights.new(name="FillLight", type='AREA')
    fill_data.energy = 180.0
    fill_data.size = 4.0
    fill_data.color = (0.88, 0.92, 1.0)
    fill = bpy.data.objects.new(name="Lgt_FillNeutral", object_data=fill_data)
    scene.collection.objects.link(fill)
    fill.location = (3.8, -3.2, 2.6)

    # 3. Rim Light (Cool Blue Edge, 240W)
    rim_data = bpy.data.lights.new(name="RimLight", type='AREA')
    rim_data.energy = 240.0
    rim_data.size = 2.0
    rim_data.color = (0.75, 0.88, 1.0)
    rim = bpy.data.objects.new(name="Lgt_RimCool", object_data=rim_data)
    scene.collection.objects.link(rim)
    rim.location = (0.0, 3.8, 3.2)

    # 4. Camera (50mm เลนส์มาตรฐาน สัดส่วนตัวหุ่นกิน 70% ของเฟรม)
    cam_data = bpy.data.cameras.new(name="MechCamera")
    cam_data.lens = 50.0
    cam = bpy.data.objects.new(name="MechCamera", object_data=cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.location = (0.0, -5.8, 1.45)

    direction = mathutils.Vector((0, 0, 1.45)) - cam.location
    cam.rotation_mode = 'QUATERNION'
    cam.rotation_quaternion = direction.to_track_quat("-Z", "Y")

def export_and_qa(out_dir: str, profile_name: str = "character"):
    """เรนเดอร์ภาพ ส่งออกโมเดล และรันชุดทดสอบคุณภาพ 4-Tier QA"""
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    profile = profile_loader.load_profile(profile_name)
    scene = bpy.context.scene

    # Cycles CPU 6-thread render config
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = 6
    scene.cycles.samples = 32
    scene.render.resolution_x = 960
    scene.render.resolution_y = 960
    scene.render.resolution_percentage = 100

    render_path = os.path.abspath(os.path.join(out_dir, "mech_robot_preview.png"))
    scene.render.filepath = render_path
    bpy.ops.render.render(write_still=True)
    print(f"[+] Render complete: {render_path}")

    glb_path = os.path.abspath(os.path.join(out_dir, "mech_robot.glb"))
    blend_path = os.path.abspath(os.path.join(out_dir, "mech_robot.blend"))
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"[+] Blend project file saved: {blend_path}")

    # รัน Master QA Hard Gates
    qa_report = quality_checker.run_full_qa_audit(
        render_image_path=render_path,
        profile_name_or_dict=profile,
        glb_export_path=glb_path
    )
    qa_report_path = os.path.join(out_dir, "qa_report.json")
    with open(qa_report_path, "w", encoding="utf-8") as f:
        json.dump(qa_report, f, indent=2, ensure_ascii=False)
    print(f"[+] QA Report written: {qa_report_path}")

    # จัดทำ Components Table (Hierarchy Level 4)
    components = {
        "character_name": "Mech_Titan_V1",
        "profile": profile_name,
        "hierarchy_depth": 4,
        "components": [
            {
                "name": "Torso_Core",
                "subcomponents": ["Mech_Torso", "Mech_ChestPlate", "Mech_Jetpack", "Mech_Thruster_L", "Mech_Thruster_R"]
            },
            {
                "name": "Head_Unit",
                "subcomponents": ["Mech_Head", "Mech_Visor", "Mech_Antenna"]
            },
            {
                "name": "Arm_Units",
                "subcomponents": ["Shoulder_Joint_L/R", "UpperArm_L/R", "Elbow_Joint_L/R", "Forearm_L/R", "Hand_L/R"]
            },
            {
                "name": "Locomotion_Unit",
                "subcomponents": ["Mech_Pelvis", "Hip_Joint_L/R", "UpperLeg_L/R", "Knee_Joint_L/R", "LowerLeg_L/R", "Foot_L/R"]
            }
        ]
    }
    comp_path = os.path.join(out_dir, "components.json")
    with open(comp_path, "w", encoding="utf-8") as f:
        json.dump(components, f, indent=2, ensure_ascii=False)
    print(f"[+] Components structure saved: {comp_path}")

    return qa_report

def main():
    args = parse_args()
    print("=" * 60)
    print("   HEADLESS MECH ROBOT GENERATION & RIGGING PIPELINE")
    print("=" * 60)

    clean_scene()
    prof = profile_loader.load_profile("character")
    objs = build_mech_character(prof)
    print(f"[+] Generated {len(objs)} mech mesh components.")

    if args.with_rig:
        arm = create_armature_rig(objs)
        print(f"[+] Created skeletal armature rig with {len(arm.data.bones)} bones.")

    setup_studio_lighting_and_camera()
    qa = export_and_qa(args.out_dir, "character")
    
    print("\n[+] SUMMARY:")
    print(f"    QA Passed : {qa['qa_passed']}")
    print(f"    Total Tris: {qa['summary']['total_tris']} (Budget: {prof['polycount_budget']['max_tris']})")
    print(f"    Output Dir: {os.path.abspath(args.out_dir)}")

if __name__ == "__main__":
    main()
