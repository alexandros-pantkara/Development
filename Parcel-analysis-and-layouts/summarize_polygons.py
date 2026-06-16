import arcpy
import os
import pandas as pd
import numpy as np
from pathlib import Path

# Get input parameters
input_polygon_features = arcpy.GetParameterAsText(0)  # Cadastral Polygons
input_forest_features = arcpy.GetParameterAsText(1)  # Forest Cover Polygons
input_forest_fields = arcpy.GetParameterAsText(2)  # Forest Cover Field
input_epidiko_values = arcpy.GetParameterAsText(3)  # Epidiko Tmima Values
spatial_reference = arcpy.GetParameterAsText(4)  # Coordinate System
excel_output_folder = arcpy.GetParameterAsText(5)  # Excel Output Folder
output_gdb = arcpy.GetParameterAsText(6)  # Output Geodatabase
intersection_symbology = arcpy.GetParameterAsText(7)

aprx = arcpy.mp.ArcGISProject("CURRENT")
project_folder = aprx.homeFolder
templates_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template data")

# Validate input_forest_fields
valid_fields = {'KATHGORDX', 'KATHGORAL1', 'LANDTYPE'}
input_fields_list = [f.strip().strip("'\"") for f in input_forest_fields.split(';')]
invalid_fields = [f for f in input_fields_list if f not in valid_fields]

if invalid_fields:
    arcpy.AddError(
        f"Invalid field(s) in input_forest_fields: {', '.join(invalid_fields)}. Only 'KATHGORDX', 'KATHGORAL1', 'LANDTYPE' are allowed.")
    raise ValueError("Field validation failed - invalid field names provided")

arcpy.AddMessage(f"Field validation passed: {', '.join(input_fields_list)}")

if not output_gdb:
    output_gdb = aprx.defaultGeodatabase
    arcpy.AddMessage(f"Using project default geodatabase: {output_gdb}")

intermediate_dataset = os.path.join(output_gdb, "summarize_polygons_Intermediate")

# Create feature datasets with the specified coordinate system
arcpy.AddMessage("Creating feature datasets...")
if not arcpy.Exists(intermediate_dataset):
    arcpy.management.CreateFeatureDataset(output_gdb, "summarize_polygons_Intermediate",
                                          spatial_reference=spatial_reference)
if not arcpy.Exists(os.path.join(output_gdb, "ΕΠΙΔΙΚΟ_ΤΜΗΜΑ")):
    arcpy.management.CreateFeatureDataset(output_gdb, "ΕΠΙΔΙΚΟ_ΤΜΗΜΑ", spatial_reference=spatial_reference)

arcpy.AddMessage("Feature datasets created successfully.")
arcpy.AddMessage("Starting summarization process...")

# Store original forest features path to reset for each iteration if needed,
# though the original logic accumulated filters. Keeping original logic here.
original_forest_features = input_forest_features

