## Basic Info for working on QGIS project
Use template project from:  <br>

To install the plugin: Plugins -> Manage and Install Plugins -> Install from ZIP -> Locate it from cloned Development folder.
<img width="889" height="773" alt="image" src="https://github.com/user-attachments/assets/87521440-d376-45fc-b5c1-4c5ee1233263" />
<br>
After installation, it will appear in the Processing Toolbox:

<img width="271" height="235" alt="image" src="https://github.com/user-attachments/assets/3eeaef8f-2a88-486a-9061-c85c7e2c12dd" />

Other useful plugins to install: Theme Manager and/or ThemeSelector. They will be used later to manage themes. <br>

Project setup and initially contained layers:  <br>

<img width="299" height="285" alt="image" src="https://github.com/user-attachments/assets/978a29a7-f015-46be-acea-e55dedaa2ff9" />  <img width="299" height="362" alt="image" src="https://github.com/user-attachments/assets/ec708224-5d59-45e7-8d96-2e38d2a6df06" />

## Overview of Tools
* Convert from CAD: Use DXF as input and save to Data>parcels.gpkg  <br>
* Summarize Polygons (Intersect): Use the parcel and forest map, and save outputs to Analysis>analysis.gpkg  <br>
* Identify Rasters: Use the parcel layer and Prostasia Data Footprints (make sure filepath attribut is correct)
* To create layouts:
  1. Use Save Layout View to save as many themes and spatial bookmarks as you want. Name them as you want them to be named for printing (this name will go to the corresponding layout's text label)
  2. Use Create Layouts DA or PROD to select the themes you created and export the layouts (they will be exported in the Layouts folder of the project)
  3. To easily manage Themes (add/remove/rearrange) use Theme Manager plugin or ThemeSelector plugin
* To create Antirrisi polygons: First use the Create Antirrisi Layer tool to just create the layer in analysis>analysis.gpkg. Then use Insert Antirrisi polygon by copying-pasting the coordinates and information from the .pdf.
