import arcpy
import os
from pathlib import Path

# Get parameters from the script tool
input_polygon = arcpy.GetParameterAsText(0)
excel_info_file = arcpy.GetParameterAsText(1)
excel_info_value = arcpy.GetParameterAsText(2)
output_gdb = arcpy.GetParameterAsText(3)

arcpy.AddMessage("Importing Excel data...")
out_dataset_name_for_join = Path(input_polygon).stem
excel_table = os.path.join(output_gdb, f"{out_dataset_name_for_join}_Excel_Table")
# --- Process: Import Excel metadata ---
arcpy.conversion.ExcelToTable(
    Input_Excel_File=excel_info_file,
    Output_Table=excel_table,
    Sheet="",
    field_names_row=1,
    cell_range=""
)
excel_table_selection = os.path.join(output_gdb, f"{out_dataset_name_for_join}_Excel_Table_Selection")
if not excel_info_value:
    arcpy.analysis.TableSelect(
        in_table=excel_table,
        out_table=excel_table_selection,
        where_clause=f"DXF = '{out_dataset_name_for_join}'"
    )
else:
    arcpy.analysis.TableSelect(
        in_table=excel_table,
        out_table=excel_table_selection,
        where_clause=f"DXF = '{excel_info_value}'"
    )
# Validate exactly one row
row_count = int(arcpy.GetCount_management(excel_table_selection)[0])
if row_count != 1:
    arcpy.AddError(f"Expected exactly 1 Excel row for DXF='{out_dataset_name_for_join}', found {row_count}")
    raise ValueError("Excel validation failed - incorrect number of matching rows")

arcpy.management.JoinField(
    in_data=input_polygon,
    in_field="OBJECTID",
    join_table=excel_table_selection,
    join_field="OBJECTID",
    fields=None,
    fm_option="NOT_USE_FM",
    field_mapping=None,
    index_join_fields="NO_INDEXES"
)

arcpy.AddMessage("Excel data validated and imported successfully.")
