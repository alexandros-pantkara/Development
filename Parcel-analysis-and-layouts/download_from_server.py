import arcpy
import os
import zipfile
from datetime import datetime

# Get parameters from the script tool
input_zip = arcpy.GetParameterAsText(0)      # the .zip on the server
output_folder = arcpy.GetParameterAsText(1)  # local folder to restore into


def top_level_entries(zf):
    """Top level names inside the archive, e.g. {'MyData.gdb'}."""
    tops = set()
    for name in zf.namelist():
        head = name.replace('\\', '/').split('/')[0]
        if head:
            tops.add(head)
    return tops


if not zipfile.is_zipfile(input_zip):
    arcpy.AddError(f'Not a zip archive: {input_zip}')
    raise ValueError('Input is not a zip archive')

# Restore into a folder named after the upload it came from, so it is obvious
# which snapshot this is. Falls back to the current time if that is not usable.
source_stamp = os.path.basename(os.path.dirname(os.path.abspath(input_zip)))
if not source_stamp:
    source_stamp = datetime.now().strftime('%Y_%m_%d_%H_%M_%S')

out_folder = os.path.join(output_folder, source_stamp)

with zipfile.ZipFile(input_zip) as zf:
    gdb_entries = [t for t in top_level_entries(zf) if t.lower().endswith('.gdb')]

    if not gdb_entries:
        arcpy.AddWarning(
            'No .gdb folder found at the top level of the archive - '
            'extracting its contents as they are.'
        )

    # Extracting over an existing geodatabase would mix old and new files
    # together, which can leave it unreadable. Refuse rather than merge.
    for gdb_folder in gdb_entries:
        target = os.path.join(out_folder, gdb_folder)
        if os.path.exists(target):
            arcpy.AddError(
                f'"{target}" already exists. Remove it, or choose a different '
                'output folder, and run the tool again.'
            )
            raise FileExistsError(target)

    os.makedirs(out_folder, exist_ok=True)
    arcpy.AddMessage(f'Extracting {os.path.basename(input_zip)} ...')
    zf.extractall(out_folder)

arcpy.AddMessage(f'Extracted to: {out_folder}')

for gdb_folder in gdb_entries:
    target = os.path.join(out_folder, gdb_folder)
    if arcpy.Exists(target):
        arcpy.AddMessage(f'Geodatabase restored: {target}')
    else:
        arcpy.AddWarning(
            f'Extracted "{target}", but ArcGIS does not recognise it as a geodatabase.'
        )

arcpy.AddMessage('Finished')
