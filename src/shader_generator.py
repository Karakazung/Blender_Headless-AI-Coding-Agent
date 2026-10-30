#!/usr/bin/env python3
"""
Procedural Shader Generator & glTF 2.0 Export Safety Checker
Provides standard BPY functions for procedural material creation with Principled BSDF,
and audits material nodes for glTF 2.0 / Godot 4.x export compatibility.
"""

from typing import Dict, Any, List, Optional, Tuple

try:
    import bpy
except ImportError:
    bpy = None

GLTF_UNSUPPORTED_NODES = {
    "ShaderNodeShaderToRGB": "EEVEE-only node; cannot export directly to standard glTF PBR without baking.",
    "ShaderNodeVolumeScatter": "Volumetric shader; not supported in glTF 2.0 standard mesh export.",
    "ShaderNodeVolumeAbsorption": "Volumetric shader; not supported in glTF 2.0 standard mesh export.",
    "ShaderNodeHoldout": "Holdout shader is unsupported in real-time glTF runtime.",
    "ShaderNodeDisplacement": "True displacement is ignored by glTF exporter unless baked to normal map."
}

def create_principled_material(
    name: str,
    base_color: Tuple[float, float, float, float] = (0.7, 0.7, 0.7, 1.0),
    roughness: float = 0.5,
    metallic: float = 0.0,
    specular: float = 0.5,
    emission_color: Optional[Tuple[float, float, float, float]] = None,
    emission_strength: float = 1.0
):
    """
    สร้าง Material ด้วยโหนด Principled BSDF มาตรฐานที่เข้ากันได้กับ glTF 2.0 100%
    """
    if bpy is None:
        raise RuntimeError("Blender bpy module is required to create materials.")

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # เคลียร์โหนดเดิม
    nodes.clear()

    # สร้าง Material Output และ Principled BSDF
    output_node = nodes.new(type="ShaderNodeOutputMaterial")
    output_node.location = (300, 0)

    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    links.new(bsdf.outputs["BSDF"], output_node.inputs["Surface"])

    # กำหนดค่าตามเวอร์ชัน Blender
    if "Base Color" in bsdf.inputs:
        bsdf.inputs["Base Color"].default_value = base_color
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = roughness
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = metallic

    # Specular / IOR handling
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = specular
    elif "Specular" in bsdf.inputs:
        bsdf.inputs["Specular"].default_value = specular

    # Emission handling
    if emission_color is not None:
        if "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = emission_color
        elif "Emission" in bsdf.inputs:
            bsdf.inputs["Emission"].default_value = emission_color
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = emission_strength

    return mat

def attach_procedural_color_ramp(
    mat,
    color_stop_a: Tuple[float, float, float, float],
    color_stop_b: Tuple[float, float, float, float],
    noise_scale: float = 15.0
):
    """
    เพิ่มโหนด Texture Coordinate + Noise + ColorRamp เชื่อมต่อเข้า Base Color
    """
    if bpy is None or not mat.use_nodes:
        return

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if not bsdf:
        return

    tex_coord = nodes.new(type="ShaderNodeTexCoord")
    tex_coord.location = (-600, 0)

    noise = nodes.new(type="ShaderNodeTexNoise")
    noise.location = (-400, 0)
    noise.inputs["Scale"].default_value = noise_scale
    links.new(tex_coord.outputs["Object"], noise.inputs["Vector"])

    ramp = nodes.new(type="ShaderNodeValToRGB")
    ramp.location = (-200, 0)
    ramp.color_ramp.elements[0].color = color_stop_a
    ramp.color_ramp.elements[1].color = color_stop_b
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])

    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

def audit_material_nodes(material) -> Dict[str, Any]:
    """
    ตรวจสอบความเข้ากันได้ของโหนดใน Material สำหรับการ Export ไปยัง glTF 2.0 / Godot 4.x
    """
    warnings = []
    has_principled = False
    has_output = False
    node_types = []

    if not hasattr(material, "use_nodes") or not material.use_nodes or material.node_tree is None:
        return {
            "material": material.name if hasattr(material, "name") else str(material),
            "compatible": True,
            "status": "PASS_SIMPLE_MATERIAL",
            "warnings": []
        }

    for node in material.node_tree.nodes:
        node_types.append(node.type)
        if node.type == "BSDF_PRINCIPLED":
            has_principled = True
        elif node.type == "OUTPUT_MATERIAL":
            has_output = True

        if node.bl_idname in GLTF_UNSUPPORTED_NODES:
            warnings.append(f"UNSUPPORTED_NODE [{node.bl_idname} ({node.name})]: {GLTF_UNSUPPORTED_NODES[node.bl_idname]}")

    if not has_output:
        warnings.append("MISSING_OUTPUT: Material has no Material Output node.")
    if not has_principled:
        warnings.append("NON_PRINCIPLED: Material is not using Principled BSDF; glTF exporter may drop surface shaders.")

    compatible = len(warnings) == 0

    return {
        "material": material.name,
        "compatible": compatible,
        "status": "PASS" if compatible else "WARN_GLTF_INCOMPATIBLE",
        "warnings": warnings,
        "total_nodes": len(node_types)
    }

if __name__ == "__main__":
    print("Shader Generator module loaded successfully.")
