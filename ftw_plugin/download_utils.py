import os
from datetime import datetime, timedelta
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
import subprocess
import sys
import tempfile

def parse_coordinates(coord_str):
    """
    Parse coordinates string in format 'topleft lon, topleft lat; bottom right lon, bottom right lat [projection]'
    Returns a tuple containing:
    - center coordinates in WGS84 (EPSG:4326)
    - top-left coordinates in WGS84 (EPSG:4326)
    - bottom-right coordinates in WGS84 (EPSG:4326)
    Each coordinate is returned as (lon, lat)
    """
    # Extract coordinates and projection
    coords_part = coord_str.split('[')[0].strip()
    proj_part = coord_str.split('[')[1].strip(']') if '[' in coord_str else 'EPSG:4326'
    
    # Parse coordinates
    top_left, bottom_right = coords_part.split(';')
    tl_lon, tl_lat = map(float, top_left.split(','))
    br_lon, br_lat = map(float, bottom_right.split(','))
    
    # If projection is not WGS84, transform coordinates
    if proj_part != 'EPSG:4326':
        source_crs = QgsCoordinateReferenceSystem(proj_part)
        dest_crs = QgsCoordinateReferenceSystem('EPSG:4326')
        transform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())
        
        # Transform all coordinates
        tl_point = transform.transform(tl_lon, tl_lat)
        br_point = transform.transform(br_lon, br_lat)
        
        tl_lon, tl_lat = tl_point.x(), tl_point.y()
        br_lon, br_lat = br_point.x(), br_point.y()
    
    # Calculate center
    center_lon = (tl_lon + br_lon) / 2
    center_lat = (tl_lat + br_lat) / 2
    
    return (center_lon, center_lat), (tl_lon, tl_lat), (br_lon, br_lat)

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

def extract_patch(top_left, bottom_right, win_a_start, win_a_end, win_b_start, win_b_end, output_dir, output_filename, max_cloud_cover=20, conda_env=None):
    """Extract a patch of Sentinel-2 data using the specified parameters."""
    try:
        # Create a temporary Python script
        script_content = """
import os
import sys
import subprocess
import pystac_client
import planetary_computer

MSPC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION_ID = "sentinel-2-l2a"

def get_best_image_ids(top_left, bottom_right, win_a_start, win_a_end, win_b_start, win_b_end, max_cloud_cover=20):
    catalog = pystac_client.Client.open(
        MSPC_URL,
        modifier=planetary_computer.sign_inplace,
    )

    min_lon, min_lat = top_left[0], bottom_right[1]
    max_lon, max_lat = bottom_right[0], top_left[1]
    bbox_geom = {
        "type": "Polygon",
        "coordinates": [[
            [min_lon, min_lat],
            [min_lon, max_lat],
            [max_lon, max_lat],
            [max_lon, min_lat],
            [min_lon, min_lat],
        ]]
    }

    def find_best_image(start_date, end_date, cloud_threshold):
        time_range = f"{start_date}/{end_date}"
        print(f"Searching for images between {start_date} and {end_date} with cloud cover < {cloud_threshold}%")
        
        search = catalog.search(
            collections=[COLLECTION_ID],
            intersects=bbox_geom,
            datetime=time_range,
            query={"eo:cloud_cover": {"lt": cloud_threshold}},
        )

        items = search.item_collection()
        if len(items) == 0:
            print(f"No images found with cloud cover < {cloud_threshold}%")
            return None
            
        best_item = min(items, key=lambda item: item.properties.get("eo:cloud_cover", 100))
        cloud_cover = best_item.properties.get("eo:cloud_cover", 100)
        print(f"Found image from {best_item.datetime.date()} with {cloud_cover}% cloud coverage")
        return best_item.id

    # Try different cloud cover thresholds if needed
    cloud_thresholds = [max_cloud_cover, 50, 70, 100]
    win_a_id = None
    win_b_id = None
    
    for threshold in cloud_thresholds:
        if win_a_id is None:
            win_a_id = find_best_image(win_a_start, win_a_end, threshold)
        if win_b_id is None:
            win_b_id = find_best_image(win_b_start, win_b_end, threshold)
        if win_a_id is not None and win_b_id is not None:
            break
            
    if win_a_id is None:
        raise ValueError(f"Could not find suitable images for window A ({win_a_start} to {win_a_end}) even with 100% cloud cover")
    if win_b_id is None:
        raise ValueError(f"Could not find suitable images for window B ({win_b_start} to {win_b_end}) even with 100% cloud cover")

    return win_a_id, win_b_id, [min_lon, min_lat, max_lon, max_lat]

if __name__ == "__main__":
    # Get command line arguments
    top_left = eval(sys.argv[1])  # Convert string tuple to actual tuple
    bottom_right = eval(sys.argv[2])  # Convert string tuple to actual tuple
    win_a_start = sys.argv[3]
    win_a_end = sys.argv[4]
    win_b_start = sys.argv[5]
    win_b_end = sys.argv[6]
    output_dir = sys.argv[7]
    output_filename = sys.argv[8]
    max_cloud_cover = int(sys.argv[9])
    conda_env = sys.argv[10] if len(sys.argv) > 10 else None

    # Get best image IDs and bbox
    win_a_id, win_b_id, bbox_list = get_best_image_ids(
        top_left, bottom_right,
        win_a_start, win_a_end,
        win_b_start, win_b_end,
        max_cloud_cover
    )

    # Format bbox as string
    bbox_str = ",".join(map(str, bbox_list))

    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Determine ftw command path
    if conda_env:
        if os.name == 'nt':  # Windows
            ftw_cmd = os.path.join(conda_env, 'Scripts', 'ftw.exe')
        else:  # Unix-like
            ftw_cmd = os.path.join(conda_env, 'bin', 'ftw')
    else:
        ftw_cmd = 'ftw'  # Try to use system ftw

    # Check if ftw command exists
    if not os.path.exists(ftw_cmd):
        raise FileNotFoundError(f"ftw command not found at {ftw_cmd}. Please ensure it is installed in the conda environment.")

    # Run ftw command
    cmd = [
        ftw_cmd, "inference", "download",
        "--win_a", win_a_id,
        "--win_b", win_b_id,
        "--out", os.path.join(output_dir, output_filename),
        "--bbox", bbox_str,
        "--overwrite"
    ]
    
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    print(os.path.join(output_dir, output_filename))
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
            str(top_left),  # Convert tuple to string
            str(bottom_right),  # Convert tuple to string
            win_a_start,
            win_a_end,
            win_b_start,
            win_b_end,
            output_dir,
            output_filename,
            str(max_cloud_cover),
            conda_env if conda_env else ""  # Pass conda_env path if available
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