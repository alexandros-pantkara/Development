import arcpy
import os
from pathlib import Path

# Get parameters from the script tool
input_cad_dataset = arcpy.GetParameterAsText(0)
output_gdb = arcpy.GetParameterAsText(1)
out_feature_dataset = arcpy.GetParameterAsText(2)
out_dataset_name = arcpy.GetParameterAsText(3)
spatial_reference = arcpy.GetParameterAsText(4)
is_parcel = arcpy.GetParameterAsText(5)

if out_feature_dataset:
    if not arcpy.Exists(os.path.join(output_gdb, out_feature_dataset)):
        arcpy.AddMessage("Creating Feature Dataset...")
        arcpy.management.CreateFeatureDataset(output_gdb, out_feature_dataset, spatial_reference)

arcpy.AddMessage(f"Output dataset name determined as: {out_dataset_name}")
# Reference the current ArcGIS Project
aprx = arcpy.mp.ArcGISProject("CURRENT")
project_folder = aprx.homeFolder
templates_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template data")

arcpy.AddMessage("Converting CAD dataset to Geodatabase...")
# --- Process: CAD to Geodatabase ---
# output_gdb_for_convert = output_gdb if output_gdb.endswith(".gdb") else os.path.dirname(output_gdb)

arcpy.conversion.CADToGeodatabase(
    input_cad_datasets=input_cad_dataset,
    out_gdb_path=output_gdb,
    out_dataset_name=out_dataset_name,
    reference_scale=1000,
    spatial_reference=spatial_reference
)
arcpy.AddMessage("CAD to Geodatabase conversion completed.")

polygon_fc_path = os.path.join(output_gdb, out_dataset_name, "Polygon")
polyline_fc_path = os.path.join(output_gdb, out_dataset_name, "Polyline")

# --- Check if Polygon feature class has features ---
polygon_has_features = (
        arcpy.Exists(polygon_fc_path) and
        int(arcpy.management.GetCount(polygon_fc_path)[0]) > 0
)

if not polygon_has_features:
    arcpy.AddWarning(
        "Polygon feature class is empty or missing. "
        "CAD polylines appear to be open — converting Polyline to Polygon..."
    )

    # Build polygon feature class from open/closed polylines using arcpy.da cursors
    # This is Basic-license compatible (no Feature To Polygon tool needed)
    sr = arcpy.Describe(polyline_fc_path).spatialReference

    if not arcpy.Exists(polygon_fc_path):
        arcpy.management.CreateFeatureclass(
            out_path=os.path.join(output_gdb, out_dataset_name),
            out_name="Polygon",
            geometry_type="POLYGON",
            spatial_reference=sr
        )

    converted_count = 0
    skipped_count = 0

    with arcpy.da.SearchCursor(polyline_fc_path, ["SHAPE@"]) as s_cur, \
            arcpy.da.InsertCursor(polygon_fc_path, ["SHAPE@"]) as i_cur:
        for row in s_cur:
            geom = row[0]
            if geom is None:
                skipped_count += 1
                continue
            all_parts = []
            for part in geom:
                pts = [pt for pt in part if pt is not None]
                if len(pts) < 2:
                    skipped_count += 1
                    continue
                # Close the ring if open
                if pts[0].X != pts[-1].X or pts[0].Y != pts[-1].Y:
                    pts.append(pts[0])
                all_parts.append(arcpy.Array(pts))
            if all_parts:
                polygon = arcpy.Polygon(arcpy.Array(all_parts), sr)
                i_cur.insertRow([polygon])
                converted_count += 1

    arcpy.AddMessage(
        f"Polyline to Polygon conversion complete: "
        f"{converted_count} feature(s) converted, {skipped_count} skipped."
    )

# --- Process: Delete Polyline feature class ---
arcpy.AddMessage("Removing Polyline feature class...")
arcpy.management.Delete(
    in_data=polyline_fc_path,
    data_type="FeatureClass"
)

# --- Process: Rename Polygon feature class ---
final_output_path = os.path.join(output_gdb, out_dataset_name, out_dataset_name)

arcpy.AddMessage("Renaming Polygon feature class and applying symbology...")
arcpy.management.Rename(
    in_data=polygon_fc_path,
    out_data=final_output_path,
    data_type="FeatureClass"
)

arcpy.management.DeleteField(
    in_table=final_output_path,
    drop_field="Entity;Handle;Layer;LyrFrzn;LyrLock;LyrOn;LyrVPFrzn;LyrHandle;Color;EntColor;LyrColor;BlkColor;Linetype;EntLinetype;LyrLnType;BlkLinetype;LTScale;Elevation;Thickness;LineWt;EntLineWt;LyrLineWt;BlkLineWt;RefName;ExtX;ExtY;ExtZ;DocName;DocPath;DocType;DocVer;DocUpdate;DocId;GlobalWidth;PtnName;PtnScl;PtnAng",
    method="DELETE_FIELDS"
)
arcpy.management.CalculateField(
    in_table=final_output_path, field="Emvadon", expression="round(!{}!,3)".format("Shape_Area"),
    expression_type="PYTHON3")
if is_parcel == "true":
    arcpy.management.CalculateField(
        in_table=final_output_path, field="parcel", expression="''", expression_type="PYTHON3")

if out_feature_dataset:
    converted_final_output_path = os.path.join(out_feature_dataset, out_dataset_name + "_Γ")
    arcpy.conversion.ExportFeatures(
        in_features=final_output_path,
        out_features=converted_final_output_path,
        where_clause="",
        use_field_alias_as_name="NOT_USE_ALIAS",
        sort_field=None
    )
    final_output_path = converted_final_output_path

try:
    active_map = aprx.activeMap

    if active_map:
        # Add the output FC by its known path
        active_map.addDataFromPath(final_output_path)
        arcpy.AddMessage(f"Added '{out_dataset_name}' to the map.")

        # Re-fetch layer by matching data source path
        added_layer = None
        for lyr in active_map.listLayers():
            try:
                if hasattr(lyr, 'dataSource') and lyr.dataSource == final_output_path:
                    added_layer = lyr
                    break
            except Exception:
                continue

        if added_layer is None:
            added_layer = active_map.listLayers()[0]
            arcpy.AddMessage("Layer matched by index fallback.")
        else:
            arcpy.AddMessage(f"Layer matched by data source: {added_layer.name}")

        # Apply symbology via in-place CIM mutation
        cim_def = added_layer.getDefinition('V3')
        sym = cim_def.renderer.symbol.symbol  # CIMPolygonSymbol

        for sl in sym.symbolLayers:
            t = type(sl).__name__
            if t == 'CIMSolidFill':
                sl.color.values = [0, 0, 0, 0]  # transparent fill
            elif t == 'CIMSolidStroke':
                sl.color.values = [255, 0, 0, 100]  # red, fully opaque
                sl.width = 2

        added_layer.setDefinition(cim_def)
        arcpy.AddMessage("Symbology applied: red outline (2pt), transparent fill.")

    else:
        arcpy.AddWarning("No active map found.")

except Exception as e:
    arcpy.AddWarning(f"Error adding/symbolizing layer: {str(e)}")

arcpy.AddMessage("CAD dataset converted to geodatabase successfully.")
arcpy.AddMessage("Process completed.")