for field in input_forest_fields.split(";"):
    arcpy.AddMessage(f"Processing field: {field}")

    # Note: This logic modifies 'input_forest_features' for subsequent iterations.
    # If independence is required, uncomment the next line:
    # input_forest_features = original_forest_features

    if field == 'KATHGORAL1':
        forest_features_info = os.path.join(output_gdb, "summarize_polygons_Intermediate", "ForestInfoFeatures_AL1")
        if arcpy.Exists(forest_features_info):
            arcpy.management.Delete(forest_features_info)
        arcpy.Select_analysis(
            in_features=input_forest_features,
            out_feature_class=forest_features_info,
            where_clause=f"{field} <> ' '"
        )
        input_forest_features = forest_features_info

    if field == 'LANDTYPE':
        forest_features_info = os.path.join(output_gdb, "summarize_polygons_Intermediate", "ForestInfoFeatures_LT")
        if arcpy.Exists(forest_features_info):
            arcpy.management.Delete(forest_features_info)
        arcpy.Select_analysis(
            in_features=input_forest_features,
            out_feature_class=forest_features_info,
            where_clause=f"{field} <> 0"
        )
        input_forest_features = forest_features_info

    row_count = int(arcpy.management.GetCount(input_forest_features)[0])

    if row_count > 0:
        out_intermediate = os.path.join(intermediate_dataset, f"Polygons_Summarize_{field}")
        out_summary_table = os.path.join(output_gdb, f"Polygons_Summarize_{field}_Table")

        # Summarize Within
        arcpy.analysis.SummarizeWithin(
            in_polygons=input_polygon_features,
            in_sum_features=input_forest_features,
            out_feature_class=out_intermediate,
            keep_all_polygons="KEEP_ALL",
            sum_fields=None,
            sum_shape="ADD_SHAPE_SUM",
            shape_unit="SQUAREMETERS",
            group_field=field,
            add_min_maj="NO_MIN_MAJ",
            add_group_percent="ADD_PERCENT",
            out_group_table=out_summary_table
        )

        arcpy.AddMessage(f"Summarization for field '{field}' completed. Creating Pivot Table (Pandas Workaround)...")

        out_summary_pivot_table = os.path.join(output_gdb, f"Polygons_Summarize_{field}_PivotTable")

        # --- PIVOT TABLE WORKAROUND START ---
        try:
            # Check if table has data
            row_count = int(arcpy.management.GetCount(out_summary_table)[0])

            if row_count > 0:
                # 1. Read the summary table
                # We need Join_ID, the group field, and the sum area
                sc_fields = ["Join_ID", field, "sum_Area_SQUAREMETERS"]

                # Using SearchCursor to load data into a list
                data = [row for row in arcpy.da.SearchCursor(out_summary_table, sc_fields)]

                # 2. Create DataFrame
                df = pd.DataFrame(data, columns=sc_fields)

                # 3. Pivot the DataFrame
                # Index: Join_ID, Columns: <field values>, Values: Area
                pivot_df = df.pivot(index="Join_ID", columns=field, values="sum_Area_SQUAREMETERS").fillna(0)

                # 4. Flatten the DataFrame
                pivot_df.reset_index(inplace=True)

                # 5. Sanitize Column Names for GDB
                new_columns = []
                type_map = []  # To build numpy dtype

                for col in pivot_df.columns:
                    if col == "Join_ID":
                        new_columns.append(col)
                        type_map.append((col, np.int32))
                    else:
                        # Validate field name (handles numbers, spaces, invalid chars)
                        safe_col = arcpy.ValidateFieldName(str(col), output_gdb)
                        new_columns.append(safe_col)
                        type_map.append((safe_col, np.float64))

                pivot_df.columns = new_columns

                # 6. Convert to Structured NumPy Array
                # We must use a structured array for NumPyArrayToTable
                # Convert values to tuples
                data_tuples = [tuple(x) for x in pivot_df.to_numpy()]
                structured_arr = np.array(data_tuples, dtype=type_map)

                # 7. Write to Table
                if arcpy.Exists(out_summary_pivot_table):
                    arcpy.management.Delete(out_summary_pivot_table)

                arcpy.da.NumPyArrayToTable(structured_arr, out_summary_pivot_table)
                arcpy.AddMessage(f"Pivot table for field '{field}' created successfully.")

            else:
                arcpy.AddWarning(f"No summary data found for field {field}. Creating empty placeholder table.")
                # Create empty table to prevent JoinField failure later
                if arcpy.Exists(out_summary_pivot_table):
                    arcpy.management.Delete(out_summary_pivot_table)
                arcpy.management.CreateTable(output_gdb, os.path.basename(out_summary_pivot_table))
                arcpy.management.AddField(out_summary_pivot_table, "Join_ID", "LONG")

        except Exception as e:
            arcpy.AddError(f"Error executing PivotTable workaround: {str(e)}")
            raise e
        # --- PIVOT TABLE WORKAROUND END ---

arcpy.AddMessage("Exporting combined summary to Excel (draft)...")

main_field = input_forest_fields.split(";")[0]
main_ptable = os.path.join(output_gdb, f"Polygons_Summarize_{main_field}_PivotTable")

