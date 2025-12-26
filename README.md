# Emission + Room Lumens + Color Temp

**Author:** 3D Logic Class  
**Version:** v1.0  
**Blender Compatibility:** 3.0 and above  

---

## Description

**Emission + Room Lumens + Color Temp** is a Blender add-on that allows you to:

- Calculate **Emission Strength** of a material based on **Lumens and Luminous Efficacy Ratio (LER)**.  
- Estimate room lighting based on **room type, floor area, and ceiling height**.  
- Apply **recommended color temperatures (Kelvin)** for realistic lighting.  
- Automatically measure **surface area of faces using the active material** or enter it manually.

Ideal for **PBR rendering, architectural visualization, and realistic scene lighting**.

---

## Features

- Calculates **minimum, average, and maximum lumens** for different room types (kitchen, living room, office, etc.)  
- Applies **Blackbody Node** for realistic color temperature in emission  
- Supports **multiple lights**  
- Automatic room height calculation from Blender objects  
- Professional UI under **Properties → Material → Emission & Lighting Calculator**  

---

## Installation Instructions

1. Download the `.zip` file from [Google Drive / GitHub link].  
2. Open Blender → **Edit → Preferences → Add-ons → Install**  
3. Select the `.zip` file  
4. Enable the add-on  

> Note: If using auto-area calculation, it is recommended to **apply scale** on objects (Ctrl+A → Scale) for accurate calculations.

---

## Usage Instructions

1. Select a mesh object with a material  
2. Go to **Material Properties → Emission & Lighting Calculator**:  
   - Set **Lumens** and **LER (lm/W)**  
   - Choose if the room area is **manual** or **from bounding box**  
   - Select room height manually or from a reference object  
   - Choose the **room type** to get recommended lux and Kelvin values  
3. Click **Calculate Lumens & Temp**  
4. Apply recommended lumens and color temperature using the **Min / Avg / Max** buttons  
5. Finally, click **Calculate Emission Strength** to update the material  

---

## Technical Notes

- **Emission Strength Formula**:  
  \[
  Strength = \frac{Lumens / LER}{Area \times NumLights}
  \]  
- Automatically measures **surface area** from faces with the active material  
- Calculates **room floor area (XY bounding box)** from two reference objects  

---

## Version & Changelog

**v1.0** – Initial release  
- Basic lumens and room temperature calculations  
- Auto-area and manual area support  
- Blackbody Node applied to Principled BSDF  

> Planned future features:  
- HDRI preview integration  
- Advanced studio / professional lighting presets  

---

## Support / Contact

- Email: `your_email@example.com`  
- YouTube: [3D Logic Class](https://www.youtube.com/channel/...)  
- Issues / Bug reports: [GitHub Issues](https://github.com/3DLogic/Blender-Emission-Lighting-Addon/issues)

---

## License

This add-on is **FREE for personal use**.  
See [LICENSE.md] for details on open-source / commercial use.
