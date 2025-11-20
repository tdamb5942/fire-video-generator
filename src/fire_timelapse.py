#!/usr/bin/env python3
"""
NASA FIRMS Fire Timelapse Generator

Generates MP4 timelapse videos showing fire activity heatmaps within a GeoJSON-defined
Area of Interest (AOI) using NASA FIRMS MODIS_SP data.

Author: Generated with Claude Code
License: MIT
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from io import StringIO

import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap
import seaborn as sns
import requests
import imageio.v3 as iio
from shapely.geometry import Point, box
from tqdm import tqdm
from PIL import Image

try:
    import contextily as cx
    HAS_CONTEXTILY = True
except ImportError:
    HAS_CONTEXTILY = False

try:
    from dotenv import load_dotenv
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False


# Configuration
API_BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
SOURCE = "MODIS_SP"
CACHE_DIR = Path(".cache")
FRAMES_DIR = Path("outputs/frames")
VIDEOS_DIR = Path("outputs/videos")

# Rate limiting for API requests (now using sequential processing)
_last_api_call_time = None
API_CALL_DELAY = 0.3  # Minimum seconds between API calls - conservative but not too slow

# Custom heatmap colormap: 10-color gradient from colleague's style reference
# Dark blue held longer (0-20%), cream introduced sooner (90%)
FIRE_CMAP = LinearSegmentedColormap.from_list(
    'fire_heatmap',
    [
        (0.00, '#182B4C'),  # Dark blue (0-20%)
        (0.20, '#0E2585'),  # Begin color progression at 20%
        (0.30, '#0B239B'),
        (0.40, '#201BA4'),
        (0.50, '#2F1B89'),
        (0.60, '#551771'),
        (0.70, '#9E0E3F'),
        (0.80, '#D71510'),
        (0.90, '#FFCE63'),  # Yellow at 90%
        (1.00, '#FFF7E1'),  # Cream at top
    ],
    N=256
)


def get_map_key():
    """
    Retrieve NASA FIRMS MAP_KEY from .env file, environment variable, or config file.

    Returns:
        str: The MAP_KEY for API authentication

    Raises:
        SystemExit: If MAP_KEY is not configured
    """
    # Load .env file if available
    if HAS_DOTENV:
        load_dotenv()

    # Try environment variable first (includes .env variables)
    map_key = os.environ.get("FIRMS_MAP_KEY")

    if not map_key:
        # Try config file
        config_file = Path("config.json")
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    map_key = config.get("MAP_KEY")
            except Exception as e:
                print(f"Error reading config.json: {e}", file=sys.stderr)

    if not map_key:
        print("ERROR: NASA FIRMS MAP_KEY not configured!", file=sys.stderr)
        print("\nPlease set the MAP_KEY using one of these methods:", file=sys.stderr)
        print("  1. Create .env file: FIRMS_MAP_KEY=your_key_here", file=sys.stderr)
        print("  2. Environment variable: export FIRMS_MAP_KEY='your_key_here'", file=sys.stderr)
        print("  3. Create config.json: {\"MAP_KEY\": \"your_key_here\"}", file=sys.stderr)
        print("\nGet your free MAP_KEY at: https://firms.modaps.eosdis.nasa.gov/api/map_key/", file=sys.stderr)
        sys.exit(1)

    return map_key


def load_aoi(geojson_path):
    """
    Load GeoJSON file and extract the area of interest.

    Args:
        geojson_path (str): Path to GeoJSON file

    Returns:
        gpd.GeoDataFrame: GeoDataFrame containing the AOI

    Raises:
        SystemExit: If file doesn't exist or is invalid
    """
    geojson_file = Path(geojson_path)

    if not geojson_file.exists():
        print(f"ERROR: GeoJSON file not found: {geojson_path}", file=sys.stderr)
        sys.exit(1)

    try:
        aoi = gpd.read_file(geojson_file)

        # Ensure WGS84 coordinate system (EPSG:4326)
        if aoi.crs is None:
            print("Warning: No CRS specified, assuming WGS84 (EPSG:4326)")
            aoi.set_crs("EPSG:4326", inplace=True)
        elif aoi.crs != "EPSG:4326":
            print(f"Converting from {aoi.crs} to EPSG:4326")
            aoi = aoi.to_crs("EPSG:4326")

        return aoi

    except Exception as e:
        print(f"ERROR: Failed to load GeoJSON file: {e}", file=sys.stderr)
        sys.exit(1)


def get_bounding_box(aoi, buffer_km=25):
    """
    Extract bounding box from GeoDataFrame with buffer.

    Args:
        aoi (gpd.GeoDataFrame): Area of interest
        buffer_km (float): Buffer distance in kilometers (default: 25km)

    Returns:
        str: Bounding box as 'west,south,east,north'
    """
    # Get the centroid of the AOI for creating a custom projection
    aoi_centroid = aoi.unary_union.centroid
    lon, lat = aoi_centroid.x, aoi_centroid.y

    # Create a custom Azimuthal Equidistant projection centered on the AOI
    # This preserves distances accurately from the center point
    custom_crs = f"+proj=aeqd +lat_0={lat} +lon_0={lon} +x_0=0 +y_0=0 +datum=WGS84 +units=m"

    # Project to custom CRS, buffer in meters, then project back to WGS84
    aoi_projected = aoi.to_crs(custom_crs)
    aoi_buffered = aoi_projected.buffer(buffer_km * 1000)  # Convert km to meters
    aoi_buffered_gdf = gpd.GeoDataFrame(geometry=aoi_buffered, crs=custom_crs)
    aoi_buffered_wgs84 = aoi_buffered_gdf.to_crs("EPSG:4326")

    # Get bounding box of buffered AOI
    bounds = aoi_buffered_wgs84.total_bounds  # [minx, miny, maxx, maxy]
    return f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}"


def generate_date_chunks(start_date, end_date, chunk_size=10, max_total_days=None):
    """
    Generate date ranges in chunks (NASA FIRMS API limit is 10 days).

    Args:
        start_date (datetime): Start date
        end_date (datetime): End date
        chunk_size (int): Maximum days per chunk (default 10)
        max_total_days (int): Maximum total days to request in single batch (helps avoid API issues)

    Yields:
        tuple: (chunk_start, chunk_end, day_range) for each chunk
    """
    # If max_total_days specified, break into year-sized batches
    if max_total_days and (end_date - start_date).days > max_total_days:
        batch_start = start_date
        while batch_start <= end_date:
            batch_end = min(batch_start + timedelta(days=max_total_days - 1), end_date)
            # Recursively generate chunks for this batch
            for chunk_start, chunk_end, day_range in generate_date_chunks(batch_start, batch_end, chunk_size, None):
                yield chunk_start, chunk_end, day_range
            batch_start = batch_end + timedelta(days=1)
        return

    current = start_date
    while current <= end_date:
        chunk_end = min(current + timedelta(days=chunk_size - 1), end_date)
        day_range = (chunk_end - current).days + 1

        yield current, chunk_end, day_range

        current = chunk_end + timedelta(days=1)


def get_cache_path(url):
    """
    Generate cache file path based on URL hash.

    Args:
        url (str): API URL

    Returns:
        Path: Path to cache file
    """
    url_hash = hashlib.md5(url.encode()).hexdigest()
    return CACHE_DIR / f"{url_hash}.csv"


def fetch_single_chunk(args):
    """Fetch a single chunk of data (used for parallel processing)."""
    chunk_start, chunk_end, day_range, map_key, bbox, use_cache = args

    date_str = chunk_start.strftime("%Y-%m-%d")
    url = f"{API_BASE_URL}/{map_key}/{SOURCE}/{bbox}/{day_range}/{date_str}"
    cache_path = get_cache_path(url)

    # Check cache first
    if use_cache and cache_path.exists():
        try:
            content = cache_path.read_text()
            if content == "No data":
                return None, True, False, None  # None, from_cache, api_called, error
            df = pd.read_csv(cache_path)
            return df, True, False, None
        except Exception:
            pass  # Fall through to API call

    # Make API request with retries
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Global rate limiting - ensure minimum delay between API calls
            global _last_api_call_time
            if _last_api_call_time is not None:
                elapsed = time.time() - _last_api_call_time
                if elapsed < API_CALL_DELAY:
                    time.sleep(API_CALL_DELAY - elapsed)
            _last_api_call_time = time.time()

            # Add small delay to respect API rate limits
            if attempt > 0:
                time.sleep(1 + attempt)  # Increasing delay on retries

            response = requests.get(url, timeout=30)
            response.raise_for_status()

            # Handle "No data" response
            if response.text.strip().lower() == "no data":
                if use_cache:
                    cache_path.write_text("No data")
                return None, False, True, None

            # Parse CSV response
            df = pd.read_csv(StringIO(response.text))

            if not df.empty:
                # Cache the response
                if use_cache:
                    df.to_csv(cache_path, index=False)
                return df, False, True, None

            return None, False, True, None

        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                # Retry with exponential backoff - longer delays for 403 errors (rate limiting)
                if "403" in str(e) or "Forbidden" in str(e):
                    delay = 5 * (2 ** attempt)  # 5, 10, 20 seconds for rate limit errors
                else:
                    delay = 2 ** attempt  # 1, 2, 4 seconds for other errors
                time.sleep(delay)
                continue
            else:
                # All retries failed
                return None, False, True, f"Failed after {max_retries} attempts: {str(e)}"


def fetch_fire_data(map_key, bbox, start_date, end_date, use_cache=False):
    """
    Fetch fire data from NASA FIRMS API in 10-day chunks using parallel requests.
    Automatically processes in yearly batches to avoid API limitations.

    Args:
        map_key (str): NASA FIRMS MAP_KEY
        bbox (str): Bounding box as 'west,south,east,north'
        start_date (datetime): Start date
        end_date (datetime): End date
        use_cache (bool): Whether to use cached responses

    Returns:
        pd.DataFrame: Combined fire data from all chunks
    """
    # Process in yearly batches to avoid API rate limits and data loss
    # NASA FIRMS API seems to have undocumented limits on long date ranges
    chunks = list(generate_date_chunks(start_date, end_date, max_total_days=365))

    print(f"\nFetching fire data from {start_date.date()} to {end_date.date()}")
    print(f"Total chunks to process: {len(chunks)}")

    if use_cache:
        CACHE_DIR.mkdir(exist_ok=True)

    # Prepare arguments for parallel processing
    chunk_args = [(chunk_start, chunk_end, day_range, map_key, bbox, use_cache)
                  for chunk_start, chunk_end, day_range in chunks]

    all_data = []
    cache_hits = 0
    api_calls = 0
    errors = []

    # Process API requests SEQUENTIALLY to ensure 100% reliability
    # Parallel requests were causing 403 rate limit errors and data loss
    # Slower but guarantees complete data retrieval
    print("Processing requests sequentially for maximum reliability...")

    for chunk_arg in tqdm(chunk_args, desc="Fetching API data", unit="chunk"):
        df, from_cache, api_called, error = fetch_single_chunk(chunk_arg)

        if df is not None:
            all_data.append(df)

        if error:
            errors.append((chunk_arg[0], chunk_arg[1], error))

        if from_cache:
            cache_hits += 1
        if api_called:
            api_calls += 1

    if not all_data:
        print("\nWarning: No fire data found for the specified date range and area")
        return pd.DataFrame()

    # Combine all chunks
    combined_df = pd.concat(all_data, ignore_index=True)

    # Remove duplicates (overlapping dates in chunks)
    combined_df = combined_df.drop_duplicates()

    print(f"\nCache statistics: {cache_hits} hits, {api_calls} API calls")
    if errors:
        print(f"WARNING: {len(errors)} API call(s) failed!")
        print("Failed date ranges:")
        for start, end, err in errors[:10]:  # Show first 10 errors
            print(f"  {start.date()} to {end.date()}: {err}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")
    print(f"Total fire detections retrieved: {len(combined_df)}")

    return combined_df


def clip_fires_to_aoi(fire_df, aoi):
    """
    Clip fire points to exact AOI polygon boundaries.

    Args:
        fire_df (pd.DataFrame): Fire data with latitude/longitude columns
        aoi (gpd.GeoDataFrame): Area of interest polygon

    Returns:
        tuple: (fire_gdf_all, fire_gdf_clipped) - all fires in bbox and fires within AOI
    """
    if fire_df.empty:
        return gpd.GeoDataFrame(), gpd.GeoDataFrame()

    print("\nClipping fire points to AOI polygon...")

    # Convert fire data to GeoDataFrame
    geometry = [Point(lon, lat) for lon, lat in zip(fire_df['longitude'], fire_df['latitude'])]
    fire_gdf_all = gpd.GeoDataFrame(fire_df, geometry=geometry, crs="EPSG:4326")

    # Clip to AOI
    fire_gdf_clipped = gpd.clip(fire_gdf_all, aoi)

    print(f"Fire points within AOI: {len(fire_gdf_clipped)} (from {len(fire_gdf_all)} total)")

    return fire_gdf_all, fire_gdf_clipped


def generate_daily_frames(fire_gdf, aoi, start_date, end_date, output_dir, basemap_style=None, interval='daily', dpi=80, overall_start=None, overall_end=None, weight_by='count', fire_gdf_all=None, cmap=None):
    """
    Generate heatmap frames at specified interval (daily or monthly).

    Args:
        fire_gdf (gpd.GeoDataFrame): Clipped fire data (within AOI)
        aoi (gpd.GeoDataFrame): Area of interest
        start_date (datetime): Start date
        end_date (datetime): End date
        output_dir (Path): Directory to save frames
        basemap_style (str): Basemap tile provider (None, 'osm', 'satellite', 'terrain')
        interval (str): Grouping interval - 'daily' or 'monthly'
        dpi (int): Resolution for frame rendering (lower = faster, default 80)
        overall_start (datetime): Overall start date for title (optional)
        overall_end (datetime): Overall end date for title (optional)
        weight_by (str): Weighting method - 'count' (frequency) or 'frp' (radiative power intensity)
        fire_gdf_all (gpd.GeoDataFrame): All fire data in bounding box (optional, for showing context)
        cmap: Colormap to use for heatmap (default: FIRE_CMAP)

    Returns:
        list: Paths to generated frame files
    """
    # Use custom colormap if not specified
    if cmap is None:
        cmap = FIRE_CMAP
    # Use overall dates for title if provided
    if overall_start is None:
        overall_start = start_date
    if overall_end is None:
        overall_end = end_date
    output_dir.mkdir(exist_ok=True)
    frame_files = []

    # Determine if we're using a basemap
    use_basemap = basemap_style is not None and HAS_CONTEXTILY

    if basemap_style and not HAS_CONTEXTILY:
        print("\nWarning: contextily not installed. Install with: uv add contextily")
        print("Continuing without basemap...\n")

    # Reproject to Web Mercator for basemap compatibility
    if use_basemap:
        aoi_plot = aoi.to_crs(epsg=3857)
        if not fire_gdf.empty:
            fire_gdf_plot = fire_gdf.to_crs(epsg=3857)
        else:
            fire_gdf_plot = fire_gdf
        # Also reproject all fires if provided
        if fire_gdf_all is not None and not fire_gdf_all.empty:
            fire_gdf_all_plot = fire_gdf_all.to_crs(epsg=3857)
        else:
            fire_gdf_all_plot = fire_gdf_all if fire_gdf_all is not None else None
    else:
        aoi_plot = aoi
        fire_gdf_plot = fire_gdf
        fire_gdf_all_plot = fire_gdf_all

    # Get expanded bounds for viewport (buffer the AOI for rendering context)
    # Use the same 25km buffer to match the API fetch area
    if use_basemap:
        # Buffer in projected coordinates (meters)
        aoi_buffered_for_plot = aoi_plot.buffer(25000)  # 25km in meters
        bounds = aoi_buffered_for_plot.total_bounds
    else:
        # Buffer in WGS84 (approximate degrees - ~0.225 degrees ≈ 25km at equator)
        aoi_buffered_for_plot = aoi_plot.buffer(0.225)
        bounds = aoi_buffered_for_plot.total_bounds

    # Convert acq_date to datetime
    if not fire_gdf_plot.empty:
        fire_gdf_plot['acq_date'] = pd.to_datetime(fire_gdf_plot['acq_date'])
    if fire_gdf_all_plot is not None and not fire_gdf_all_plot.empty:
        fire_gdf_all_plot['acq_date'] = pd.to_datetime(fire_gdf_all_plot['acq_date'])

    # Generate date periods based on interval
    periods = []
    if interval == 'monthly':
        # Generate monthly periods
        current = start_date.replace(day=1)
        while current <= end_date:
            # Get last day of month
            if current.month == 12:
                next_month = current.replace(year=current.year + 1, month=1)
            else:
                next_month = current.replace(month=current.month + 1)
            month_end = next_month - timedelta(days=1)

            # Don't exceed end_date
            period_end = min(month_end, end_date)
            periods.append((current, period_end, current.strftime('%Y-%m')))

            current = next_month
    else:  # daily
        current_date = start_date
        while current_date <= end_date:
            periods.append((current_date, current_date, current_date.strftime('%Y-%m-%d')))
            current_date += timedelta(days=1)

    print(f"\nGenerating {len(periods)} {interval} frames...")

    # Pre-calculate monthly fire counts/totals for the bar chart
    monthly_counts = {}
    if interval == 'monthly' and not fire_gdf_plot.empty:
        for period_start, period_end, label in periods:
            month_fires = fire_gdf_plot[
                (fire_gdf_plot['acq_date'] >= period_start) &
                (fire_gdf_plot['acq_date'] <= period_end)
            ]
            if weight_by == 'frp':
                # Sum of FRP values (MW)
                monthly_counts[label] = month_fires['frp'].sum() if 'frp' in month_fires.columns else 0
            else:
                # Count of detections
                monthly_counts[label] = len(month_fires)
    elif interval == 'monthly':
        # All zeros if no fire data
        for period_start, period_end, label in periods:
            monthly_counts[label] = 0

    for period_start, period_end, label in tqdm(periods, desc="Rendering frames"):
        # Filter fires for this period (AOI fires)
        if not fire_gdf_plot.empty:
            if interval == 'monthly':
                # Get all fires within the month
                period_fires = fire_gdf_plot[
                    (fire_gdf_plot['acq_date'] >= period_start) &
                    (fire_gdf_plot['acq_date'] <= period_end)
                ]
            else:  # daily
                period_fires = fire_gdf_plot[fire_gdf_plot['acq_date'] == period_start]
        else:
            period_fires = gpd.GeoDataFrame()

        # Filter all fires for this period (including outside AOI)
        if fire_gdf_all_plot is not None and not fire_gdf_all_plot.empty:
            if interval == 'monthly':
                period_fires_all = fire_gdf_all_plot[
                    (fire_gdf_all_plot['acq_date'] >= period_start) &
                    (fire_gdf_all_plot['acq_date'] <= period_end)
                ]
            else:  # daily
                period_fires_all = fire_gdf_all_plot[fire_gdf_all_plot['acq_date'] == period_start]
        else:
            period_fires_all = None

        # Create figure with subplots (map on top, bar chart on bottom for monthly interval)
        if interval == 'monthly':
            # Calculate aspect ratio from AOI bounds to minimize side whitespace
            width_deg = bounds[2] - bounds[0]
            height_deg = bounds[3] - bounds[1]
            aspect_ratio = width_deg / height_deg

            # Set figure dimensions based on aspect ratio
            if aspect_ratio > 1.2:  # Wide area
                fig_width, fig_height = 14, 10
            elif aspect_ratio < 0.8:  # Tall area
                fig_width, fig_height = 10, 12
            else:  # Square-ish area
                fig_width, fig_height = 12, 11

            fig = plt.figure(figsize=(fig_width, fig_height), facecolor='#2b2b2b')
            # Reduced bar chart height ratio and added border padding
            # Symmetric margins to center the map perfectly
            gs = fig.add_gridspec(2, 1, height_ratios=[8, 1], hspace=0.05,
                                 left=0.05, right=0.95, top=0.92, bottom=0.08)
            ax_map = fig.add_subplot(gs[0], facecolor='#2b2b2b')
            ax_bar = fig.add_subplot(gs[1], facecolor='#2b2b2b')
            ax = ax_map  # Main plot is the map

            # Force map to be perfectly centered by setting equal aspect
            ax_map.set_aspect('equal', adjustable='box')
        else:
            fig, ax = plt.subplots(figsize=(12, 10))

        # CRITICAL: Set axis limits BEFORE adding basemap so it knows what area to fetch
        # Add 8% padding on each side to prevent boundary touching video edges
        x_range = bounds[2] - bounds[0]
        y_range = bounds[3] - bounds[1]
        padding_x = x_range * 0.08
        padding_y = y_range * 0.08
        ax.set_xlim(bounds[0] - padding_x, bounds[2] + padding_x)
        ax.set_ylim(bounds[1] - padding_y, bounds[3] + padding_y)

        # Add basemap if requested
        if use_basemap:
            # Add basemap tiles (axis limits already set above)
            try:
                if basemap_style == 'satellite':
                    cx.add_basemap(ax, source=cx.providers.Esri.WorldImagery, attribution_size=6)
                elif basemap_style == 'terrain':
                    cx.add_basemap(ax, source=cx.providers.Stamen.Terrain, attribution_size=6)
                else:  # 'osm' or default
                    cx.add_basemap(ax, source=cx.providers.OpenStreetMap.Mapnik, attribution_size=6)
            except Exception as e:
                print(f"\nWarning: Failed to add basemap: {e}")
                print("Continuing without basemap for this frame...")

        # Plot AOI boundary (lighter color for dark mode, high z-order to show on top)
        aoi_plot.boundary.plot(ax=ax, color='#e0e0e0', linewidth=2.5, zorder=10)

        # Plot fires - use all fires in bounding box with same color scheme
        # Use period_fires_all if available, otherwise fall back to period_fires
        fires_to_plot = period_fires_all if period_fires_all is not None and len(period_fires_all) > 0 else period_fires

        if len(fires_to_plot) >= 3:
            # Use KDE heatmap for sufficient points
            try:
                # Extract coordinates
                x = fires_to_plot.geometry.x.values
                y = fires_to_plot.geometry.y.values

                # Get weights if using FRP
                if weight_by == 'frp' and 'frp' in fires_to_plot.columns:
                    weights = fires_to_plot['frp'].values
                    # Normalize weights to avoid extreme values
                    weights = weights / weights.max() if weights.max() > 0 else weights
                else:
                    weights = None

                # Create KDE plot (tighter kernels for more accurate representation)
                sns.kdeplot(
                    x=x, y=y,
                    weights=weights,
                    cmap=cmap, fill=True, alpha=0.4,
                    levels=10, ax=ax, bw_adjust=0.15, zorder=2
                )

                # Add scatter points (size by FRP if applicable)
                if weight_by == 'frp' and 'frp' in fires_to_plot.columns:
                    # Scale point sizes by FRP (normalize for visibility)
                    frp_vals = fires_to_plot['frp'].values
                    sizes = 5 + (frp_vals / frp_vals.max() * 45) if frp_vals.max() > 0 else 15
                    ax.scatter(x, y, c='red', s=sizes, alpha=0.6, edgecolors='none', zorder=3)
                else:
                    ax.scatter(x, y, c='red', s=15, alpha=0.6, edgecolors='none', zorder=3)

            except Exception as e:
                # Fallback to scatter if KDE fails
                if weight_by == 'frp' and 'frp' in fires_to_plot.columns:
                    frp_vals = fires_to_plot['frp'].values
                    sizes = 10 + (frp_vals / frp_vals.max() * 90) if frp_vals.max() > 0 else 20
                    fires_to_plot.plot(ax=ax, color='red', markersize=sizes, alpha=0.6, zorder=3)
                else:
                    fires_to_plot.plot(ax=ax, color='red', markersize=20, alpha=0.6, zorder=3)

        elif len(fires_to_plot) > 0:
            # Scatter plot for sparse data
            if weight_by == 'frp' and 'frp' in fires_to_plot.columns:
                frp_vals = fires_to_plot['frp'].values
                sizes = 20 + (frp_vals / frp_vals.max() * 130) if frp_vals.max() > 0 else 50
                fires_to_plot.plot(ax=ax, color='red', markersize=sizes, alpha=0.6, zorder=3)
            else:
                fires_to_plot.plot(ax=ax, color='red', markersize=50, alpha=0.6, zorder=3)

        # Set axis labels and styling
        if use_basemap:
            # Remove axis labels for cleaner map view
            ax.set_xlabel('')
            ax.set_ylabel('')
            ax.set_xticks([])
            ax.set_yticks([])
        else:
            ax.set_xlabel('Longitude', fontsize=12, color='#e0e0e0')
            ax.set_ylabel('Latitude', fontsize=12, color='#e0e0e0')
            ax.tick_params(colors='#e0e0e0')


        # Add statistics text with modern styling (fixed layout to prevent jumping)
        if interval == 'monthly':
            month_name = period_start.strftime('%B')
            year = period_start.strftime('%Y')

            if weight_by == 'frp' and 'frp' in period_fires.columns:
                # Sum FRP values
                total_frp = period_fires['frp'].sum()
                value_text = f'{total_frp:,.0f} MW'
                unit_label = 'Fire Radiative Power'
            else:
                # Count detections
                value_text = f'{len(period_fires):,}'
                unit_label = 'Detections'

            stats_text = f'{month_name} {year}\n{value_text} {unit_label}'
        else:
            if weight_by == 'frp' and 'frp' in period_fires.columns:
                total_frp = period_fires['frp'].sum()
                stats_text = f'{total_frp:,.0f} MW'
            else:
                stats_text = f'{len(period_fires):,} Detections'

        # Styled info box (dark mode) - positioned further inside with clear whitespace
        ax.text(0.05, 0.95, stats_text, transform=ax.transAxes,
                fontsize=12, verticalalignment='top', fontweight='600',
                color='#e0e0e0', family='monospace',
                bbox=dict(boxstyle='round,pad=0.6', facecolor='#3d3d3d',
                         edgecolor='#e74c3c', linewidth=2.5, alpha=0.95))

        # Add monthly bar chart for monthly interval
        if interval == 'monthly':
            # CRITICAL: Perfect alignment - match bar chart to map's plot area
            fig.canvas.draw()  # Force render to get actual positions

            # Get the actual plot area of the map (excluding labels)
            map_bbox = ax_map.get_window_extent().transformed(fig.transFigure.inverted())

            # Set bar chart to match map's horizontal extent exactly
            bar_bbox = ax_bar.get_position()
            ax_bar.set_position([map_bbox.x0, bar_bbox.y0, map_bbox.width, bar_bbox.height])

            # Create bar chart of monthly detections
            months = list(monthly_counts.keys())
            counts = list(monthly_counts.values())

            # Beautiful gradient colors - current month highlighted
            current_idx = months.index(label)
            colors = ['#e74c3c' if i == current_idx else '#95a5a6' for i in range(len(months))]

            # Create bars with modern styling
            bars = ax_bar.bar(range(len(months)), counts, color=colors,
                            edgecolor='#34495e', linewidth=1.2, alpha=0.85)

            # Highlight current bar with glow effect
            bars[current_idx].set_edgecolor('#c0392b')
            bars[current_idx].set_linewidth(2.5)
            bars[current_idx].set_alpha(1.0)

            # Customize bar chart with dark mode styling
            ylabel = 'FRP (MW)' if weight_by == 'frp' else 'Detections'
            ax_bar.set_ylabel(ylabel, fontsize=11, fontweight='semibold', color='#e0e0e0')
            ax_bar.set_xlim(-0.5, len(months) - 0.5)
            ax_bar.grid(axis='y', alpha=0.2, linestyle='--', color='#666666', linewidth=0.8)
            ax_bar.set_facecolor('#2b2b2b')
            ax_bar.spines['top'].set_visible(False)
            ax_bar.spines['right'].set_visible(False)
            ax_bar.spines['left'].set_color('#666666')
            ax_bar.spines['bottom'].set_color('#666666')
            ax_bar.tick_params(colors='#e0e0e0')

            # Format date labels (Aug '23 format)
            def format_month_label(month_str):
                """Convert YYYY-MM to Mmm 'YY format"""
                dt = datetime.strptime(month_str, '%Y-%m')
                return dt.strftime("%b '%y")

            # Set x-axis labels (show every Nth label to avoid crowding)
            if len(months) <= 12:
                step = 1
            elif len(months) <= 24:
                step = 2
            elif len(months) <= 36:
                step = 3
            else:
                step = 6

            tick_positions = range(0, len(months), step)
            tick_labels = [format_month_label(months[i]) for i in tick_positions]
            ax_bar.set_xticks(tick_positions)
            ax_bar.set_xticklabels(tick_labels, rotation=45, ha='right', fontsize=9,
                                  color='#e0e0e0', fontweight='medium')

            # Add subtle background highlight for current month
            ax_bar.axvspan(current_idx - 0.5, current_idx + 0.5,
                          alpha=0.15, color='#e74c3c', zorder=0)

            # Match bar chart width to map by adjusting margins
            ax_bar.margins(x=0)

        # Save frame
        if interval == 'monthly':
            frame_file = output_dir / f"frame_{label}.png"
        else:
            frame_file = output_dir / f"frame_{period_start.strftime('%Y%m%d')}.png"

        # Save with minimal whitespace - bbox_inches='tight' crops to content
        if interval == 'monthly':
            # Use bbox_inches='tight' to crop whitespace around map
            plt.savefig(frame_file, dpi=dpi, bbox_inches='tight', pad_inches=0.15)
        else:
            plt.tight_layout(pad=0.3)
            plt.savefig(frame_file, dpi=dpi, bbox_inches='tight', pad_inches=0.1)
        plt.close(fig)

        # Ensure even dimensions for H.264 codec (required by libx264)
        img = Image.open(frame_file)
        width, height = img.size

        # Pad to even dimensions if needed
        new_width = width if width % 2 == 0 else width + 1
        new_height = height if height % 2 == 0 else height + 1

        if new_width != width or new_height != height:
            new_img = Image.new('RGB', (new_width, new_height), (255, 255, 255))
            new_img.paste(img, (0, 0))
            new_img.save(frame_file)
        elif img.mode != 'RGB':
            # Also ensure RGB mode
            img.convert('RGB').save(frame_file)

        frame_files.append(frame_file)

    return frame_files


