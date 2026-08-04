"""Identify Rasters - QGIS Processing script.

QGIS equivalent of Parcel-analysis-and-layouts/identify_layers.py (ArcGIS).
Buffers the area of interest, finds the raster catalog records that intersect
the buffer, and loads the referenced rasters into a layer tree group, grouped
by the date folder of each raster path.

Add it to QGIS with: Processing Toolbox -> Scripts -> Add Script to Toolbox.
"""

import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsGeometry,
    QgsLayerTreeGroup,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingParameterDistance,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterString,
    QgsProject,
    QgsRasterLayer,
)


def algorithm_flag(name):
    """Return an algorithm flag, tolerating the QGIS 3.36 enum rename."""
    flag = getattr(QgsProcessingAlgorithm, "Flag" + name, None)
    if flag is None:
        flag = getattr(Qgis.ProcessingAlgorithmFlag, name)
    return flag


class IdentifyRasters(QgsProcessingAlgorithm):
    """Load the ProstasiaData rasters that cover the area of interest."""

    INPUT = "INPUT"
    CATALOG = "CATALOG"
    FILEPATH_FIELD = "FILEPATH_FIELD"
    BUFFER_DISTANCE = "BUFFER_DISTANCE"
    GROUP_NAME = "GROUP_NAME"
    RECORDS_MATCHED = "RECORDS_MATCHED"
    RASTERS_ADDED = "RASTERS_ADDED"

    def tr(self, string):
        return QCoreApplication.translate("IdentifyRasters", string)

    def createInstance(self):
        return IdentifyRasters()

    def name(self):
        return "identifyrasters"

    def displayName(self):
        return self.tr("Identify Rasters")

    def group(self):
        return self.tr("Other")

    def groupId(self):
        return "other"

    def flags(self):
        # The algorithm touches the project layer tree, so it must stay on the
        # main thread, and it needs a project to add the layers to.
        return (
            super().flags()
            | algorithm_flag("NoThreading")
            | algorithm_flag("RequiresProject")
        )

    def shortHelpString(self):
        return self.tr(
            "Intersects the main layer (e.g. ΓΕΩΤΕΜΑΧΙΟ) with the Image Catalog "
            "layer to find which rasters from ProstasiaData are useful.\n\n"
            "The area of interest is buffered (300 m by default), every catalog "
            "record intersecting that buffer is selected, and the raster each "
            "record points to is loaded into a layer tree group. Inside that "
            "group, rasters are placed in subgroups named after the date folder "
            "of their path (…/<date>/<subfolder>/<raster>).\n\n"
            "The buffer distance is expressed in the units of the area of "
            "interest layer; the units drop-down converts from metres for you.\n\n"
            "An existing group with the same name is reused instead of being "
            "duplicated."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                self.tr("Area of interest (e.g. ΓΕΩΤΕΜΑΧΙΟ)"),
                [QgsProcessing.TypeVectorPolygon],
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.CATALOG,
                self.tr("Raster catalog"),
                [QgsProcessing.TypeVectorPolygon],
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.FILEPATH_FIELD,
                self.tr("Field holding the raster file path"),
                defaultValue="filepath",
                parentLayerParameterName=self.CATALOG,
                type=QgsProcessingParameterField.String,
            )
        )
        self.addParameter(
            QgsProcessingParameterDistance(
                self.BUFFER_DISTANCE,
                self.tr("Buffer distance"),
                defaultValue=300.0,
                parentParameterName=self.INPUT,
                minValue=0.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.GROUP_NAME,
                self.tr("Layer tree group"),
                defaultValue="Visible Layers",
            )
        )

        self.addOutput(
            QgsProcessingOutputNumber(
                self.RECORDS_MATCHED, self.tr("Intersecting catalog records")
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(self.RASTERS_ADDED, self.tr("Rasters added"))
        )

    @staticmethod
    def get_or_create_group(parent, group_name):
        """Return the direct child group named group_name; create it if missing."""
        for child in parent.children():
            if isinstance(child, QgsLayerTreeGroup) and child.name() == group_name:
                return child
        return parent.addGroup(group_name)

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(
                self.invalidSourceError(parameters, self.INPUT)
            )

        catalog = self.parameterAsSource(parameters, self.CATALOG, context)
        if catalog is None:
            raise QgsProcessingException(
                self.invalidSourceError(parameters, self.CATALOG)
            )

        filepath_field = self.parameterAsString(
            parameters, self.FILEPATH_FIELD, context
        )
        distance = self.parameterAsDouble(parameters, self.BUFFER_DISTANCE, context)
        group_name = (
            self.parameterAsString(parameters, self.GROUP_NAME, context).strip()
            or "Visible Layers"
        )

        project = context.project() or QgsProject.instance()
        if project is None:
            raise QgsProcessingException(
                self.tr("This tool must be run from an open QGIS project.")
            )

        # 1. Buffer the area of interest
        buffers = []
        for feature in source.getFeatures():
            if feedback.isCanceled():
                return {}
            geom = feature.geometry()
            if geom.isNull() or geom.isEmpty():
                continue
            buffers.append(geom.buffer(distance, 8))

        if not buffers:
            raise QgsProcessingException(
                self.tr("The area of interest has no usable geometries.")
            )

        search_geom = QgsGeometry.unaryUnion(buffers)
        if search_geom.isNull() or search_geom.isEmpty():
            raise QgsProcessingException(self.tr("Could not build the buffer geometry."))

        feedback.pushInfo(
            "Buffer created: {} around {} input geometr{}".format(
                distance, len(buffers), "y" if len(buffers) == 1 else "ies"
            )
        )

        # The catalog may live in another CRS than the area of interest
        if source.sourceCrs() != catalog.sourceCrs():
            transform = QgsCoordinateTransform(
                source.sourceCrs(), catalog.sourceCrs(), context.transformContext()
            )
            if search_geom.transform(transform) != 0:
                raise QgsProcessingException(
                    self.tr("Could not reproject the buffer to the catalog CRS.")
                )

        # 2. Set up the layer tree group
        root = project.layerTreeRoot()
        target_group = self.get_or_create_group(root, group_name)
        feedback.pushInfo("Using group layer: '{}'".format(group_name))

        # 3. Find the intersecting catalog records
        feedback.pushInfo("Selecting intersecting raster records...")
        engine = QgsGeometry.createGeometryEngine(search_geom.constGet())
        engine.prepareGeometry()

        request = QgsFeatureRequest().setFilterRect(search_geom.boundingBox())
        request.setSubsetOfAttributes([filepath_field], catalog.fields())

        matches = []
        for feature in catalog.getFeatures(request):
            if feedback.isCanceled():
                return {}
            geom = feature.geometry()
            if geom.isNull() or geom.isEmpty():
                continue
            if engine.intersects(geom.constGet()):
                matches.append(feature[filepath_field])

        selected_count = len(matches)
        feedback.pushInfo(
            "Found {} intersecting raster records".format(selected_count)
        )

        # 4. Add a raster per selected record, in a subgroup named after its date
        step = 100.0 / selected_count if selected_count else 0
        added = 0
        seen = set()

        for index, raster_path in enumerate(matches):
            if feedback.isCanceled():
                break
            feedback.setProgress(int(index * step))

            raster_path = str(raster_path) if raster_path else ""
            folder_path = os.path.dirname(raster_path) if raster_path else ""
            raster_date = (
                os.path.basename(os.path.dirname(folder_path))
                if folder_path
                else "Unknown_Date"
            )

            if not raster_path or not os.path.exists(raster_path):
                feedback.pushWarning(
                    "✗ Invalid/missing path: {}".format(raster_path or "<empty>")
                )
                continue

            key = os.path.normcase(os.path.normpath(raster_path))
            if key in seen:
                feedback.pushInfo(
                    "• Already added, skipping duplicate record: {}".format(
                        os.path.basename(raster_path)
                    )
                )
                continue
            seen.add(key)

            try:
                date_group = self.get_or_create_group(target_group, raster_date)
                layer_name = os.path.splitext(os.path.basename(raster_path))[0]
                layer = QgsRasterLayer(raster_path, layer_name)

                if not layer.isValid():
                    feedback.pushWarning("✗ Failed to load: {}".format(raster_path))
                    continue

                project.addMapLayer(layer, False)
                date_group.addLayer(layer)
                added += 1
                feedback.pushInfo(
                    "✓ Added: {} -> '{}' group".format(
                        os.path.basename(raster_path), raster_date
                    )
                )
            except Exception as exc:  # noqa: BLE001 - report and carry on
                feedback.pushWarning(
                    "✗ Error adding {}: {}".format(raster_path, exc)
                )

        feedback.setProgress(100)
        feedback.pushInfo(
            "Completed. Processed {} records, added {} rasters to '{}'.".format(
                selected_count, added, group_name
            )
        )

        return {
            self.RECORDS_MATCHED: selected_count,
            self.RASTERS_ADDED: added,
        }
