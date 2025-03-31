import os
from qgis.PyQt import uic
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QDate
from qgis.core import QgsProject, QgsMapLayer, QgsRectangle
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
        
        # Set default dates
        self.sos_date.setDate(QDate(2024, 6, 1))  # 01/06/2024
        self.eos_date.setDate(QDate(2024, 11, 30))  # 31/11/2024
        
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
        
        # Initialize conda environment
        self.conda_env = None
        
        # Import download utilities only after UI is set up
        self.setup_download_utils()
    
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
            from .download_utils import parse_coordinates, calculate_window_dates, extract_patch
            self.parse_coordinates = parse_coordinates
            self.calculate_window_dates = calculate_window_dates
            self.extract_patch = extract_patch
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Failed to set up download utilities: {str(e)}"
            )
            self.reject()
    
    def handle_download(self):
        """Handle download button click."""
        try:
            # Validate coordinates
            if not self.roi_bbox.text():
                QtWidgets.QMessageBox.warning(self, "Error", "Please set the area of interest coordinates.")
                return
            
            # Parse coordinates and get center point
            center_lon, center_lat = self.parse_coordinates(self.roi_bbox.text())
            
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
                lon=center_lon,
                lat=center_lat,
                win_a_start=win_a_start,
                win_a_end=win_a_end,
                win_b_start=win_b_start,
                win_b_end=win_b_end,
                output_dir=output_dir,
                output_filename=output_filename,
                max_cloud_cover=70,
                patch_size=1024,
                conda_env=self.conda_env
            )
            
            # Update progress
            self.progressBar.setValue(100)
            self.progressBar.setFormat("Download complete!")
            
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