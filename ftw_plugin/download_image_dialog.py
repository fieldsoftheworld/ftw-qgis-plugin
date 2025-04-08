import os
from qgis.PyQt import uic
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QDate
from qgis.core import QgsProject, QgsMapLayer, QgsRectangle, QgsCoordinateTransform
from qgis.gui import QgsMapCanvas
import tempfile
import sys
import subprocess
import json
from qgis.core import QgsApplication
from .ftw_plugin_dialog import setup_ftw_env

# This loads your .ui file so that PyQt can populate your plugin with the elements from Qt Designer
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'download_image.ui'))

class DownloadImageDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(DownloadImageDialog, self).__init__(parent)
        # Set up the dialog from the UI
        self.setupUi(self)
        
        # Define season TIF paths
        self.seasons = {
            "summer": {
                "start": "/Users/gmuhawen/Gedeon/RESEARCH/FTW/ftw_data_download/data/sc_sos_3x3_v2.tiff",
                "end": "/Users/gmuhawen/Gedeon/RESEARCH/FTW/ftw_data_download/data/sc_eos_3x3_v2.tiff"
            },
            "winter": {
                "start": "/Users/gmuhawen/Gedeon/RESEARCH/FTW/ftw_data_download/data/wc_eos_3x3_v2.tiff",
                "end": "/Users/gmuhawen/Gedeon/RESEARCH/FTW/ftw_data_download/data/wc_sos_3x3_v2.tiff"
            }
        }
        
        # Set default dates
        self.sos_date.setDate(QDate(2024, 6, 1))  # 01/06/2024
        self.eos_date.setDate(QDate(2024, 11, 30))  # 31/11/2024
        
        # Create a button group for crop type radio buttons
        self.crop_type_group = QtWidgets.QButtonGroup(self)
        self.crop_type_group.addButton(self.winter_crops)
        self.crop_type_group.addButton(self.summer_crops)
        self.crop_type_group.setExclusive(True)  # Ensure only one can be selected at a time
        
        # Set winter crops as default
        self.winter_crops.setChecked(True)
        
        # Create menu for ROI extraction button
        self.roi_menu = QtWidgets.QMenu(self)
        self.set_canvas_extent_action = self.roi_menu.addAction("Set to current map canvas extent")
        
        # Create submenu for layer selection
        self.layer_menu = QtWidgets.QMenu("Calculate from layer", self)
        self.roi_menu.addMenu(self.layer_menu)
        
        # Connect the property override button
        self.roi_extraction_button.clicked.connect(self.show_roi_menu)
        
        # Connect the menu actions
        self.set_canvas_extent_action.triggered.connect(self.set_canvas_extent)
        
        # Connect the download and cancel buttons
        self.download_button.clicked.connect(self.handle_download)
        self.download_ui_cancel.clicked.connect(self.reject)
        
        # Connect the browse button for output path
        self.download_tif_path.clicked.connect(self.browse_output)
        
        # Connect crop type radio buttons
        self.winter_crops.toggled.connect(self.on_crop_type_changed)
        self.summer_crops.toggled.connect(self.on_crop_type_changed)
        
        # Connect ROI text change
        self.roi_bbox.textChanged.connect(self.on_roi_changed)
        
        # Initialize conda environment
        self.conda_env = None
        
        # Import download utilities only after UI is set up
        self.setup_download_utils()
        
        # Connect to QGIS layer change signals
        QgsProject.instance().layersAdded.connect(self.refresh_raster_list)
        QgsProject.instance().layersRemoved.connect(self.refresh_raster_list)
        
        # Initial population of raster list
        self.refresh_raster_list()
    
    def setup_download_utils(self):
        """Set up the download utilities after ensuring conda environment is activated."""
        try:
            # Get settings file path
            settings_path = os.path.join(
                QgsApplication.qgisSettingsDirPath(),
                "ftw_plugin_settings.json"
            )
            
            # Read environment name from settings
            if not os.path.exists(settings_path):
                raise RuntimeError("Settings file not found. Please configure the plugin first.")
            
            with open(settings_path, 'r') as f:
                settings = json.load(f)
                env_name = settings.get('env_name')
                if not env_name:
                    raise RuntimeError("Environment name not found in settings. Please configure the plugin first.")
            
            # Get conda path from settings
            conda_path = settings.get('conda_path')
            if not conda_path:
                raise RuntimeError("Conda path not found in settings. Please configure the plugin first.")
            
            # Extract the base conda path from conda.sh path
            if conda_path.endswith('conda.sh'):
                conda_base = os.path.dirname(os.path.dirname(os.path.dirname(conda_path)))
            else:
                conda_base = conda_path
            
            # Set up environment
            if not setup_ftw_env(self, env_name):
                raise RuntimeError("Failed to set up conda environment")
            
            # Construct the full path to the conda environment
            if os.name == 'nt':  # Windows
                self.conda_env = os.path.join(conda_base, 'envs', env_name)
            else:  # Unix-like
                self.conda_env = os.path.join(conda_base, 'envs', env_name)
            
            # Now import the download utilities
            from .download_utils import parse_coordinates, calculate_window_dates, extract_patch, get_dates_from_tifs
            self.parse_coordinates = parse_coordinates
            self.calculate_window_dates = calculate_window_dates
            self.extract_patch = extract_patch
            self.get_dates_from_tifs = get_dates_from_tifs
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Failed to set up download utilities: {str(e)}"
            )
            self.reject()
    
    def center_map_on_layer(self, layer):
        """Center the map canvas on a layer, handling CRS transformations."""
        if not layer or not layer.isValid():
            return
            
        # Get the project's CRS
        project_crs = self.parent().iface.mapCanvas().mapSettings().destinationCrs()
        
        # Get the layer's CRS
        layer_crs = layer.crs()
        
        # If CRSs are different, transform the extent
        if project_crs != layer_crs:
            transform = QgsCoordinateTransform(layer_crs, project_crs, QgsProject.instance())
            extent = transform.transformBoundingBox(layer.extent())
        else:
            extent = layer.extent()
            
        # Set the extent with a small buffer for better visualization
        canvas = self.parent().iface.mapCanvas()
        canvas.setExtent(extent)
        
        # Add a small buffer to the extent (5% of the width and height)
        width = extent.width()
        height = extent.height()
        buffer_width = width * 0.05
        buffer_height = height * 0.05
        
        buffered_extent = QgsRectangle(
            extent.xMinimum() - buffer_width,
            extent.yMinimum() - buffer_height,
            extent.xMaximum() + buffer_width,
            extent.yMaximum() + buffer_height
        )
        
        # Set the buffered extent
        canvas.setExtent(buffered_extent)
        canvas.refresh()

    def handle_download(self):
        """Handle download button click."""
        try:
            # Validate coordinates
            if not self.roi_bbox.text():
                QtWidgets.QMessageBox.warning(self, "Error", "Please set the area of interest coordinates.")
                return
            
            # Parse coordinates and get all points
            (center_lon, center_lat), (tl_lon, tl_lat), (br_lon, br_lat) = self.parse_coordinates(self.roi_bbox.text())
            
            # Get dates
            sos_date = self.sos_date.date().toString('yyyy-MM-dd')
            eos_date = self.eos_date.date().toString('yyyy-MM-dd')
            
            # Calculate window dates
            win_a_start, win_a_end, win_b_start, win_b_end = self.calculate_window_dates(sos_date, eos_date)
            
            # Get output path
            output_path = self.download_tif_name.text()
            if not output_path:
                temp_dir = tempfile.gettempdir()
                output_path = os.path.join(temp_dir, "ftw_download_output.tif")
                self.download_tif_name.setText(output_path)
            
            # Create output directory if it doesn't exist
            output_dir = os.path.dirname(output_path)
            if not output_dir:
                output_dir = os.getcwd()
            
            # Get the output filename
            output_filename = os.path.basename(output_path)
            
            # Update progress
            self.progressBar.setValue(20)
            self.progressBar.setFormat("Downloading images...")
            QtWidgets.QApplication.processEvents()
            
            # Extract patch using conda environment
            output_file = self.extract_patch(
                top_left=(tl_lon, tl_lat),
                bottom_right=(br_lon, br_lat),
                win_a_start=win_a_start,
                win_a_end=win_a_end,
                win_b_start=win_b_start,
                win_b_end=win_b_end,
                output_dir=output_dir,
                output_filename=output_filename,
                max_cloud_cover=40,
                conda_env=self.conda_env
            )
            
            # Update progress
            self.progressBar.setValue(100)
            self.progressBar.setFormat("Download complete!")
            
            # Add the layer to the map
            from qgis.core import QgsRasterLayer
            layer = QgsRasterLayer(output_file, output_filename)
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                # Center and zoom to the layer extent with proper CRS handling
                self.center_map_on_layer(layer)
            else:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Warning",
                    "Image downloaded but could not be added to the map."
                )
            
            # Show success message
            QtWidgets.QMessageBox.information(
                self,
                "Success",
                f"Image downloaded successfully to:\n{output_file}"
            )
            
            # Accept the dialog
            self.accept()
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Failed to download image: {str(e)}"
            )
            self.progressBar.setValue(0)
            self.progressBar.setFormat("Download failed")
    
    def show_roi_menu(self):
        """Show the ROI extraction menu."""
        # Clear previous layer menu items
        self.layer_menu.clear()
        
        # Get all layers from the project
        layers = QgsProject.instance().mapLayers()
        
        # Add layers to the submenu
        for layer_id, layer in layers.items():
            if layer.type() == QgsMapLayer.VectorLayer or layer.type() == QgsMapLayer.RasterLayer:
                action = self.layer_menu.addAction(layer.name())
                action.setData(layer_id)
                action.triggered.connect(lambda checked, lid=layer_id: self.calculate_from_layer(lid))
        
        # Show the menu
        self.roi_menu.exec_(self.roi_extraction_button.mapToGlobal(
            self.roi_extraction_button.rect().bottomLeft()))
    
    def set_canvas_extent(self):
        """Set ROI to current map canvas extent."""
        canvas = self.parent().iface.mapCanvas()
        extent = canvas.extent()
        crs = canvas.mapSettings().destinationCrs()
        
        # Format the coordinates
        coords = f"{extent.xMinimum():.2f}, {extent.yMaximum():.2f}; {extent.xMaximum():.2f}, {extent.yMinimum():.2f} [{crs.authid()}]"
        self.roi_bbox.setText(coords)
    
    def calculate_from_layer(self, layer_id):
        """Calculate ROI from selected layer."""
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer:
            extent = layer.extent()
            crs = layer.crs()
            
            # Format the coordinates
            coords = f"{extent.xMinimum():.2f}, {extent.yMaximum():.2f}; {extent.xMaximum():.2f}, {extent.yMinimum():.2f} [{crs.authid()}]"
            self.roi_bbox.setText(coords)
    
    def browse_output(self):
        """Open file dialog to select output location."""
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Select Output Location",
            "",
            "GeoTIFF (*.tif);;All Files (*.*)"
        )
        if file_path:
            self.download_tif_name.setText(file_path)
    
    def get_values(self):
        """Return the values entered by the user."""
        # Get the selected crop type
        crop_type = "winter" if self.winter_crops.isChecked() else \
                   "summer" if self.summer_crops.isChecked() else "other"
        
        return {
            'coordinates': self.roi_bbox.text(),
            'crop_type': crop_type,
            'sos_date': self.sos_date.date().toString('yyyy-MM-dd'),
            'eos_date': self.eos_date.date().toString('yyyy-MM-dd'),
            'output_path': self.download_tif_name.text()
        }
    
    def refresh_raster_list(self):
        """Refresh the list of available raster layers in the UI."""
        # Get all layers from the project
        layers = QgsProject.instance().mapLayers()
        
        # Clear previous layer menu items
        self.layer_menu.clear()
        
        # Add layers to the submenu
        for layer_id, layer in layers.items():
            if layer.type() == QgsMapLayer.VectorLayer or layer.type() == QgsMapLayer.RasterLayer:
                action = self.layer_menu.addAction(layer.name())
                action.setData(layer_id)
                action.triggered.connect(lambda checked, lid=layer_id: self.calculate_from_layer(lid))
    
    def on_crop_type_changed(self, checked):
        """Handle crop type radio button changes."""
        if not checked:
            return
            
        # Only update dates if winter or summer is selected
        if self.winter_crops.isChecked() or self.summer_crops.isChecked():
            self.update_dates_from_season()

    def on_roi_changed(self):
        """Handle ROI text changes."""
        # Only update dates if winter or summer is selected
        if self.winter_crops.isChecked() or self.summer_crops.isChecked():
            self.update_dates_from_season()

    def update_dates_from_season(self):
        """Update dates based on selected season and coordinates."""
        try:
            # Check if we have coordinates
            if not self.roi_bbox.text():
                return
            
            # Get the selected season
            season = "winter" if self.winter_crops.isChecked() else "summer"
            
            # Get the center point from coordinates
            (center_lon, center_lat), _, _ = self.parse_coordinates(self.roi_bbox.text())
            
            # Create a point geometry
            from shapely.geometry import Point
            point = Point(center_lon, center_lat)
            
            # Get the TIF paths for the selected season
            start_tif = self.seasons[season]["start"]
            end_tif = self.seasons[season]["end"]
            
            # Get the year from the spinbox
            year = self.crop_year.value()
            
            # Get dates from TIFs
            start_date, end_date = self.get_dates_from_tifs(
                point=point,
                start_season_tif_path=start_tif,
                end_season_tif_path=end_tif,
                year=year,
                season_type=season
            )
            
            # Update the date widgets
            start_qdate = QDate.fromString(start_date, "yyyy-MM-dd")
            end_qdate = QDate.fromString(end_date, "yyyy-MM-dd")
            
            self.sos_date.setDate(start_qdate)
            self.eos_date.setDate(end_qdate)
            
            # Print selected parameters for inspection
            print("\nSelected Parameters:")
            print(f"Season: {season}")
            print(f"Year: {year}")
            print(f"Center Coordinates: ({center_lon}, {center_lat})")
            print(f"Start of Season: {start_date}")
            print(f"End of Season: {end_date}")
            print(f"Start TIF: {start_tif}")
            print(f"End TIF: {end_tif}")
            
        except Exception as e:
            # Don't show error message here to avoid spamming the user
            # The error will be caught during the actual download
            print(f"Error updating dates: {str(e)}") 