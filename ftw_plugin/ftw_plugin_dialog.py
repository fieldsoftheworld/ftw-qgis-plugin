# -*- coding: utf-8 -*-
"""
/***************************************************************************
 FTWDialog
                                 A QGIS plugin
 A plugin to use FTW models to generate field boundaries
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                             -------------------
        begin                : 2025-03-20
        git sha              : $Format:%H$
        copyright            : (C) 2025 by Fields of The World Team
        email                : gedeonmuhawenayo@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os
import uuid
import urllib.request
from pathlib import Path
import sys
import json

from qgis.PyQt import uic
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsRasterLayer, QgsApplication
from qgis.utils import iface

import subprocess



# This loads your .ui file so that PyQt can populate your plugin with the elements from Qt Designer
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'ftw_plugin_dialog_base.ui'))

# Model configurations
MODEL_CONFIGS = {
    "FTW 3 Classes": {
        "url": "https://github.com/fieldsoftheworld/ftw-baselines/releases/download/v1/3_Class_FULL_FTW_Pretrained.ckpt",
        "filename": "3_Class_FULL_FTW_Pretrained.ckpt"
    },
    "FTW 2 Classes": {
        "url": "https://github.com/fieldsoftheworld/ftw-baselines/releases/download/v1/2_Class_FULL_FTW_Pretrained.ckpt",
        "filename": "2_Class_FULL_FTW_Pretrained.ckpt"
    }
}

valid_filenames = ", ".join(config["filename"] for config in MODEL_CONFIGS.values())


class FTWDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, iface, parent=None):
        """Constructor."""
        super(FTWDialog, self).__init__(parent)
        self.iface = iface

        # Set up the dialog from the UI
        self.setupUi(self)
        
        # Initialize settings
        self.settings_file = os.path.join(
            QgsApplication.qgisSettingsDirPath(),
            "ftw_plugin_settings.json"
        )
        
        # Set up the user interface from Designer through FORM_CLASS.
        # After self.setupUi() you can access any designer object by doing
        # self.<objectName>, and you can use autoconnect slots - see
        # http://doc.qt.io/qt-5/designer-using-a-ui-file.html
        # #widgets-and-dialogs-with-auto-connect
        self.setupConnections()
        
        # Populate the raster combo box
        self.populate_raster_combo()
        
        # Load saved settings
        self.load_settings()
        
        # Setup model combo box
        self.setup_model_combo()

    def setupConnections(self):
        """Set up all signal connections for the dialog."""
        # Connect the quit button to close the dialog
        self.quit_button.clicked.connect(self.close)
        
        # Connect the raster path button to file dialog
        self.raster_path.clicked.connect(self.browse_raster)
        
        # Connect the model path button to file dialog
        self.model_path.clicked.connect(self.browse_model)
        
        # Connect output path button
        self.output_path.clicked.connect(self.browse_output)
        
        # Connect run button
        self.run_button.clicked.connect(self.run_process)
        
        # Connect add_map button
        self.add_map.clicked.connect(self.add_visualizations_to_map)
        
        # Connect checkboxes for enabling/disabling the add_map button
        self.win_a.stateChanged.connect(self.update_add_map_button_state)
        self.win_b.stateChanged.connect(self.update_add_map_button_state)
        self.nir.stateChanged.connect(self.update_add_map_button_state)
        
        # Connect polygonize flag checkbox
        self.polygonize_flag.stateChanged.connect(self.update_polygonize_options)
    
    def setup_model_combo(self):
        """Setup the model selection combo box."""
        self.model_name.clear()
        for model_name in MODEL_CONFIGS.keys():
            self.model_name.addItem(model_name)
    
    def get_models_dir(self):
        """Get the directory where models should be stored."""
        # Use QGIS user profile directory to store models
        profile_dir = QgsApplication.qgisSettingsDirPath()
        models_dir = os.path.join(profile_dir, 'ftw_models')
        os.makedirs(models_dir, exist_ok=True)
        return models_dir
    
    def ensure_model_downloaded(self, model_name):
        """Ensure the selected model is downloaded and return its path."""
        if model_name not in MODEL_CONFIGS:
            return None
            
        config = MODEL_CONFIGS[model_name]
        models_dir = self.get_models_dir()
        model_path = os.path.join(models_dir, config['filename'])
        
        # Check if model exists
        if not os.path.exists(model_path):
            try:
                # Enable the cancel button and reset progress
                self.cancel_button.setEnabled(True)
                self.progress_bar.setValue(0)
                self.progress_bar.setFormat("Downloading model...")
                QtWidgets.QApplication.processEvents()
                
                def update_progress(block_num, block_size, total_size):
                    downloaded = block_num * block_size
                    if total_size > 0:
                        percent = min(100, int(downloaded * 100 / total_size))
                        self.progress_bar.setValue(percent)
                        QtWidgets.QApplication.processEvents()
                
                # Download the model
                urllib.request.urlretrieve(
                    config['url'],
                    model_path,
                    reporthook=update_progress
                )
                
                # Disable the cancel button
                self.cancel_button.setEnabled(False)
                return model_path
                
            except Exception as e:
                # Disable the cancel button
                self.cancel_button.setEnabled(False)
                QtWidgets.QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to download model: {str(e)}"
                )
                if os.path.exists(model_path):
                    os.remove(model_path)
                return None
        
        return model_path

    def populate_raster_combo(self):
        """Populate the raster combo box with available raster layers from QGIS."""
        # Clear existing items
        self.raster_name.clear()
        
        # Get all layers from the project
        layers = QgsProject.instance().mapLayers().values()
        
        # Filter and add only 8-band raster layers to the combo box
        for layer in layers:
            if isinstance(layer, QgsRasterLayer):
                # Check if the raster has 8 bands
                if layer.bandCount() == 8:
                    self.raster_name.addItem(layer.name(), layer.id())

    def browse_raster(self):
        """Open file dialog to select a raster file and add it to QGIS."""
        # Open file dialog
        file_dialog = QtWidgets.QFileDialog()
        raster_path, _ = file_dialog.getOpenFileName(
            self,
            "Select Raster Layer",
            "",
            "Raster Files (*.tif *.tiff *.img *.jp2 *.asc);;All Files (*.*)"
        )
        
        if raster_path:
            # Get the filename without extension as the layer name
            layer_name = os.path.splitext(os.path.basename(raster_path))[0]
            
            # Create and add the raster layer to QGIS
            raster_layer = QgsRasterLayer(raster_path, layer_name)
            if raster_layer.isValid():
                # Check if the raster has 8 bands
                if raster_layer.bandCount() != 8:
                    QtWidgets.QMessageBox.critical(
                        self,
                        "Error",
                        f"Invalid raster: Expected 8 bands, found {raster_layer.bandCount()} bands.\n"
                        f"Please select a valid 8-band raster."
                    )
                    return
                
                QgsProject.instance().addMapLayer(raster_layer)
                
                # Update the combo box and select the new layer
                self.populate_raster_combo()
                index = self.raster_name.findData(raster_layer.id())
                if index >= 0:
                    self.raster_name.setCurrentIndex(index)
            else:
                # Show error message if layer is invalid
                QtWidgets.QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to load raster layer: {raster_path}"
                )

    def browse_model(self):
        """Open file dialog to select a model checkpoint file."""
        # Open file dialog
        file_dialog = QtWidgets.QFileDialog()
        model_path, _ = file_dialog.getOpenFileName(
            self,
            "Select Model Checkpoint",
            "",
            "Checkpoint Files (*.ckpt);;All Files (*.*)"
        )
        
        if model_path:
            # Get the filename without extension
            model_name = os.path.splitext(os.path.basename(model_path))[0]
            
            # Check if this is a known model type
            known_model = False
            for config_name, config in MODEL_CONFIGS.items():
                if config['filename'] == os.path.basename(model_path):
                    # Select the corresponding model type in combo box
                    index = self.model_name.findText(config_name)
                    if index >= 0:
                        self.model_name.setCurrentIndex(index)
                    known_model = True
                    break
            
            if not known_model:
                # Warn user if this is not a known model type
                QtWidgets.QMessageBox.warning(
                    self,
                    "Warning",
                    f"This is not a standard FTW model checkpoint.\n\n"
                    f"Please ensure the model filename is one of:\n{valid_filenames}"
                )
            
            # Copy the model to the models directory for future use
            try:
                models_dir = self.get_models_dir()
                target_path = os.path.join(models_dir, os.path.basename(model_path))
                
                # Only copy if it's not already in the models directory
                if model_path != target_path:
                    import shutil
                    shutil.copy2(model_path, target_path)
                
            except Exception as e:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Warning",
                    f"Failed to copy model to plugin directory: {str(e)}"
                )

    def browse_output(self):
        """Open file dialog to select output location and filename."""
        # Get initial directory from current output path if it exists
        initial_dir = os.path.dirname(self.output_name.text()) if self.output_name.text() else ""
        
        # Open file dialog for saving
        file_dialog = QtWidgets.QFileDialog()
        output_path, _ = file_dialog.getSaveFileName(
            self,
            "Select Output Location",
            initial_dir,
            "GeoTIFF Files (*.tif);;All Files (*.*)"
        )
        
        if output_path:
            # Ensure the file has .tif extension
            if not output_path.lower().endswith('.tif'):
                output_path += '.tif'
            
            # Update the output name field
            self.output_name.setText(output_path)
    
    def update_add_map_button_state(self):
        """Enable or disable the add_map button based on checkbox states."""
        # Enable the button if any visualization option is checked
        self.add_map.setEnabled(
            self.win_a.isChecked() or self.win_b.isChecked() or self.nir.isChecked()
        )
    
    def update_polygonize_options(self):
        """Handle polygonize flag checkbox state change."""
        # Enable/disable simplify polygon spinbox based on checkbox state
        self.simplify_polygon.setEnabled(self.polygonize_flag.isChecked())
        
        # Get the current value if enabled
        if self.polygonize_flag.isChecked():
            self.simplify_value = self.simplify_polygon.value()
        else:
            self.simplify_value = None
    
    def add_visualizations_to_map(self):
        """Add selected visualizations to the map."""
        # Get the selected raster layer
        selected_layer_id = self.raster_name.currentData()
        if not selected_layer_id:
            QtWidgets.QMessageBox.warning(
                self,
                "Warning",
                "Please select a raster layer first."
            )
            return
            
        selected_layer = QgsProject.instance().mapLayer(selected_layer_id)
        if not selected_layer or not selected_layer.isValid():
            QtWidgets.QMessageBox.warning(
                self,
                "Warning",
                "Selected layer is not valid."
            )
            return
            
        # Create visualizations based on checkbox states
        self.visualize_bands(selected_layer)
        
    def visualize_bands(self, source_layer):
        """Create band visualizations based on checkbox states."""
        if not (self.win_a.isChecked() or self.win_b.isChecked() or self.nir.isChecked()):
            return
            
        source_path = source_layer.source()
        
        # Handle Window A visualization (Bands 1,2,3)
        if self.win_a.isChecked():
            layer_name = f"{source_layer.name()}_win_A_{str(uuid.uuid4())[:8]}"
            win_a_layer = QgsRasterLayer(source_path, layer_name)
            if win_a_layer.isValid():
                # Set band rendering for R,G,B as 1,2,3
                win_a_layer.renderer().setRedBand(1)
                win_a_layer.renderer().setGreenBand(2)
                win_a_layer.renderer().setBlueBand(3)
                QgsProject.instance().addMapLayer(win_a_layer)
            else:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Warning",
                    f"Failed to create Window A visualization for {source_layer.name()}"
                )
        
        # Handle Window B visualization (Bands 5,6,7)
        if self.win_b.isChecked():
            layer_name = f"{source_layer.name()}_win_B_{str(uuid.uuid4())[:8]}"
            win_b_layer = QgsRasterLayer(source_path, layer_name)
            if win_b_layer.isValid():
                # Set band rendering for R,G,B as 5,6,7
                win_b_layer.renderer().setRedBand(5)
                win_b_layer.renderer().setGreenBand(6)
                win_b_layer.renderer().setBlueBand(7)
                QgsProject.instance().addMapLayer(win_b_layer)
            else:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Warning",
                    f"Failed to create Window B visualization for {source_layer.name()}"
                )
        
        # Handle NIR false color visualizations
        if self.nir.isChecked():
            # NIR false color for Window A (Bands 4,1,2 for NIR,R,G)
            layer_name = f"{source_layer.name()}_NIR_A_{str(uuid.uuid4())[:8]}"
            nir_a_layer = QgsRasterLayer(source_path, layer_name)
            if nir_a_layer.isValid():
                # Set band rendering for R,G,B as 4,1,2 (NIR, Red, Green)
                nir_a_layer.renderer().setRedBand(4)
                nir_a_layer.renderer().setGreenBand(1)
                nir_a_layer.renderer().setBlueBand(2)
                QgsProject.instance().addMapLayer(nir_a_layer)
            else:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Warning",
                    f"Failed to create NIR Window A visualization for {source_layer.name()}"
                )
                
            # NIR false color for Window B (Bands 8,5,6 for NIR,R,G)
            layer_name = f"{source_layer.name()}_NIR_B_{str(uuid.uuid4())[:8]}"
            nir_b_layer = QgsRasterLayer(source_path, layer_name)
            if nir_b_layer.isValid():
                # Set band rendering for R,G,B as 8,5,6 (NIR, Red, Green)
                nir_b_layer.renderer().setRedBand(8)
                nir_b_layer.renderer().setGreenBand(5)
                nir_b_layer.renderer().setBlueBand(6)
                QgsProject.instance().addMapLayer(nir_b_layer)
            else:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Warning",
                    f"Failed to create NIR Window B visualization for {source_layer.name()}"
                )
        
        # Refresh the map canvas
        iface.mapCanvas().refresh()
        
    def detect_conda_env(self):
        """Detect conda environment and return its path."""
        # Try to find conda in common locations
        possible_conda_paths = [
            os.path.expanduser("~/anaconda3"),
            os.path.expanduser("~/miniconda3"),
            "/opt/anaconda3",
            "/opt/miniconda3"
        ]
        
        # Check if conda is in PATH
        import subprocess
        try:
            conda_path = subprocess.check_output(['which', 'conda']).decode().strip()
            if conda_path:
                # Get the conda environment path
                conda_env = subprocess.check_output(['conda', 'info', '--base']).decode().strip()
                if conda_env:
                    return conda_env
        except:
            pass
            
        # If not found in PATH, check common locations
        for path in possible_conda_paths:
            if os.path.exists(path):
                return path
                
        return None
        
    def load_settings(self):
        """Load plugin settings from JSON file."""
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                    if 'conda_path' in settings:
                        # Validate the saved conda path
                        conda_path = settings['conda_path']
                        if os.path.exists(conda_path):
                            self.conda_path = conda_path
                            # Load environment name if it exists, otherwise use default
                            self.env_name = settings.get('env_name', 'ftw_plugin')
                            return
            except Exception as e:
                print(f"Error loading settings: {str(e)}")
        
        # If no valid settings found, set defaults
        self.conda_path = None
        self.env_name = 'ftw_plugin'
        
    def save_settings(self, conda_path):
        """Save plugin settings to JSON file."""
        try:
            settings = {
                'conda_path': conda_path,
                'env_name': getattr(self, 'env_name', 'ftw_plugin')
            }
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f)
            self.conda_path = conda_path
        except Exception as e:
            print(f"Error saving settings: {str(e)}")
            
    def collect_inputs(self):
        """Collect and validate all necessary inputs for model processing."""
        inputs = {}
        
        # Get raster layer
        selected_layer_id = self.raster_name.currentData()
        if not selected_layer_id:
            QtWidgets.QMessageBox.warning(
                self,
                "Warning",
                "Please select a raster layer first."
            )
            return None
            
        selected_layer = QgsProject.instance().mapLayer(selected_layer_id)
        if not selected_layer or not selected_layer.isValid():
            QtWidgets.QMessageBox.warning(
                self,
                "Warning",
                "Selected layer is not valid."
            )
            return None
            
        # Get the actual raster file path
        raster_path = selected_layer.source()
        if not raster_path or not os.path.exists(raster_path):
            QtWidgets.QMessageBox.warning(
                self,
                "Warning",
                "Could not find the raster file path."
            )
            return None
            
        inputs['raster_path'] = raster_path
        
        # Get model path
        selected_model = self.model_name.currentText()
        model_path = self.ensure_model_downloaded(selected_model)
        if not model_path:
            QtWidgets.QMessageBox.warning(
                self,
                "Warning",
                "Failed to get model checkpoint."
            )
            return None
        inputs['model_path'] = model_path
        
        # Get output path
        output_path = self.output_name.text()
        if not output_path:
            import tempfile
            output_path = os.path.join(tempfile.gettempdir(), "ftw_output.tif")
            self.output_name.setText(output_path)
        
        # Ensure output directory exists
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
            except Exception as e:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Warning",
                    f"Failed to create output directory: {str(e)}"
                )
                return None
        inputs['output_path'] = output_path
        
        # Get polygonize options
        inputs['polygonize_enabled'] = self.polygonize_flag.isChecked()
        if inputs['polygonize_enabled']:
            inputs['simplify_value'] = self.simplify_polygon.value()
        
        # Get model type (2 or 3 classes)
        inputs['model_type'] = "3" if selected_model == "FTW 3 Classes" else "2"
        
        # Get conda environment path
        if self.conda_path and os.path.exists(self.conda_path):
            inputs['conda_path'] = self.conda_path
        else:
            conda_path = self.detect_conda_env()
            if not conda_path:
                # Prompt user for conda path
                conda_path, ok = QtWidgets.QInputDialog.getText(
                    self,
                    "Conda Environment",
                    "Please enter the path to your conda environment (e.g., ~/anaconda3 or ~/miniconda3) or the full path to conda.sh:",
                    text=os.path.expanduser("~/anaconda3")
                )
                if not ok or not conda_path:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Warning",
                        "Conda environment path is required."
                    )
                    return None
                    
                # Expand any user path (e.g., ~) to full path
                conda_path = os.path.expanduser(conda_path)
                
                # Check if the path is to conda.sh
                if conda_path.endswith('conda.sh'):
                    if not os.path.exists(conda_path):
                        QtWidgets.QMessageBox.warning(
                            self,
                            "Warning",
                            f"Conda setup script not found at: {conda_path}"
                        )
                        return None
                    conda_sh_path = conda_path
                else:
                    # If it's a parent directory, construct the conda.sh path
                    if not os.path.exists(conda_path):
                        QtWidgets.QMessageBox.warning(
                            self,
                            "Warning",
                            f"Conda environment not found at: {conda_path}"
                        )
                        return None
                        
                    conda_sh_path = os.path.join(conda_path, "etc", "profile.d", "conda.sh")
                    if not os.path.exists(conda_sh_path):
                        QtWidgets.QMessageBox.warning(
                            self,
                            "Warning",
                            f"Conda setup script not found at: {conda_sh_path}"
                        )
                        return None
                
                # Save the valid conda path
                self.save_settings(conda_sh_path)
                inputs['conda_path'] = conda_sh_path
            else:
                inputs['conda_path'] = conda_path
        
        # Add environment name to inputs
        inputs['env_name'] = getattr(self, 'env_name', 'ftw_plugin')
        
        return inputs
    
    def run_process(self):
        """Handle the run button click event."""
        # Collect and validate all inputs
        self.inputs = self.collect_inputs()
        if self.inputs is None:
            return
            
        try:
            # Enable the cancel button and reset progress
            self.cancel_button.setEnabled(True)
            self.progress_bar.setValue(0)
            
            # Update progress message for environment setup
            self.progress_bar.setFormat("Setting up a conda environment...")
            QtWidgets.QApplication.processEvents()
            
            # Run environment setup in a separate thread
            from PyQt5.QtCore import QThread, pyqtSignal
            
            class SetupThread(QThread):
                finished = pyqtSignal(bool, str)  # success, message
                progress = pyqtSignal(int, str)   # value, message
                
                def __init__(self, conda_path, env_name):
                    super().__init__()
                    self.conda_path = conda_path
                    self.env_name = env_name
                
                def run(self):
                    try:
                        # Create a callback function to emit progress updates
                        def progress_callback(value, message):
                            self.progress.emit(value, message)
                        
                        # Run the setup process
                        setup_ftw_env(self.conda_path, self.env_name, progress_callback)
                        self.finished.emit(True, "Environment setup completed successfully!")
                    except Exception as e:
                        self.finished.emit(False, str(e))
            
            # Create and start the setup thread
            self.setup_thread = SetupThread(self.inputs['conda_path'], self.inputs['env_name'])
            self.setup_thread.finished.connect(self.handle_setup_finished)
            self.setup_thread.progress.connect(self.update_progress)
            self.setup_thread.start()
            
        except Exception as e:
            # Disable the cancel button
            self.cancel_button.setEnabled(False)
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"An error occurred during processing: {str(e)}"
            )
    
    def handle_setup_finished(self, success, message):
        """Handle the completion of the environment setup."""
        if success:
            # Start the inference process
            self.start_inference()
        else:
            # Disable the cancel button and show error
            self.cancel_button.setEnabled(False)
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                message
            )
    
    def start_inference(self):
        """Start the inference process after successful environment setup."""
        # Run inference in a separate thread
        from PyQt5.QtCore import QThread, pyqtSignal
        
        class InferenceThread(QThread):
            finished = pyqtSignal(bool, str)  # success, message
            progress = pyqtSignal(int, str)   # value, message
            
            def __init__(self, inputs):
                super().__init__()
                self.inputs = inputs
            
            def run(self):
                try:
                    # Create a callback function to emit progress updates
                    def progress_callback(value, message):
                        self.progress.emit(value, message)
                    
                    # Pass the callback to run_inference
                    run_inference(self.inputs, progress_callback)
                    self.finished.emit(True, "Processing completed successfully!")
                except Exception as e:
                    self.finished.emit(False, str(e))
        
        # Create and start the inference thread
        self.inference_thread = InferenceThread(self.inputs)
        self.inference_thread.finished.connect(self.handle_inference_finished)
        self.inference_thread.progress.connect(self.update_progress)
        self.inference_thread.start()

    def handle_inference_finished(self, success, message):
        """Handle the completion of the inference process."""
        # Disable the cancel button
        self.cancel_button.setEnabled(False)
        
        if success:
            # Add the output raster to the map
            output_path = self.inputs['output_path']
            if os.path.exists(output_path):
                # Get the filename without extension as the layer name
                layer_name = os.path.splitext(os.path.basename(output_path))[0]
                
                # Create and add the raster layer to QGIS
                raster_layer = QgsRasterLayer(output_path, layer_name)
                if raster_layer.isValid():
                    QgsProject.instance().addMapLayer(raster_layer)
                    message += "\nOutput raster has been added to the map."
                else:
                    message += "\nWarning: Could not load output raster."
            else:
                message += "\nWarning: Output file not found."
            
            QtWidgets.QMessageBox.information(
                self,
                "Success",
                message
            )
        else:
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                message
            )
    
    def update_progress(self, value, message):
        """Update the progress bar with a new value and message."""
        self.progress_bar.setValue(value)
        self.progress_bar.setFormat(message)
        QtWidgets.QApplication.processEvents()


def setup_ftw_env(conda_setup, env_name, progress_callback=None):
    """Set up the FTW environment with progress updates."""
    os.environ.pop("PYTHONHOME", None)
    os.environ.pop("PYTHONPATH", None)

    bash_script = f"""
    source "{conda_setup}"

    # Step 1: Create env if it doesn't exist
    if ! conda env list | grep -q "^{env_name}"; then
        echo "[PROGRESS] 25 Creating conda environment '{env_name}'..."
        conda create -y -n {env_name} python=3.9
    else
        echo "[PROGRESS] 25 Conda environment '{env_name}' already exists."
    fi

    # Step 2: Try to run 'ftw inference --help'
    echo "[PROGRESS] 50 Checking if 'ftw' CLI is available..."
    conda activate {env_name}
    if ftw inference --help > /dev/null 2>&1; then
        echo "[PROGRESS] 75 'ftw' CLI already available. Skipping installation."
    else
        echo "[PROGRESS] 75 Installing required packages..."
        conda install -y -c conda-forge gdal rasterio pyproj libgdal-arrow-parquet
        pip install ftw-tools
    fi

    # Final Test
    echo "[PROGRESS] 90 Final test of 'ftw inference --help'"
    ftw inference --help
    echo "[PROGRESS] 100 Setup complete"
    """

    try:
        process = subprocess.Popen(
            ["bash", "-c", bash_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        # Store output for error reporting
        stdout_lines = []
        stderr_lines = []

        # Read output line by line and update progress
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                line = line.strip()
                stdout_lines.append(line)
                
                # Handle different types of output
                if "[PROGRESS]" in line:
                    try:
                        progress = int(line.split()[1])
                        message = line.split("] ", 1)[1]
                        if progress_callback:
                            progress_callback(progress, message)
                    except ValueError:
                        pass
                elif "[INFO]" in line:
                    print(line.split("] ", 1)[1])
                elif "[ERROR]" in line:
                    print(f"Error: {line.split('] ', 1)[1]}")

        # Get any remaining output
        remaining_stdout, remaining_stderr = process.communicate()
        stdout_lines.extend(remaining_stdout.splitlines())
        stderr_lines.extend(remaining_stderr.splitlines())

        if process.returncode != 0:
            error_msg = "Environment setup failed:\n"
            error_msg += "\n".join(line for line in stderr_lines if line.strip())
            raise Exception(error_msg)

    finally:
        if 'process' in locals():
            process.stdout.close()
            process.stderr.close()
            process.terminate()

    return True

def run_inference(inputs, progress_callback=None):
    """Run FTW inference (and optional polygonization) inside a Conda environment with progress updates."""
    os.environ.pop("PYTHONHOME", None)
    os.environ.pop("PYTHONPATH", None)

    conda_setup = inputs['conda_path']
    raster_path = inputs['raster_path']
    model_path = inputs['model_path']
    output_path = inputs['output_path']
    env_name = inputs.get('env_name', 'ftw_plugin')
    polygonize_enabled = inputs.get('polygonize_enabled', False)
    simplify_value = inputs.get('simplify_value', 20)

    # Prepare polygonization command if enabled
    polygonize_command = ""
    if polygonize_enabled:
        polygonize_command = f"""
        echo "[PROGRESS] 90 Running polygonization..."
        if ! ftw inference polygonize "{output_path}" --simplify {simplify_value}; then
            echo "[ERROR] Polygonization failed"
            exit 1
        fi
        echo "[PROGRESS] 95 Polygonization complete"
        """

    bash_script = f"""
    source "{conda_setup}"
    conda activate {env_name}

    # Run inference
    echo "[PROGRESS] 45 Running inference..."
    echo "[INFO] Using model: {model_path}"
    echo "[INFO] Processing raster: {raster_path}"
    
    if ! ftw inference run "{raster_path}" --model "{model_path}" --out "{output_path}" --overwrite; then
        echo "[ERROR] Inference failed"
        exit 1
    fi
    echo "[PROGRESS] 85 Inference complete"

    # Optional polygonization
    {polygonize_command}

    echo "[PROGRESS] 100 Process complete"
    """

    try:
        process = subprocess.Popen(
            ["bash", "-c", bash_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        # Store output for error reporting
        stdout_lines = []
        stderr_lines = []

        # Read output line by line and update progress
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                line = line.strip()
                stdout_lines.append(line)
                
                # Handle different types of output
                if "[PROGRESS]" in line:
                    try:
                        progress = int(line.split()[1])
                        message = line.split("] ", 1)[1]
                        if progress_callback:
                            progress_callback(progress, message)
                    except ValueError:
                        pass
                elif "[INFO]" in line:
                    print(line.split("] ", 1)[1])
                elif "[ERROR]" in line:
                    print(f"Error: {line.split('] ', 1)[1]}")

        # Get any remaining output
        remaining_stdout, remaining_stderr = process.communicate()
        stdout_lines.extend(remaining_stdout.splitlines())
        stderr_lines.extend(remaining_stderr.splitlines())

        if process.returncode != 0:
            error_msg = "Process failed:\n"
            error_msg += "\n".join(line for line in stderr_lines if line.strip())
            raise Exception(error_msg)

    finally:
        if 'process' in locals():
            process.stdout.close()
            process.stderr.close()
            process.terminate()

    return True