import arcpy
import os
import shutil
from pathlib import Path
from datetime import datetime

# Get parameters from the script tool
input_geodatabase = arcpy.GetParameterAsText(0)
input_server_folder = arcpy.GetParameterAsText(1)

desc = arcpy.Describe(input_geodatabase)
# If Describe has a .path (feature class/table/etc.), use that as workspace; otherwise use the input itself
workspace_path = getattr(desc, 'path', None) or input_geodatabase
gdb_name = Path(workspace_path).stem

timestamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
out_folder = os.path.join(input_server_folder, timestamp)
out_gdb = os.path.join(out_folder, gdb_name)

# Create the directory and any missing parents. No error if it already exists.
os.makedirs(out_folder, exist_ok=True)

arcpy.management.Copy(
    in_data=input_geodatabase,
    out_data=out_gdb,
    data_type="Workspace",
    associated_data=None
)

# Copy the current ArcGIS Pro project (.aprx) into the same output folder
current_project = arcpy.mp.ArcGISProject("CURRENT")
current_aprx = current_project.filePath

if current_aprx and os.path.exists(current_aprx):
    shutil.copy2(current_aprx, os.path.join(out_folder, os.path.basename(current_aprx)))
    arcpy.AddMessage(f"Copied current project: {os.path.basename(current_aprx)}")
else:
    arcpy.AddWarning("Could not find the current ArcGIS Pro project file.")

arcpy.AddMessage("Finished")