import arcpy
import os
import json


def create_raster_catalog_arcpy(input_folders, output_geojson):
    """
    Scans folders for rasters using ArcPy to handle ECW/JP2 formats,
    projects bounds to WGS84, and saves as GeoJSON.
    """
    # ArcPy supports ECW, JP2, TIF, SID, etc. natively
    valid_extensions = ('.tif', '.tiff', '.jp2', '.ecw', '.img', '.sid')

    # Define WGS84 Spatial Reference (EPSG:4326) for GeoJSON
    sr_wgs84 = arcpy.SpatialReference(4326)

    geojson_output = {
        "type": "FeatureCollection",
        "features": []
    }

    print(f"Starting scan of {len(input_folders)} folder(s) using ArcPy...")
    count = 0

    for folder in input_folders:
        for root, dirs, files in os.walk(folder):
            for file in files:
                if file.lower().endswith(valid_extensions):
                    file_path = os.path.join(root, file)

                    try:
                        # 1. Check if valid raster and get properties
                        # 'Describe' is fast and works on unopened files
                        try:
                            desc = arcpy.Describe(file_path)
                        except Exception:
                            # If ArcPy can't describe it, it's likely corrupt or xml
                            continue

                        if desc.dataType != 'RasterDataset':
                            continue

                        # 2. Check for Spatial Reference
                        if desc.spatialReference is None or desc.spatialReference.name == "Unknown":
                            print(f"Skipping (No CRS): {file}")
                            continue

                        # 3. Create a Polygon from the raster's extent
                        # We use the extent object to get the corners in native coordinates
                        extent = desc.extent

                        # Create a list of points (Counter-clockwise)
                        pts = [
                            arcpy.Point(extent.XMin, extent.YMin),
                            arcpy.Point(extent.XMax, extent.YMin),
                            arcpy.Point(extent.XMax, extent.YMax),
                            arcpy.Point(extent.XMin, extent.YMax),
                            arcpy.Point(extent.XMin, extent.YMin)
                        ]

                        # Create polygon geometry
                        poly = arcpy.Polygon(arcpy.Array(pts), desc.spatialReference)

                        # 4. Project the polygon to WGS84
                        # This handles the reprojection (e.g. Greek Grid -> Lat/Lon)
                        poly_wgs84 = poly.projectAs(sr_wgs84)

                        # 5. Get the bounding box of the PROJECTED polygon
                        # This ensures the GeoJSON box covers the twisted/rotated image in WGS84
                        wgs_ext = poly_wgs84.extent

                        # Format coordinates for GeoJSON [[ [x,y], [x,y]... ]]
                        # Note: GeoJSON uses specific winding, but simple box is robust
                        coordinates = [[
                            [wgs_ext.XMin, wgs_ext.YMin],
                            [wgs_ext.XMax, wgs_ext.YMin],
                            [wgs_ext.XMax, wgs_ext.YMax],
                            [wgs_ext.XMin, wgs_ext.YMax],
                            [wgs_ext.XMin, wgs_ext.YMin]
                        ]]

                        # 6. Append to Feature Collection
                        feature = {
                            "type": "Feature",
                            "properties": {
                                "filename": file,
                                "filepath": file_path,
                                "crs_source": desc.spatialReference.name
                            },
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": coordinates
                            }
                        }

                        geojson_output["features"].append(feature)
                        count += 1
                        print(f"Processed: {file}")

                    except Exception as e:
                        print(f"Error processing {file}: {str(e)}")

    # Write the final file
    with open(output_geojson, 'w') as f:
        json.dump(geojson_output, f, indent=2)

    print(f"\nSuccess! Processed {count} rasters.")
    print(f"Output saved to: {output_geojson}")


# ==========================================
# INPUT SETTINGS
# ==========================================
if __name__ == "__main__":
    # 1. List of folders to search
    my_folders = [
        r"C:\workspace\Freelance life\Pantelis Karapatsios\ArcPy ortho automation\Data\Structured folders\5ARIA_GEO_CORRECT\ΝΑΞΟΣ",
    ]

    # 2. Output filename
    output_file = r"C:\workspace\Freelance life\Pantelis Karapatsios\ArcPy ortho automation\image_catalog_5aria.geojson"

    create_raster_catalog_arcpy(my_folders, output_file)
