import arcpy
import os
import shutil
import zipfile
from datetime import datetime

# Get parameters from the script tool
input_geodatabase = arcpy.GetParameterAsText(0)
input_server_folder = arcpy.GetParameterAsText(1)


def resolve_geodatabase(path):
    """
    Accepts either the geodatabase itself or a dataset inside it, and returns
    the full path to the .gdb folder.
    """
    desc = arcpy.Describe(path)
    if getattr(desc, 'dataType', '') == 'Workspace':
        return desc.catalogPath
    return getattr(desc, 'path', None) or path


def zip_geodatabase(gdb_path, out_zip_path):
    """
    Zips a file geodatabase. The .gdb folder is kept as the top level entry in
    the archive, so it extracts straight back to a usable geodatabase. Lock
    files left behind by an open ArcGIS session are skipped.
    """
    gdb_path = gdb_path.rstrip('\\/')
    parent = os.path.dirname(gdb_path)

    written = skipped = 0
    with zipfile.ZipFile(out_zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(gdb_path):
            for name in files:
                if name.lower().endswith('.lock'):
                    skipped += 1
                    continue
                full = os.path.join(root, name)
                zf.write(full, os.path.relpath(full, parent))
                written += 1
    return written, skipped


gdb_path = resolve_geodatabase(input_geodatabase)
gdb_folder = os.path.basename(gdb_path.rstrip('\\/'))   # e.g. 'MyData.gdb'
gdb_stem = os.path.splitext(gdb_folder)[0]              # e.g. 'MyData'

timestamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
out_folder = os.path.join(input_server_folder, timestamp)
out_zip = os.path.join(out_folder, f'{gdb_stem}.zip')

os.makedirs(out_folder, exist_ok=True)

arcpy.AddMessage(f'Zipping {gdb_folder} ...')
arcpy.AddMessage('Save any open edits first - this copies the files as they are on disk.')

written, skipped = zip_geodatabase(gdb_path, out_zip)
size_mb = os.path.getsize(out_zip) / (1024 * 1024)
arcpy.AddMessage(
    f'Geodatabase zipped: {out_zip} '
    f'({written} file(s), {size_mb:.1f} MB, {skipped} lock file(s) skipped)'
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
