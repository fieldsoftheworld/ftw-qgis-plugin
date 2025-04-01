import os
from datetime import datetime, timedelta
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
import subprocess
import sys
import tempfile

def parse_coordinates(coord_str):
    """
    Parse coordinates string in format 'topleft lon, topleft lat; bottom right lon, bottom right lat [projection]'
    Returns center coordinates in WGS84 (EPSG:4326)
    """
    # Extract coordinates and projection
    coords_part = coord_str.split('[')[0].strip()
    proj_part = coord_str.split('[')[1].strip(']') if '[' in coord_str else 'EPSG:4326'
    
    # Parse coordinates
    top_left, bottom_right = coords_part.split(';')
    tl_lon, tl_lat = map(float, top_left.split(','))
    br_lon, br_lat = map(float, bottom_right.split(','))
    
    # Calculate center
    center_lon = (tl_lon + br_lon) / 2
    center_lat = (tl_lat + br_lat) / 2
    
    # If projection is not WGS84, transform coordinates
    if proj_part != 'EPSG:4326':
        source_crs = QgsCoordinateReferenceSystem(proj_part)
        dest_crs = QgsCoordinateReferenceSystem('EPSG:4326')
        transform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())
        center_point = transform.transform(center_lon, center_lat)
        center_lon, center_lat = center_point.x(), center_point.y()
    
    return center_lon, center_lat

def calculate_window_dates(sos_date, eos_date):
    """
    Calculate window dates based on SOS and EOS dates.
    """
    # Convert string dates to datetime objects
    sos = datetime.strptime(sos_date, '%Y-%m-%d')
    eos = datetime.strptime(eos_date, '%Y-%m-%d')
    
    # Calculate window dates
    win_a_start = (sos - timedelta(days=15)).strftime('%Y-%m-%d')
    win_a_end = (sos + timedelta(days=15)).strftime('%Y-%m-%d')
    win_b_start = (eos - timedelta(days=30)).strftime('%Y-%m-%d')
    win_b_end = eos.strftime('%Y-%m-%d')
    
    return win_a_start, win_a_end, win_b_start, win_b_end

