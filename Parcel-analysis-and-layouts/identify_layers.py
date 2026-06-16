import arcpy
import os

# 1. Get input parameters
input_polygon_features = arcpy.GetParameterAsText(0)  # Area of Interest (Polygon Layer)
input_catalog_features = arcpy.GetParameterAsText(1)  # Raster Catalog (Polygon Layer)

# Buffer
arcpy.analysis.Buffer(
    in_features=input_polygon_features,
    out_feature_class=r"memory\ΓΕΩΤΕΜΑΧΙΟ_Buffer",
    buffer_distance_or_field="300 Meters",
    line_side="FULL",
    line_end_type="ROUND",
    dissolve_option="NONE",
    dissolve_field=None,
    method="PLANAR"
)

arcpy.AddMessage("Buffer created: 300m around input polygons")

# 2. Setup Map and Group Layer
aprx = arcpy.mp.ArcGISProject("CURRENT")
m = aprx.activeMap
group_name = "Visible Layers"
target_group = m.createGroupLayer(group_name)
arcpy.AddMessage(f"Created group layer: '{group_name}'")


def get_or_create_subgroup(map_obj, parent_group, subgroup_name):
    """Return a subgroup (GroupLayer) inside parent_group with subgroup_name; create it if missing."""
    # Try to find an existing subgroup under the parent group
    for lyr in parent_group.listLayers():
        if lyr.isGroupLayer and lyr.name == subgroup_name:
            return lyr

    # Create a temp group at the map root (ArcGIS Pro creates groups at map level),
    # then copy it into the parent group, then remove the root-level temp copy.
    tmp_group = map_obj.createGroupLayer(subgroup_name)
    map_obj.addLayerToGroup(parent_group, tmp_group)
    map_obj.removeLayer(tmp_group)

    # Find and return the subgroup that now exists under parent_group
    for lyr in parent_group.listLayers():
        if lyr.isGroupLayer and lyr.name == subgroup_name:
            return lyr

    raise RuntimeError(f"Could not create/find subgroup '{subgroup_name}' under '{parent_group.name}'.")


# 4. Find Intersecting Rasters using the Catalog
arcpy.AddMessage("Selecting intersecting raster records...")
selection = arcpy.management.SelectLayerByLocation(
    in_layer=input_catalog_features,
    overlap_type="INTERSECT",
    select_features=r"memory\ΓΕΩΤΕΜΑΧΙΟ_Buffer"
)

# Count selected
selected_count = int(arcpy.GetCount_management(selection)[0])
arcpy.AddMessage(f"Found {selected_count} intersecting raster records")

# 5. Iterate through selected catalog records and add rasters
filepath_field = "filepath"
count = 0

with arcpy.da.SearchCursor(selection, [filepath_field]) as cursor:
    for row in cursor:
        raster_path = row[0]
        folder_path = os.path.dirname(raster_path) if raster_path else ""
        raster_date = os.path.basename(os.path.dirname(folder_path)) if folder_path else "Unknown_Date"

        if raster_path and os.path.exists(raster_path):
            try:
                # Create/reuse subgroup inside "Visible Layers" named after raster_date
                date_group = get_or_create_subgroup(m, target_group, raster_date)

                # Add raster then move it into the date subgroup
                new_layer = m.addDataFromPath(raster_path)

                if new_layer:
                    m.addLayerToGroup(date_group, new_layer)
                    m.removeLayer(new_layer)  # remove root-level copy
                    count += 1
                    arcpy.AddMessage(f"✓ Added: {os.path.basename(raster_path)} -> '{raster_date}' group")
                else:
                    arcpy.AddWarning(f"✗ Failed to load: {raster_path}")
            except Exception as e:
                arcpy.AddWarning(f"✗ Error adding {raster_path}: {str(e)}")
        else:
            arcpy.AddWarning(f"✗ Invalid/missing path: {raster_path}")

# Clear the selection on the catalog to be clean
arcpy.management.SelectLayerByAttribute(input_catalog_features, "CLEAR_SELECTION")

# Final summary
arcpy.AddMessage(f"Completed. Processed {selected_count} records, added {count} rasters to '{group_name}'.")
