"""
====================================================================
Blender Add-on: Emission + Bounding Box Area + Room Lumens + Color Temp
====================================================================

Author:      3D Logic Class
Version:     1.0
Blender:     4.0+
Category:    Material

--------------------------------------------------------------------
DESCRIPTION
--------------------------------------------------------------------
This add-on provides a physically informed lighting calculator
for Blender materials, designed to simulate realistic room brightness.

It integrates material emission setup with room lighting estimation,
allowing you to:
 - Compute the emission strength from lumens and surface area.
 - Estimate room lighting needs (lux and lumens) based on room type.
 - Automatically detect room area from bounding box or walls.
 - Measure ceiling height from geometry or manual input.
 - Suggest appropriate color temperatures for different spaces.
 - Automatically apply emission or blackbody nodes to materials.

Ideal for:
 - Architectural visualization
 - Interior design rendering
 - Lighting previsualization
 - Realistic PBR-based scene setup

--------------------------------------------------------------------
HOW IT WORKS
--------------------------------------------------------------------
1. The user selects a material and inputs or calculates lighting data.
2. The add-on computes the emission strength (W/m²) for Cycles/Eevee.
3. Optional tools estimate total lumens and color temperature
   for the room based on lux standards (EN 12464-1 guidelines).

--------------------------------------------------------------------
DEPENDENCIES
--------------------------------------------------------------------
- Blender built-in modules: bpy, bmesh, mathutils
--------------------------------------------------------------------
"""

import bpy
import bmesh
from mathutils import Vector
import numpy as np


# ------------------------------------------------------------------
# Blender Add-on Metadata
# ------------------------------------------------------------------
# ==========================================================
# Blender Add-on: Emission + Room Lumens + Color Temp
# ==========================================================

bl_info = {
    "name": "Emission + Room Lumens + Color Temp",
    "author": "3D Logic Class",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "Properties > Material > Emission & Lighting Calculator",
    "description": "Calculate emission strength and room lighting with realistic lumens & color temperatures.",
    "category": "Material",
}


# ------------------------------------------------------------------
# Utility Functions
# ------------------------------------------------------------------

def get_active_material_area(obj):
    """
    Calculate the total surface area of all polygons that use the active material.

    This ensures emission strength is physically consistent
    with the actual visible surface area.

    Args:
        obj (bpy.types.Object): Mesh object to analyze.

    Returns:
        float: Total area (m²) of polygons using the active material.
    """
    if not obj or obj.type != 'MESH':
        return 0.0

    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()

    active_index = obj.active_material_index
    area = sum(face.calc_area() for face in bm.faces if face.material_index == active_index)

    bm.free()
    return area


def bounding_box_area_xy(props, context):
    """
    Compute the projected floor area of a room regardless of model rotation.

    This function analyzes the geometry of the selected wall objects
    (or the active object if none are provided) and computes the area
    of their projection onto the dominant geometric plane — typically
    the "floor" plane. This makes the result invariant to the model’s
    rotation in world space.

    Args:
        props (MaterialEmissionProperties): Property group holding references
            to the wall objects (wall_a, wall_b).
        context (bpy.types.Context): Blender context used for fallback object
            access (active_object).

    Returns:
        float: Estimated floor area in square meters.
    """
    # Collect reference objects for bounding calculation
    objects = []
    if props.wall_a:
        objects.append(props.wall_a)
    if props.wall_b:
        objects.append(props.wall_b)

    # Fallback: use active mesh if no walls are defined
    if len(objects) == 0 and context.active_object and context.active_object.type == 'MESH':
        objects = [context.active_object]

    if not objects:
        return 0.0

    # Gather all vertex coordinates in world space
    verts_world = []
    for obj in objects:
        if obj and obj.type == 'MESH':
            for v in obj.data.vertices:
                verts_world.append(obj.matrix_world @ v.co)

    # At least three vertices are required to define a plane
    if len(verts_world) < 3:
        return 0.0

    # Convert to NumPy array for geometric analysis
    pts = np.array([[v.x, v.y, v.z] for v in verts_world])

    # Compute the mean center of all points
    center = pts.mean(axis=0)

    # Subtract center to normalize for PCA
    pts_centered = pts - center

    # Principal Component Analysis (PCA) to find the dominant plane
    cov = np.cov(pts_centered.T)
    eigvals, eigvecs = np.linalg.eig(cov)

    # The eigenvector with the smallest eigenvalue corresponds to the plane normal
    normal = eigvecs[:, np.argmin(eigvals)]

    # Define two orthogonal axes lying in the plane
    axis_x = eigvecs[:, np.argmax(eigvals)]
    axis_y = np.cross(normal, axis_x)

    # Normalize the basis vectors
    axis_x /= np.linalg.norm(axis_x)
    axis_y /= np.linalg.norm(axis_y)

    # Project all 3D vertices onto the plane’s 2D coordinate system
    proj = np.array([[np.dot(p - center, axis_x), np.dot(p - center, axis_y)] for p in pts])

    # Compute the bounding rectangle in the 2D projected space
    min_x, max_x = proj[:, 0].min(), proj[:, 0].max()
    min_y, max_y = proj[:, 1].min(), proj[:, 1].max()

    # Calculate and return the area of that rectangle
    area = abs((max_x - min_x) * (max_y - min_y))
    return float(area)