def compile_video(frame_files, output_path, fps=3, hold_last_frame=3):
    """
    Compile frames into MP4 video.

    Args:
        frame_files (list): List of frame file paths
        output_path (str): Output video file path
        fps (int): Frames per second
        hold_last_frame (int): Number of extra frames to hold the last frame (default: 3)
    """
    print(f"\nCompiling video: {output_path}")
    print(f"Total frames: {len(frame_files)}, FPS: {fps}")

    # Read frames and write video
    frames = []
    for frame_file in tqdm(frame_files, desc="Loading frames"):
        frames.append(iio.imread(frame_file))

    # Hold the last frame for a few extra frames to avoid abrupt ending
    if frames and hold_last_frame > 0:
        last_frame = frames[-1]
        for _ in range(hold_last_frame):
            frames.append(last_frame)

    # Write video with H.264 codec
    iio.imwrite(
        output_path,
        frames,
        fps=fps,
        codec='libx264',
        quality=8,
        macro_block_size=1
    )

    print(f"Video saved: {output_path}")

    # Calculate video duration (including held frames)
    total_frames = len(frame_files) + hold_last_frame
    duration = total_frames / fps
    print(f"Video duration: {duration:.1f} seconds ({total_frames} frames)")


def cleanup_frames(frame_dir):
    """
    Remove temporary frame files.

    Args:
        frame_dir (Path): Directory containing frames
    """
    print("\nCleaning up temporary frames...")

    for frame_file in frame_dir.glob("*.png"):
        frame_file.unlink()

    frame_dir.rmdir()