# Join other pivot tables to the first one
for field in input_forest_fields.split(";")[1:]:
    join_table = os.path.join(output_gdb, f"Polygons_Summarize_{field}_PivotTable")
    if arcpy.Exists(join_table):
        arcpy.management.JoinField(
            in_data=main_ptable,
            in_field="Join_ID",
            join_table=join_table,
            join_field="Join_ID",
            fields=None,
            fm_option="NOT_USE_FM",
            field_mapping=None,
            index_join_fields="NO_INDEXES"
        )

# Cleanup join fields
# DeleteField might fail if fields don't exist, ignore errors or check existence
try:
    arcpy.management.DeleteField(
        in_table=main_ptable,
        drop_field="Join_ID_1;Join_ID_12",
        method="DELETE_FIELDS"
    )
except:
    pass  # Ignore if fields don't exist

output_excel_file = os.path.join(excel_output_folder, "Polygon Summary draft.csv")

arcpy.conversion.ExportTable(
    in_table=main_ptable,
    out_table=output_excel_file,
    where_clause="",
    use_field_alias_as_name="NOT_USE_ALIAS",
    sort_field=None
)

arcpy.AddMessage(f"Summary draft table exported to Excel file: {output_excel_file}")

# Get a list of field objects
fields = arcpy.ListFields(input_polygon_features)
field_count = len(fields)

arcpy.management.CalculateGeometryAttributes(
    in_features=input_polygon_features,
    geometry_property="Εμβαδόν AREA",
    length_unit="",
    area_unit="SQUARE_METERS",
    coordinate_system=spatial_reference,
    coordinate_format="SAME_AS_INPUT"
)

arcpy.AddMessage(f"Joining summary table with original parcel")
arcpy.management.JoinField(
    in_data=input_polygon_features,
    in_field="OBJECTID",
    join_table=output_excel_file,
    join_field="Join_ID",
    fields=None,
    fm_option="NOT_USE_FM",
    field_mapping=None,
    index_join_fields="NO_INDEXES")

arcpy.management.DeleteField(
    in_table=input_polygon_features,
    drop_field="Join_ID",
    method="DELETE_FIELDS"
)
for field in arcpy.ListFields(input_polygon_features):
    if field.type == "Double" and field.editable:
        arcpy.management.CalculateField(
            in_table=input_polygon_features,
            field=field.name,
            expression=f"round(!{field.name}!,3)",
            expression_type="PYTHON3",
            code_block="",
            field_type="DOUBLE",
            enforce_domains="NO_ENFORCE_DOMAINS"
        )

arcpy.AddMessage("Computing Epidiko Tmima")

# Reset input features for this step as per original logic
input_forest_features = arcpy.GetParameterAsText(1)
forest_only_features = os.path.join(output_gdb, "summarize_polygons_Intermediate", "ForestOnlyFeatures")
KATHGORDX = 'KATHGORDX'

if arcpy.Exists(forest_only_features):
    arcpy.management.Delete(forest_only_features)

arcpy.analysis.Select(
    in_features=input_forest_features,
    out_feature_class=forest_only_features,
    where_clause=f"{KATHGORDX} in {input_epidiko_values}"
)

desc = arcpy.Describe(input_polygon_features)
full_path = desc.catalogPath
intersect_inputs = [full_path, forest_only_features]

if desc.name != 'ΓΕΩΤΕΜΑΧΙΟ':
    epidiko_tmima = os.path.join(output_gdb, "ΕΠΙΔΙΚΟ_ΤΜΗΜΑ", f"ΕΠΙΔΙΚΟ_ΤΜΗΜΑ_{desc.name}")
    clipped_forest_cover = os.path.join(output_gdb, f"ΓΕΩΤΕΜΑΧΙΟ_ΜΟΡΦΕΣ_ΔΧ_{desc.name}")
    arcpy.AddMessage("Layer name not ΓΕΩΤΕΜΑΧΙΟ-> using custom names")
else:
    epidiko_tmima = os.path.join(output_gdb, "ΕΠΙΔΙΚΟ_ΤΜΗΜΑ", "ΕΠΙΔΙΚΟ_ΤΜΗΜΑ")
    clipped_forest_cover = os.path.join(output_gdb, "ΓΕΩΤΕΜΑΧΙΟ_ΜΟΡΦΕΣ_ΔΧ")
    arcpy.AddMessage("Layer name is ΓΕΩΤΕΜΑΧΙΟ-> using standard names")