def object_height(obj):
    """
    Measure the total height (Z extent) of a given mesh object.

    Useful for estimating ceiling height automatically from walls.

    Args:
        obj (bpy.types.Object): The target mesh object.

    Returns:
        float: Object height (m).
    """
    if not obj or obj.type != 'MESH':
        return 0.0

    zs = [(obj.matrix_world @ v.co).z for v in obj.data.vertices]
    return max(zs) - min(zs) if zs else 0.0


def update_ler_from_preset(self, context):
    """
    Synchronize LER (Luminous Efficacy Ratio) with selected preset.

    This ensures user-friendly light type selection while retaining
    the ability for manual override if 'Custom' is chosen.
    """
    if self.ler_preset != 'CUSTOM':
        self.ler = float(self.ler_preset)


def update_height_from_object(self, context):
    """
    Automatically update ceiling height when the user specifies a reference object.

    This allows users to link height dynamically to room geometry.
    """
    if self.height_source == 'FROM_OBJECT' and self.height_object and self.height_object.type == 'MESH':
        h = object_height(self.height_object)
        if h > 0:
            self.room_height = h


# ------------------------------------------------------------------
# Property Group
# ------------------------------------------------------------------

class MaterialEmissionProperties(bpy.types.PropertyGroup):
    """
    Central data model for storing all emission and room-lighting properties.

    Attached to bpy.types.Material as 'emission_props'.
    """

    # ----------------------------
    # Light Source Properties
    # ----------------------------
    lumens: bpy.props.FloatProperty(
        name="Lumens",
        description="Total luminous flux of the light source (lm)",
        default=850,
        min=0
    )

    ler_preset: bpy.props.EnumProperty(
        name="Light Type",
        description="Preset for luminous efficacy (lm/W)",
        items=[
            ('300', "White LED / Standard (300)", ""),
            ('250', "Warm Incandescent (250)", ""),
            ('683', "Ideal Green (683)", ""),
            ('150', "Simulate Higher Exposure – Natural Look (150)", ""),
            ('100', "Simulate Higher Exposure – Bright Room (100)", ""),
            ('50', "Simulate Higher Exposure – Very Bright (50)", ""),
            ('CUSTOM', "Custom", "")
        ],
        default='300',
        update=update_ler_from_preset
    )

    ler: bpy.props.FloatProperty(
        name="LER (lm/W)",
        description="Manual luminous efficacy (lm/W)",
        default=300,
        min=1
    )

    # ----------------------------
    # Area & Emission Strength
    # ----------------------------
    auto_area: bpy.props.BoolProperty(
        name="Use Material Area",
        description="Use surface area from active material automatically",
        default=True
    )

    area: bpy.props.FloatProperty(
        name="Area (m²)",
        description="Manual emission surface area (per light)",
        default=0.02,
        min=0.0001
    )

    num_lights: bpy.props.IntProperty(
        name="Number of Lights",
        description="Number of identical lights sharing this material",
        default=1,
        min=1
    )

    strength: bpy.props.FloatProperty(
        name="Emission Strength",
        description="Calculated emission strength (Cycles/Eevee intensity)",
        default=0.0
    )

    # ----------------------------
    # Room Geometry Properties
    # ----------------------------
    room_area_source: bpy.props.EnumProperty(
        name="Room Area Source",
        description="Select how to determine the room floor area",
        items=[('MANUAL', "Manual Input", ""), ('BOUNDING_BOX', "From Bounding Box", "")],
        default='MANUAL'
    )

    room_area: bpy.props.FloatProperty(
        name="Room Area (m²)",
        description="Total room floor area (if manual mode is used)",
        default=20,
        min=1
    )

    wall_a: bpy.props.PointerProperty(type=bpy.types.Object, name="Reference Object A")
    wall_b: bpy.props.PointerProperty(type=bpy.types.Object, name="Reference Object B")

    # ----------------------------
    # Room Height
    # ----------------------------
    height_source: bpy.props.EnumProperty(
        name="Ceiling Height Source",
        description="Select manual input or object measurement",
        items=[('MANUAL', "Manual Input", ""), ('FROM_OBJECT', "From Object Height", "")],
        default='MANUAL'
    )

    height_object: bpy.props.PointerProperty(
        name="Height Reference Object",
        type=bpy.types.Object,
        update=update_height_from_object
    )

    room_height: bpy.props.FloatProperty(
        name="Ceiling Height (m)",
        description="Height of the room in meters",
        default=2.7,
        min=0.5
    )

    # ----------------------------
    # Room Type (Lighting Context)
    # ----------------------------
    room_type: bpy.props.EnumProperty(
        name="Room Type",
        description="Determines recommended lux and color temperatures",
        items=[
            ('kitchen_gen', "Kitchen – General (250 Lux)", ""),
            ('kitchen_task', "Kitchen – Task (500 Lux)", ""),
            ('living_gen', "Living Room – General (150 Lux)", ""),
            ('living_read', "Living Room – Reading (400 Lux)", ""),
            ('bedroom_gen', "Bedroom – General (100 Lux)", ""),
            ('bedroom_read', "Bedroom – Reading (300 Lux)", ""),
            ('office', "Office (400 Lux)", ""),
            ('workshop', "Workshop (500 Lux)", ""),
            ('bathroom_gen', "Bathroom – General (250 Lux)", ""),
            ('bathroom_mirror', "Bathroom – Mirror (500 Lux)", ""),
            ('studio', "Studio/Art Room (750 Lux)", ""),
            ('dining', "Dining Room (150 Lux)", ""),
            ('hallway', "Hallway (100 Lux)", ""),
            ('laundry', "Laundry (300 Lux)", ""),
            ('gym', "Gym (300 Lux)", ""),
            ('patio', "Outdoor Patio (100 Lux)", "")
        ],
        default='living_gen'
    )

    # ----------------------------
    # Computed Results (Outputs)
    # ----------------------------
    lumens_min: bpy.props.FloatProperty(name="Min Lumens", default=0)
    lumens_avg: bpy.props.FloatProperty(name="Avg Lumens", default=0)
    lumens_max: bpy.props.FloatProperty(name="Max Lumens", default=0)

    temp_min: bpy.props.IntProperty(name="Min Kelvin", default=0)
    temp_avg: bpy.props.IntProperty(name="Avg Kelvin", default=0)
    temp_max: bpy.props.IntProperty(name="Max Kelvin", default=0)


