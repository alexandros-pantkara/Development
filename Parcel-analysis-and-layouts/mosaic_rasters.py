import arcpy
import os

# 1. Get input parameters directly
# Param 0: List of Rasters (MultiValue: Raster Layer)
input_rasters_str = arcpy.GetParameterAsText(0)
# Param 1: Output Geodatabase (Workspace)
output_gdb = arcpy.GetParameterAsText(1)
# Param 2: Mosaic Name (String)
mosaic_name = arcpy.GetParameterAsText(2)
# Param 3: Number of Bands (Long)
num_bands = arcpy.GetParameterAsText(3)

# 2. Process the input list (handling semicolon separation and quotes)
input_rasters = [r.replace("'", "").replace('"', "") for r in input_rasters_str.split(";")]

# 3. Handle optional Geodatabase (use default if empty)
if not output_gdb or output_gdb == "#":
    aprx = arcpy.mp.ArcGISProject("CURRENT")
    output_gdb = aprx.defaultGeodatabase

# 4. Derive required properties from the first input raster
desc = arcpy.Describe(input_rasters[0])
spatial_ref = desc.spatialReference

arcpy.AddMessage(f"Mosaicking {len(input_rasters)} rasters into {output_gdb}\\{mosaic_name}...")

# 5. Execute the tool
output_raster_path = os.path.join(output_gdb, mosaic_name)
arcpy.management.MosaicToNewRaster(
    input_rasters=input_rasters,
    output_location=output_gdb,
    raster_dataset_name_with_extension=mosaic_name,
    coordinate_system_for_the_raster=spatial_ref,
    pixel_type='16_BIT_UNSIGNED',
    number_of_bands=num_bands,
    mosaic_method="LAST",
    mosaic_colormap_mode="FIRST"
)

arcpy.AddMessage("Mosaic completed successfully.")

# 6. Add output to active map
try:
    aprx = arcpy.mp.ArcGISProject("CURRENT")
    active_map = aprx.activeMap
    if active_map:
        new_layer = active_map.addDataFromPath(output_raster_path)
        arcpy.AddMessage(f"✓ Added mosaic '{mosaic_name}' to active map")
    else:
        arcpy.AddWarning("No active map found - mosaic created but not added to map")
except Exception as e:
    arcpy.AddWarning(f"Failed to add mosaic to map: {str(e)}")
