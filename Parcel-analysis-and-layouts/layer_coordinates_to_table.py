import arcpy
import os

# Parameters
layers = arcpy.GetParameterAsText(0)
output_geodatabase = arcpy.GetParameterAsText(1)

# Enable overwrite to prevent errors if running multiple times
arcpy.env.overwriteOutput = True

# Get reference to the active project and map to load tables later
try:
    aprx = arcpy.mp.ArcGISProject("CURRENT")
    active_map = aprx.activeMap
except Exception:
    active_map = None

dataset_list = [lyr.strip("'") for lyr in layers.split(";") if lyr]

for dataset in dataset_list:
    try:
        # Get description
        desc = arcpy.Describe(dataset)
        spatial_ref = desc.spatialReference
        shape_type = desc.shapeType

        # Check coordinate system (EPSG:2100 is GGRS87 / Greek Grid)
        if spatial_ref.factoryCode != 2100:
            raise ValueError(
                f"Error: {dataset} is in {spatial_ref.name} (EPSG:{spatial_ref.factoryCode}). "
                "Layer must be in EPSG:2100."
            )

        # Prepare output table
        base_name = os.path.splitext(os.path.basename(dataset))[0]
        output_table_name = f"{base_name}_KORYFES"
        output_table_path = os.path.join(output_geodatabase, output_table_name)

        # Create table
        arcpy.management.CreateTable(output_geodatabase, output_table_name)

        # Add fields (Renamed to X and Y)
        arcpy.management.AddField(output_table_path, "ORIG_FID", "LONG")
        arcpy.management.AddField(output_table_path, "PART_NUM", "LONG")
        arcpy.management.AddField(output_table_path, "ΚΟΡΥΦΗ", "LONG")
        arcpy.management.AddField(output_table_path, "X", "DOUBLE")
        arcpy.management.AddField(output_table_path, "Y", "DOUBLE")

        # Open cursors
        insert_fields = ["ORIG_FID", "PART_NUM", "ΚΟΡΥΦΗ", "X", "Y"]

        with arcpy.da.InsertCursor(output_table_path, insert_fields) as insert_cursor:
            with arcpy.da.SearchCursor(dataset, ["OID@", "SHAPE@"]) as search_cursor:
                for row in search_cursor:
                    oid = row[0]
                    geometry = row[1]

                    if not geometry:
                        continue

                    # HANDLE POINTS (No iteration)
                    if shape_type == 'Point':
                        pt = geometry.firstPoint
                        insert_cursor.insertRow([
                            oid, 0, 1,
                            round(pt.X, 3),
                            round(pt.Y, 3)
                        ])

                    # HANDLE MULTIPOINTS (Iterate points directly)
                    elif shape_type == 'Multipoint':
                        vertex_num = 1
                        for pt in geometry:
                            insert_cursor.insertRow([
                                oid, 0, vertex_num,
                                round(pt.X, 3),
                                round(pt.Y, 3)
                            ])
                            vertex_num += 1

                    # HANDLE POLYGONS / LINES (Iterate Parts -> Points)
                    else:
                        part_num = 0
                        for part in geometry:
                            vertex_num = 1
                            for point in part:
                                if point:  # Check for interior rings (None values)
                                    insert_cursor.insertRow([
                                        oid, part_num, vertex_num,
                                        round(point.X, 3),
                                        round(point.Y, 3)
                                    ])
                                    vertex_num += 1
                            part_num += 1

        arcpy.AddMessage(f"Created table: {output_table_name}")

        # Add to the active project map
        if active_map:
            active_map.addDataFromPath(output_table_path)
            arcpy.AddMessage(f"Added {output_table_name} to the map.")

    except Exception as e:
        arcpy.AddError(f"Failed to process {dataset}: {str(e)}")
        raise