if arcpy.Exists(epidiko_tmima):
    arcpy.management.Delete(epidiko_tmima)

arcpy.analysis.Intersect(
    in_features=intersect_inputs,
    out_feature_class=epidiko_tmima,
    join_attributes="ALL",
    cluster_tolerance=None,
    output_type="INPUT"
)

desc = arcpy.Describe(input_polygon_features)
fc_basename = desc.featureClass.name     # just the name

arcpy.AddMessage("Deleting redundant fields for Epidiko Tmima...")
arcpy.management.DeleteField(
    in_table=epidiko_tmima,
    drop_field=f"FID_{fc_basename};NOMOS;OTA;KATHGORDX;KATHGORAL1;LANDTYPE",
    method="KEEP_FIELDS"
)

arcpy.AddMessage("Epidiko Tmima computation completed. Applying symbology and adding to map...")

arcpy.AddMessage("Exporting combined summary to Excel (final)...")

output_excel_file = os.path.join(excel_output_folder, "Polygon Summary final.csv")

gewtemaxio_name = Path(input_polygon_features).stem
arcpy.conversion.ExportTable(
    in_table=input_polygon_features,
    out_table=output_excel_file,
    where_clause="",
    use_field_alias_as_name="NOT_USE_ALIAS",
    field_mapping=f'ID "ID" true true false 255 Text 0 0,First,#,{input_polygon_features},OBJECTID,-1,-1;Εμβαδόν "Εμβαδόν" true true false 8 Float 0 0,First,#,{gewtemaxio_name},Εμβαδόν,-1,-1;ΑΑ "ΑΑ" true true false 8 Float 0 0,First,#,{gewtemaxio_name},ΑΑ,-1,-1;ΔΔ "ΔΔ" true true false 8 Float 0 0,First,#,{gewtemaxio_name},ΔΔ,-1,-1',
    sort_field=None
)
arcpy.AddMessage(f"Summary table exported to Excel file: {output_excel_file}")
try:
    active_map = aprx.activeMap
    if active_map:
        # Define path to the symbology file
        out_dataset_name = Path(epidiko_tmima).stem
        symbology_file = os.path.join(templates_folder, "ΕΠΙΔΙΚΟ_ΤΜΗΜΑ_s.lyrx")

        if os.path.exists(symbology_file):
            # 1. Load the Layer File (.lyrx) as an object
            lyr_doc = arcpy.mp.LayerFile(symbology_file)
            arcpy.AddMessage("Applying symbology from {}".format(symbology_file))

            # 2. Get the first layer in the .lyrx
            template_layer = lyr_doc.listLayers()[0]

            # 3. Update the Connection Properties to point to the new data
            new_connection_info = {
                'workspace_factory': 'File Geodatabase',
                'connection_info': {'database': output_gdb},
                'dataset': out_dataset_name
            }

            template_layer.updateConnectionProperties(
                current_connection_info=template_layer.connectionProperties,
                new_connection_info=new_connection_info
            )

            # 4. Find the input polygon layer in the map
            input_polygon_layer = None
            input_polygon_name = os.path.basename(input_polygon_features)
            for lyr in active_map.listLayers():
                is_match = lyr.name == input_polygon_name
                if not is_match and lyr.supports("dataSource"):
                    is_match = lyr.dataSource == full_path
                if is_match:
                    input_polygon_layer = lyr
                    break

            # 5. Add template_layer positioned below input_polygon_layer
            if input_polygon_layer:
                active_map.insertLayer(input_polygon_layer, template_layer, "AFTER")
                arcpy.AddMessage(
                    f"Successfully added '{out_dataset_name}' below '{input_polygon_layer.name}' with symbology pre-applied.")
            else:
                active_map.addLayer(template_layer)
                arcpy.AddMessage(
                    f"Successfully added '{out_dataset_name}' with symbology pre-applied (input polygon layer not found in map).")

        else:
            arcpy.AddWarning(f"Symbology file not found at: {symbology_file}. Adding raw data instead.")
            active_map.addDataFromPath(epidiko_tmima)
    else:
        arcpy.AddWarning("No active map found. Layer created but not added to map.")