# ------------------------------------------------------------------
# PANEL CLASS (User Interface)
# ------------------------------------------------------------------
class MATERIAL_PT_emission_calculator(bpy.types.Panel):
    """
    UI Panel displayed in the Material Properties tab.

    Provides all user controls for emission strength,
    room lighting calculations, and color temperature setup.
    """
    bl_label = "Emission & Lighting Calculator"
    bl_idname = "MATERIAL_PT_emission_calculator"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"

    def draw(self, context):
        """
        Draws the interface in Blender’s Properties Editor.
        """
        layout = self.layout
        obj = context.object
        mat = obj.active_material if obj else None

        if not obj or not mat:
            layout.label(text="Select a mesh with a material", icon='ERROR')
            return

        props = mat.emission_props
        calculated_area = bounding_box_area_xy(props, context)
        
        # New Quick Setup Section
        box = layout.box()
        box.label(text="Quick Setup", icon='LIGHT_DATA')
        box.operator("material.make_it_lamp", icon='SHADING_RENDERED')        

        # --- Room Estimation UI ---
        box = layout.box()
        box.label(text="Room Lighting Estimator", icon='LIGHT')

        box.prop(props, "room_area_source")
        sub = box.box()
        if props.room_area_source == 'MANUAL':
            sub.prop(props, "room_area")
        else:
            sub.label(text="Bounding Box Objects (XY projection):")
            sub.prop(props, "wall_a")
            sub.prop(props, "wall_b")
            if calculated_area > 0:
                sub.label(text=f"Calculated Area: {calculated_area:.2f} m²")
            else:
                sub.label(text="Select at least one valid mesh", icon='INFO')

        box.prop(props, "height_source")
        sub = box.box()
        if props.height_source == 'MANUAL':
            sub.prop(props, "room_height")
        else:
            sub.prop(props, "height_object")
            if props.height_object:
                h = object_height(props.height_object)
                sub.label(text=f"Measured Height: {h:.3f} m")

        box.prop(props, "room_type")
        box.operator("material.calc_room_lumens", icon="LIGHT_HEMI")

        if props.lumens_avg > 0:
            box.label(text=f"Lumens → {props.lumens_min:.0f} / {props.lumens_avg:.0f} / {props.lumens_max:.0f}")
            r = box.row(align=True)
            r.operator("material.use_lumens", text="Min").mode = 'MIN'
            r.operator("material.use_lumens", text="Avg").mode = 'AVG'
            r.operator("material.use_lumens", text="Max").mode = 'MAX'

        if props.temp_avg > 0:
            box.label(text=f"Color Temp → {props.temp_min}K / {props.temp_avg}K / {props.temp_max}K")
            r = box.row(align=True)
            r.operator("material.apply_temperature", text="Min").mode = 'MIN'
            r.operator("material.apply_temperature", text="Avg").mode = 'AVG'
            r.operator("material.apply_temperature", text="Max").mode = 'MAX'

        # --- Emission Section ---
        layout.separator()
        layout.label(text="Emission Calculation", icon='SHADING_RENDERED')
        layout.prop(props, "lumens")
        layout.prop(props, "ler_preset")

        row = layout.row()
        row.prop(props, "ler")
        row.enabled = (props.ler_preset == 'CUSTOM')

        layout.separator()
        layout.prop(props, "auto_area")
        sub = layout.box()
        if props.auto_area:
            material_area = get_active_material_area(obj)
            if material_area > 0:
                sub.label(text=f"Material area: {material_area:.4f} m²")
            else:
                sub.label(text="No valid polygons found", icon='ERROR')
        else:
            sub.prop(props, "area")

        layout.prop(props, "num_lights")
        layout.label(text="Note: Scale is auto-applied during strength calculation", icon='INFO')
        layout.operator("material.calc_emission_strength", icon='LIGHT')
        layout.label(text=f"Emission Strength: {props.strength:.4f}")