def extract_patch(lon, lat, win_a_start, win_a_end, win_b_start, win_b_end, output_dir, output_filename, max_cloud_cover=70, patch_size=1024, conda_env=None):
    """Extract a patch of Sentinel-2 data using the specified parameters."""
    try:
        # Create a temporary Python script
        script_content = """
import os
import sys
import time
import warnings
import numpy as np
from datetime import datetime

import pystac_client
import planetary_computer
import stackstac
import rioxarray
import xarray as xr
from tqdm.auto import tqdm
from shapely.geometry import shape, box

# Constants
MSPC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION_ID = "sentinel-2-l2a"
BANDS_OF_INTEREST = ["B04", "B03", "B02", "B08"]

def download_sentinel2(lon, lat, win_a_start, win_a_end, win_b_start, win_b_end, output_dir, output_filename, max_cloud_cover=70, patch_size=1024):
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Initialize the STAC client
    catalog = pystac_client.Client.open(
        MSPC_URL,
        modifier=planetary_computer.sign_inplace,
    )
    
    # Define the point of interest
    area_of_interest = {"type": "Point", "coordinates": [lon, lat]}
    
    # Function to find best image in a date range
    def find_best_image(start_date, end_date):
        time_of_interest = f"{start_date}/{end_date}"
        print(f"\\nSearching for images between {start_date} and {end_date}")
        
        search = catalog.search(
            collections=[COLLECTION_ID],
            intersects=area_of_interest,
            datetime=time_of_interest,
            query={"eo:cloud_cover": {"lt": max_cloud_cover}},
        )
        
        items = search.item_collection()
        if len(items) == 0:
            print("No suitable images found in this date range")
            return None
            
        # Find least cloudy image
        least_cloudy_item = min(items, key=lambda item: item.properties.get("eo:cloud_cover", 100))
        print(f"Selected image from {least_cloudy_item.datetime.date()} with {least_cloudy_item.properties.get('eo:cloud_cover', 100)}% cloud coverage")
        return least_cloudy_item
    
    # Find best images for each window
    win_a_item = find_best_image(win_a_start, win_a_end)
    win_b_item = find_best_image(win_b_start, win_b_end)
    
    if win_a_item is None or win_b_item is None:
        raise ValueError(f"Could not find suitable images (cloud coverage <= {max_cloud_cover}%) in the specified date ranges")
    
    # Process both images
    print("Processing images")
    tic = time.time()
    
    # Create stacks for both images
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stack_a = stackstac.stack(
            win_a_item,
            assets=BANDS_OF_INTEREST,
        )
        stack_b = stackstac.stack(
            win_b_item,
            assets=BANDS_OF_INTEREST,
        )
    
    # Get the center point of the image
    _, _, height, width = stack_a.shape
    center_x = width // 2
    center_y = height // 2
    
    # Extract patches centered on the point
    x_start = center_x - patch_size // 2
    y_start = center_y - patch_size // 2
    
    patch_a = stack_a[0, :, y_start:y_start + patch_size, x_start:x_start + patch_size].compute()
    patch_b = stack_b[0, :, y_start:y_start + patch_size, x_start:x_start + patch_size].compute()
    
    # Combine the patches and reorganize dimensions
    combined = xr.concat([patch_a, patch_b], dim="time", coords="minimal", compat="override")
    
    # Reorganize dimensions to (time, band, y, x)
    combined = combined.transpose("time", "band", "y", "x")
    
    # Create output filename
    output_file = os.path.join(output_dir, output_filename)
    
    # Write the output - combine both time steps into a single 8-band image
    print("Writing output")
    
    # Stack bands into a single dimension
    combined = combined.stack(bands=("time", "band"))
    combined = combined.transpose("bands", "y", "x")
    
    # Add band descriptions
    band_descriptions = {
        1: f"B04_{win_a_item.datetime.date()}",
        2: f"B03_{win_a_item.datetime.date()}",
        3: f"B02_{win_a_item.datetime.date()}",
        4: f"B08_{win_a_item.datetime.date()}",
        5: f"B04_{win_b_item.datetime.date()}",
        6: f"B03_{win_b_item.datetime.date()}",
        7: f"B02_{win_b_item.datetime.date()}",
        8: f"B08_{win_b_item.datetime.date()}"
    }
    
    # Write the data first
    combined.rio.to_raster(
        output_file,
        driver="GTiff",
        compress="deflate",
        dtype="uint16",
        tiled=True,
        blockxsize=256,
        blockysize=256,
        tags={
            "TIFFTAG_DATETIME": datetime.now().strftime("%Y:%m:%d %H:%M:%S")
        }
    )
    
    # Add band descriptions using GDAL
    from osgeo import gdal
    ds = gdal.Open(output_file, gdal.GA_Update)
    for i, desc in band_descriptions.items():
        ds.GetRasterBand(i).SetDescription(desc)
    ds = None  # Close the dataset
    
    print(f"Saved {output_file}")
    print(f"Finished processing in {time.time()-tic:.2f} seconds")
    return output_file

if __name__ == "__main__":
    # Get command line arguments
    lon = float(sys.argv[1])
    lat = float(sys.argv[2])
    win_a_start = sys.argv[3]
    win_a_end = sys.argv[4]
    win_b_start = sys.argv[5]
    win_b_end = sys.argv[6]
    output_dir = sys.argv[7]
    output_filename = sys.argv[8]
    max_cloud_cover = int(sys.argv[9])
    patch_size = int(sys.argv[10])
    
    # Download the patch
    output_file = download_sentinel2(
        lon=lon,
        lat=lat,
        win_a_start=win_a_start,
        win_a_end=win_a_end,
        win_b_start=win_b_start,
        win_b_end=win_b_end,
        output_dir=output_dir,
        output_filename=output_filename,
        max_cloud_cover=max_cloud_cover,
        patch_size=patch_size,
    )
    
    # Print the output file path
    print(output_file)
"""
        
        # Create a temporary script file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(script_content)
            script_path = f.name
        
        # Get the Python executable from the conda environment
        if conda_env:
            if os.name == 'nt':  # Windows
                python_exe = os.path.join(conda_env, 'python.exe')
            else:  # Unix-like
                python_exe = os.path.join(conda_env, 'bin', 'python')
        else:
            python_exe = sys.executable
        
        # Run the script
        cmd = [
            python_exe,
            script_path,
            str(lon),
            str(lat),
            win_a_start,
            win_a_end,
            win_b_start,
            win_b_end,
            output_dir,
            output_filename,
            str(max_cloud_cover),
            str(patch_size)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # Clean up the temporary script
        os.unlink(script_path)
        
        # Check for errors
        if result.returncode != 0:
            raise RuntimeError(f"Script failed: {result.stderr}")
        
        # Get the output file path from the last line of output
        output_file = result.stdout.strip().split('\n')[-1]
        
        return output_file
        
    except Exception as e:
        raise RuntimeError(f"Failed to extract patch: {str(e)}") 