except Exception as e:
    arcpy.AddWarning(f"An error occurred while adding to map: {str(e)}")

arcpy.AddMessage("Clipping Forest Cover to Cadastral Polygons...")


if arcpy.Exists(clipped_forest_cover):
    arcpy.management.Delete(clipped_forest_cover)

arcpy.analysis.Clip(
    in_features=input_forest_features,
    clip_features=input_polygon_features,
    out_feature_class=clipped_forest_cover,
    cluster_tolerance=None,
)
try:
    active_map = aprx.activeMap
    if active_map:
        # Define path to the symbology file
        out_dataset_name = Path(clipped_forest_cover).stem
        if intersection_symbology=='two-color':
            symbology_file = os.path.join(templates_folder, "KATHGORDX_v1.lyrx")
        else:
            symbology_file = os.path.join(templates_folder, "ΑΝΑΜΟΡΦΩΣΗ_ΑΝΑΡΤΗΣΗ_ΔΧ.lyrx")

        if os.path.exists(symbology_file):
            # 1. Load the Layer File (.lyrx) as an object
            lyr_doc = arcpy.mp.LayerFile(symbology_file)
            arcpy.AddMessage("Applying symbology from {}".format(symbology_file))

            # 2. Get the first layer in the .lyrx
            template_layer = lyr_doc.listLayers()[0]

            # 3. Update the Connection Properties to point to the new data
            new_connection_info = {
                'workspace_factory': 'File Geodatabase',
                'connection_info': {'database': output_gdb},
                'dataset': out_dataset_name
            }

            template_layer.updateConnectionProperties(
                current_connection_info=template_layer.connectionProperties,
                new_connection_info=new_connection_info
            )

            # 4. Find the input polygon layer in the map
            input_polygon_layer = None
            input_polygon_name = os.path.basename(input_polygon_features)
            for lyr in active_map.listLayers():
                is_match = lyr.name == input_polygon_name
                if not is_match and lyr.supports("dataSource"):
                    is_match = lyr.dataSource == full_path
                if is_match:
                    input_polygon_layer = lyr
                    break

            # 5. Add template_layer positioned below input_polygon_layer
            if input_polygon_layer:
                active_map.insertLayer(input_polygon_layer, template_layer, "AFTER")
                arcpy.AddMessage(
                    f"Successfully added '{out_dataset_name}' below '{input_polygon_layer.name}' with symbology pre-applied.")
            else:
                active_map.addLayer(template_layer)
                arcpy.AddMessage(
                    f"Successfully added '{out_dataset_name}' with symbology pre-applied (input polygon layer not found in map).")

        else:
            arcpy.AddWarning(f"Symbology file not found at: {symbology_file}. Adding raw data instead.")
            active_map.addDataFromPath(epidiko_tmima)
    else:
        arcpy.AddWarning("No active map found. Layer created but not added to map.")

except Exception as e:
    arcpy.AddWarning(f"An error occurred while adding to map: {str(e)}")

aprx = arcpy.mp.ArcGISProject("CURRENT")
m = aprx.listMaps()[0]
for lyr in m.listLayers():
    if lyr.name == "ΑΝΑΜΟΡΦΩΣΗ ΔΑΣΙΚΟΥ ΧΑΡΤΗ":
        lyr.name = "ΓΕΩΤΕΜΑΧΙΟ_ΜΟΡΦΕΣ_ΔΧ"
        break

aprx.save()

arcpy.AddMessage("Cleaning up intermediate data...")
for field in input_forest_fields.split(";"):
    out_summary_table = os.path.join(output_gdb, f"Polygons_Summarize_{field}_Table")
    arcpy.management.Delete(out_summary_table)
    join_table = os.path.join(output_gdb, f"Polygons_Summarize_{field}_PivotTable")
    arcpy.management.Delete(join_table)

arcpy.AddMessage("Finished.")