# ------------------------------------------------------------------
# OPERATORS
# ------------------------------------------------------------------
class MATERIAL_OT_make_it_lamp(bpy.types.Operator):
    """
    Automates the creation of a physically accurate lamp material.
    Cleans up legacy shaders and redundant Blackbody nodes to ensure a 
    fresh Principled BSDF setup with synchronized color temperature.
    """
    bl_idname = "material.make_it_lamp"
    bl_label = "Make it Lamp"
    bl_description = "Purge old nodes and setup PBR lamp properties with a single Blackbody link"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mat = context.object.active_material
        if not mat:
            self.report({'WARNING'}, "No active material found")
            return {'CANCELLED'}
        
        # Enable nodes and access the node tree
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        # 1. CLEAN SWEEP: REMOVE EXISTING SHADERS AND REDUNDANT BLACKBODY NODES
        # We iterate through a copy of the nodes list to safely remove any node 
        # that acts as a shader or a Blackbody controller. 
        # This prevents "node clutter" and overlapping nodes.
        for node in list(nodes):
            is_shader = any(output.type == 'SHADER' for output in node.outputs)
            if (is_shader and node.type != 'OUTPUT_MATERIAL') or node.type == 'BLACKBODY':
                nodes.remove(node)

        # 2. CREATE AND INITIALIZE FRESH PRINCIPLED BSDF
        # Fresh node creation ensures no leftover settings from legacy material types.
        principled = nodes.new(type='ShaderNodeBsdfPrincipled')
        principled.location = (0, 300)
        
        # Ensure a Material Output exists for the final render connection
        output_node = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL'), None)
        if not output_node:
            output_node = nodes.new(type='ShaderNodeOutputMaterial')
            output_node.location = (300, 300)
        
        # Connect the new shader to the material surface output
        links.new(principled.outputs['BSDF'], output_node.inputs['Surface'])

        # 3. APPLY PHYSICAL SURFACE PRESETS
        # Metallic 0.0: Glass and plastics are non-metallic (dielectric) materials.
        # Roughness 0.050: Low values provide the sharp, glossy reflections of a glass bulb.
        # IOR 1.450: The standard physical Index of Refraction for architectural glass.
        principled.inputs['Metallic'].default_value = 0.0
        principled.inputs['Roughness'].default_value = 0.050
        principled.inputs['IOR'].default_value = 1.450
        
        # 4. CONFIGURE CYCLES TRANSMISSION & SPECULAR
        # IOR Level 0.705: Adjusted to match the specific reflection intensity shown in references.
        if 'IOR Level' in principled.inputs:
            principled.inputs['IOR Level'].default_value = 0.705
        # Transmission Weight 1.0: Converts the surface from opaque to fully transparent for glass.
        if 'Transmission Weight' in principled.inputs:
            principled.inputs['Transmission Weight'].default_value = 1.000
            
        # 5. DISABLE SECONDARY REFLECTION LAYERS
        # Disabling Coat and Sheen ensures the glass remains clear without redundant highlights.
        if 'Coat Weight' in principled.inputs:
            principled.inputs['Coat Weight'].default_value = 0.0
        if 'Sheen Weight' in principled.inputs:
            principled.inputs['Sheen Weight'].default_value = 0.0

        # 6. SETUP A SINGLE BLACKBODY TEMPERATURE NODE
        # Creating a fresh Blackbody node to drive the light hue through physical Kelvin units.
        bb = nodes.new(type='ShaderNodeBlackbody')
        # Positioning to the left of the Principled BSDF for a clean hierarchy
        bb.location = (principled.location.x - 450, principled.location.y - 200)
        bb.inputs[0].default_value = 3500.0  # Industry standard warm white temperature
        links.new(bb.outputs[0], principled.inputs['Emission Color'])

        self.report({'INFO'}, "Material purged and PBR Lamp setup applied cleanly.")
        return {'FINISHED'}
        
