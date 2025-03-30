import os
from qgis.PyQt import uic
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QDate

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
        
        # Connect the property override button
        self.roi_extraction_button.clicked.connect(self.handle_property_override)
        
        # Connect the download and cancel buttons
        self.download_button.clicked.connect(self.accept)
        self.download_ui_cancel.clicked.connect(self.reject)
        
        # Connect the browse button for output path
        self.download_tif_path.clicked.connect(self.browse_output)
    
    def handle_property_override(self):
        """Handle the property override button click."""
        # TODO: Implement property override functionality
        pass
    
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