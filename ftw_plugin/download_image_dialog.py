import os
from qgis.PyQt import uic
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QDate
from qgis.core import QgsProject, QgsMapLayer, QgsRectangle
from qgis.gui import QgsMapCanvas

# This loads your .ui file so that PyQt can populate your plugin with the elements from Qt Designer
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'download_image.ui'))

class DownloadImageDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(DownloadImageDialog, self).__init__(parent)
        # Set up the dialog from the UI
        self.setupUi(self)
        
        # Set default dates to today
        self.sos_date.setDate(QDate.currentDate())
        self.eos_date.setDate(QDate.currentDate())
        
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
        self.download_button.clicked.connect(self.accept)
        self.download_ui_cancel.clicked.connect(self.reject)
        
        # Connect the browse button for output path
        self.download_tif_path.clicked.connect(self.browse_output)
    
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