class MATERIAL_OT_calc_room_lumens(bpy.types.Operator):
    """Calculate recommended lumens and color temperatures for the selected room type."""
    bl_idname = "material.calc_room_lumens"
    bl_label = "Calculate Lumens & Temperature"

    def execute(self, context):
        props = context.object.active_material.emission_props

        # Determine area source
        if props.room_area_source == 'BOUNDING_BOX':
            area = bounding_box_area_xy(props, context)
            if area <= 0:
                self.report({'WARNING'}, "Invalid bounding box area")
                return {'CANCELLED'}
            props.room_area = area

        # Update height if linked to object
        if props.height_source == 'FROM_OBJECT' and props.height_object:
            h = object_height(props.height_object)
            if h > 0:
                props.room_height = h

        area = props.room_area
        height = props.room_height

        # Lux and temperature presets per room type
        lux = {
            'kitchen_gen': [150, 250, 350], 'kitchen_task': [300, 500, 700],
            'living_gen': [100, 150, 200], 'living_read': [300, 400, 500],
            'bedroom_gen': [60, 100, 150], 'bedroom_read': [200, 300, 400],
            'office': [300, 400, 500], 'workshop': [300, 500, 700],
            'bathroom_gen': [150, 250, 350], 'bathroom_mirror': [300, 500, 700],
            'studio': [500, 750, 1000], 'dining': [100, 150, 200],
            'hallway': [50, 100, 150], 'laundry': [200, 300, 400],
            'gym': [200, 300, 400], 'patio': [50, 100, 150]
        }[props.room_type]

        temp_k = {
            'kitchen_gen': [3000, 3500, 4000],
            'kitchen_task': [4000, 4500, 5000],
            'living_gen': [2700, 3000, 3500],
            'living_read': [3000, 3500, 4000],
            'bedroom_gen': [2500, 2700, 3000],
            'bedroom_read': [2700, 3000, 3500],
            'office': [4000, 4500, 5000],
            'workshop': [4000, 5000, 6500],
            'bathroom_gen': [3000, 3500, 4000],
            'bathroom_mirror': [4000, 4500, 5000],
            'studio': [5000, 5500, 6500],
            'dining': [2700, 3000, 3500],
            'hallway': [2700, 3000, 4000],
            'laundry': [3500, 4000, 4500],
            'gym': [4000, 4500, 5000],
            'patio': [2700, 3000, 4000],
        }[props.room_type]

        # Height correction factor: slightly increases lumens for taller rooms
        h_factor = 1 + 0.05 * max(0, (height * 3.28) - 10)

        props.lumens_min = lux[0] * area * h_factor
        props.lumens_avg = lux[1] * area * h_factor
        props.lumens_max = lux[2] * area * h_factor

        props.temp_min, props.temp_avg, props.temp_max = temp_k

        return {'FINISHED'}