def validate_dates(start_str, end_str):
    """
    Validate and parse date strings.

    Args:
        start_str (str): Start date string (YYYY-MM-DD)
        end_str (str): End date string (YYYY-MM-DD)

    Returns:
        tuple: (start_date, end_date) as datetime objects

    Raises:
        SystemExit: If dates are invalid
    """
    try:
        start_date = datetime.strptime(start_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_str, "%Y-%m-%d")
    except ValueError as e:
        print(f"ERROR: Invalid date format. Use YYYY-MM-DD", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        sys.exit(1)

    if start_date > end_date:
        print("ERROR: Start date must be before end date", file=sys.stderr)
        sys.exit(1)

    # Warn about MODIS_SP processing delay
    recent_threshold = datetime.now() - timedelta(days=60)
    if end_date > recent_threshold:
        print("\nWarning: MODIS_SP data has a 2-3 month processing delay.")
        print(f"Recent dates (after ~{recent_threshold.date()}) may have no data.")

    return start_date, end_date


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Generate fire activity timelapse videos from NASA FIRMS data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s inputs/example.geojson 2023-08-01 2023-08-31
  %(prog)s inputs/area.geojson 2023-01-01 2023-12-31 -o outputs/videos/yearly_fires.mp4 --fps 5
  %(prog)s inputs/area.geojson 2023-06-01 2023-06-30 --cache --basemap satellite
  %(prog)s inputs/area.geojson 2023-08-01 2023-08-31 --basemap osm
        """
    )

    parser.add_argument('geojson', help='Path to GeoJSON file defining the AOI')
    parser.add_argument('start_date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('end_date', help='End date (YYYY-MM-DD)')
    parser.add_argument('-o', '--output', default=None,
                        help='Output video filename (default: outputs/videos/OUTPUT_{input_filename}.mp4)')
    parser.add_argument('--fps', type=int, default=3,
                        help='Frames per second (default: 3, slower for better viewing)')
    parser.add_argument('--cache', action='store_true',
                        help='Cache API responses for development')
    parser.add_argument('--keep-frames', action='store_true',
                        help='Keep temporary frame files after video generation')
    parser.add_argument('--basemap', choices=['osm', 'satellite', 'terrain', 'none'], default='satellite',
                        help='Basemap overlay (default: satellite). '
                             'Options: osm, satellite, terrain, none. Requires contextily: uv add contextily')
    parser.add_argument('--interval', choices=['daily', 'monthly'], default='monthly',
                        help='Time interval for frame grouping (default: monthly). '
                             'Use "daily" for day-by-day viewing.')
    parser.add_argument('--dpi', type=int, default=80,
                        help='Frame resolution in DPI (default: 80). Higher = better quality but slower. Try 60 for speed, 100+ for quality.')

    args = parser.parse_args()

    # Generate default output filename based on input if not specified
    if args.output is None:
        input_filename = Path(args.geojson).stem  # Get filename without extension
        args.output = f"outputs/videos/OUTPUT_{input_filename}.mp4"

    # Check basemap availability UPFRONT (before processing)
    if args.basemap and args.basemap != 'none' and not HAS_CONTEXTILY:
        print("\n" + "="*60)
        print("ERROR: Basemap requested but contextily is not installed!")
        print("="*60)
        print("\nTo install contextily, run:")
        print("  uv add contextily")
        print("\nOr run without basemap:")
        print(f"  ... --basemap none")
        print("="*60)
        sys.exit(1)

    # Convert 'none' to None for internal use
    if args.basemap == 'none':
        args.basemap = None

    # Validate inputs
    start_date, end_date = validate_dates(args.start_date, args.end_date)
    map_key = get_map_key()

    # Load AOI
    print(f"Loading AOI from: {args.geojson}")
    t0 = time.time()
    aoi = load_aoi(args.geojson)
    bbox = get_bounding_box(aoi, buffer_km=25)
    print(f"Bounding box (with 25km buffer): {bbox}")

    # Fetch fire data
    print(f"\n[1/4] Fetching fire data...")
    t1 = time.time()
    fire_df = fetch_fire_data(map_key, bbox, start_date, end_date, use_cache=args.cache)
    print(f"✓ Data fetch completed in {time.time() - t1:.1f}s")

    # Clip to AOI
    print(f"\n[2/4] Processing spatial data...")
    t2 = time.time()
    fire_gdf_all, fire_gdf = clip_fires_to_aoi(fire_df, aoi)
    print(f"✓ Spatial processing completed in {time.time() - t2:.1f}s")

    # Generate frames with custom colormap
    print(f"\n[3/4] Rendering frames (DPI={args.dpi})...")
    t3 = time.time()
    frames_dir = Path("outputs/frames_frequency")
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_files = generate_daily_frames(fire_gdf, aoi, start_date, end_date, frames_dir,
                                       basemap_style=args.basemap, interval=args.interval,
                                       dpi=args.dpi, overall_start=start_date, overall_end=end_date,
                                       weight_by='count', fire_gdf_all=fire_gdf_all, cmap='gnuplot2')
    print(f"✓ Frame rendering completed in {time.time() - t3:.1f}s")

    # Generate output filename with format: OUTPUT_{StartDate}_{EndDate}_{AOI_name}.mp4
    input_filename = Path(args.geojson).stem
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    output_path = Path(args.output)
    output_dir = output_path.parent
    output_video = output_dir / f"OUTPUT_{start_str}_{end_str}_{input_filename}.mp4"

    print(f"\n[4/4] Compiling video...")
    t4 = time.time()
    output_dir.mkdir(parents=True, exist_ok=True)
    compile_video(frame_files, str(output_video), fps=args.fps)
    print(f"✓ Video compilation completed in {time.time() - t4:.1f}s")

    # Cleanup
    if not args.keep_frames:
        cleanup_frames(frames_dir)
    else:
        print(f"\nFrames saved in: {frames_dir}")

    total_time = time.time() - t0
    print(f"\n{'='*60}")
    print(f"✓ Total processing time: {total_time:.1f}s ({total_time/60:.1f} minutes)")
    print(f"{'='*60}")
    print(f"\nVideo saved to: {output_video}")
    print("Done!")


if __name__ == "__main__":
    main()
