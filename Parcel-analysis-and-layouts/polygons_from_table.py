# -*- coding: utf-8 -*-
import os
import re

import arcpy
import pandas as pd


def parse_coordinates(coord_text):
    """
    Returns: list_of_parts
      where each part is a list of (x, y) tuples.
    Handles multipart polygons separated by 'ΤΜΗΜΑ1', 'ΤΜΗΜΑ2', ...
    """
    if coord_text is None:
        return []

    txt = str(coord_text)

    # Split by part markers like ΤΜΗΜΑ1, ΤΜΗΜΑ2 ...
    sections = re.split(r"ΤΜΗΜΑ\d+", txt)
    parts = []

    for section in sections:
        section = section.strip()
        if not section:
            continue

        coords = []
        for line in section.splitlines():
            line = line.strip()
            if not line:
                continue

            # X1=631342,970Y1=4106531,850 (allow spaces; comma/period decimals)
            xm = re.search(r"X\d+\s*=\s*([0-9]+(?:[.,][0-9]+)?)", line)
            ym = re.search(r"Y\d+\s*=\s*([0-9]+(?:[.,][0-9]+)?)", line)
            if not (xm and ym):
                continue

            x = float(xm.group(1).replace(",", "."))
            y = float(ym.group(1).replace(",", "."))
            coords.append((x, y))

        if coords:
            parts.append(coords)

    return parts


def make_output_fc(output_workspace, input_excel):
    """
    Creates a valid output dataset name in the chosen workspace.
    If workspace is a folder, creates a .shp; if a geodatabase/feature dataset, creates a feature class.
    """
    desc = arcpy.Describe(output_workspace)
    ws_type = getattr(desc, "workspaceType", None)

    base = os.path.splitext(os.path.basename(input_excel))[0]
    raw_name = f"{base}_ΓΕΩΤΕΜΑΧΙΟ"

    valid_name = arcpy.ValidateTableName(raw_name, output_workspace)

    if ws_type == "FileSystem":
        if not valid_name.lower().endswith(".shp"):
            valid_name = valid_name + ".shp"

    return os.path.join(output_workspace, valid_name)


def create_polygon_features(input_excel, output_workspace):
    df = pd.read_excel(input_excel)

    sr = arcpy.SpatialReference(2100)  # EPSG:2100

    out_fc = make_output_fc(output_workspace, input_excel)

    out_path = output_workspace
    out_name = os.path.basename(out_fc)

    if arcpy.Exists(out_fc):
        arcpy.management.Delete(out_fc)

    arcpy.management.CreateFeatureclass(out_path, out_name, "POLYGON", spatial_reference=sr)

    # Add fields
    arcpy.management.AddField(out_fc, "a_a_old", "LONG")
    arcpy.management.AddField(out_fc, "a_a_new", "LONG")
    arcpy.management.AddField(out_fc, "emvadon", "DOUBLE")
    arcpy.management.AddField(out_fc, "new_prwteuon", "TEXT", field_length=50)
    arcpy.management.AddField(out_fc, "new_deutereon", "TEXT", field_length=50)
    arcpy.management.AddField(out_fc, "new_triteuon", "TEXT", field_length=50)
    arcpy.management.AddField(out_fc, "new_landtype", "LONG")

    fields = [
        "SHAPE@",
        "a_a_old", "a_a_new", "emvadon",
        "new_prwteuon", "new_deutereon", "new_triteuon",
        "new_landtype"
    ]

    with arcpy.da.InsertCursor(out_fc, fields) as cur:
        for i, r in df.iterrows():
            parts = parse_coordinates(r.get("syntetagmenes_koryfwn"))
            if not parts:
                arcpy.AddWarning(f"Row {i + 2}: No valid coordinates found.")
                continue

            # Create multipart polygon with proper separators
            geom_array = arcpy.Array()

            for part_idx, part in enumerate(parts):
                part_arr = arcpy.Array()
                for x, y in part:
                    part_arr.add(arcpy.Point(x, y))

                # Close ring if needed
                if part[0] != part[-1]:
                    part_arr.add(arcpy.Point(part[0][0], part[0][1]))

                geom_array.add(part_arr)

                # Add None separator between parts (not after the last part)
                if part_idx < len(parts) - 1:
                    geom_array.add(None)

            poly = arcpy.Polygon(geom_array, sr)

            def to_int(v):
                return int(v) if pd.notna(v) else None

            def to_float(v):
                return float(v) if pd.notna(v) else None

            def to_text(v):
                return str(v) if pd.notna(v) else None

            cur.insertRow([
                poly,
                to_int(r.get("a_a_old")),
                to_int(r.get("a_a_new")),
                to_float(r.get("emvadon")),
                to_text(r.get("new_prwteuon")),
                to_text(r.get("new_deutereon")),
                to_text(r.get("new_triteuon")),
                to_int(r.get("new_landtype")),
            ])

    return out_fc


# Script tool entry point
input_excel = arcpy.GetParameterAsText(0)
output_workspace = arcpy.GetParameterAsText(1)

out_fc = create_polygon_features(input_excel, output_workspace)