class MATERIAL_OT_use_lumens(bpy.types.Operator):
    """Apply calculated lumens (min, avg, or max) to the material."""
    bl_idname = "material.use_lumens"
    bl_label = "Use Lumens"
    mode: bpy.props.EnumProperty(items=[('MIN','Min',''),('AVG','Avg',''),('MAX','Max','')])

    def execute(self, context):
        props = context.object.active_material.emission_props
        val = {'MIN': props.lumens_min, 'AVG': props.lumens_avg, 'MAX': props.lumens_max}[self.mode]
        props.lumens = val
        return {'FINISHED'}


class MATERIAL_OT_apply_temperature(bpy.types.Operator):
    """Apply selected color temperature to the material’s emission or blackbody node."""
    bl_idname = "material.apply_temperature"
    bl_label = "Apply Color Temperature"
    mode: bpy.props.EnumProperty(items=[('MIN','Min',''),('AVG','Avg',''),('MAX','Max','')])

    def execute(self, context):
        mat = context.object.active_material
        if not mat or not mat.use_nodes:
            self.report({'WARNING'}, "Material must use nodes")
            return {'CANCELLED'}

        props = mat.emission_props
        temp = {'MIN': props.temp_min, 'AVG': props.temp_avg, 'MAX': props.temp_max}[self.mode]

        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        # Find or create Blackbody node
        bb = next((n for n in nodes if n.type == 'BLACKBODY'), None)
        if not bb:
            bb = nodes.new("ShaderNodeBlackbody")
            bb.location = (-300, 0)

        bb.inputs[0].default_value = temp

        # Link to Principled BSDF Emission input
        principled = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if principled:
            links.new(bb.outputs["Color"], principled.inputs["Emission Color"])
            self.report({'INFO'}, f"Applied {temp}K to Emission Color")
        else:
            self.report({'INFO'}, f"Created/updated Blackbody node with {temp}K")

        return {'FINISHED'}


class MATERIAL_OT_calc_emission_strength(bpy.types.Operator):
    """Calculate emission strength based on lumens, LER, and surface area."""
    bl_idname = "material.calc_emission_strength"
    bl_label = "Calculate Emission Strength"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if not obj or obj.type != 'MESH':
            self.report({'WARNING'}, "Select a mesh object")
            return {'CANCELLED'}

        mat = obj.active_material
        if not mat:
            self.report({'WARNING'}, "No active material found")
            return {'CANCELLED'}

        props = mat.emission_props

        # Apply object scale to ensure correct area computation
        selected = context.selected_objects.copy()
        active = context.active_object
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

        for o in selected:
            o.select_set(True)
        context.view_layer.objects.active = active

        # Area calculation
        area = props.area if not props.auto_area else get_active_material_area(obj)
        if area <= 0:
            self.report({'WARNING'}, "Invalid emission area")
            return {'CANCELLED'}

        total_area = area * props.num_lights
        strength = (props.lumens / props.ler) / total_area
        props.strength = strength

        # Update material nodes
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        out = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
        if not out:
            out = nodes.new("ShaderNodeOutputMaterial")

        surf = out.inputs["Surface"]
        current = surf.links[0].from_node if surf.is_linked else None

        # If Principled BSDF exists, use its Emission Strength
        if current and current.type == 'BSDF_PRINCIPLED':
            current.inputs["Emission Strength"].default_value = strength
        else:
            # Otherwise, create an Emission Shader
            em = nodes.new("ShaderNodeEmission")
            em.location = (out.location.x - 300, out.location.y)
            links.new(em.outputs["Emission"], surf)
            em.inputs["Strength"].default_value = strength

        self.report({'INFO'}, f"Emission Strength set to {strength:.4f}")
        return {'FINISHED'}


# ------------------------------------------------------------------
# REGISTRATION
# ------------------------------------------------------------------

classes = (
    MaterialEmissionProperties,
    MATERIAL_OT_make_it_lamp,
    MATERIAL_PT_emission_calculator,
    MATERIAL_OT_calc_room_lumens,
    MATERIAL_OT_use_lumens,
    MATERIAL_OT_apply_temperature,
    MATERIAL_OT_calc_emission_strength,
)


def register():
    """Register all classes and custom properties."""
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Material.emission_props = bpy.props.PointerProperty(type=MaterialEmissionProperties)


def unregister():
    """Cleanly unregister classes and remove custom properties."""
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    del bpy.types.Material.emission_props


if __name__ == "__main__":
    register()
