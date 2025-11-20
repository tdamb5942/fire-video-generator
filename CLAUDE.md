# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NASA FIRMS Fire Timelapse Generator - A Python tool that creates MP4 timelapse videos showing fire activity heatmaps using NASA FIRMS MODIS_SP data within GeoJSON-defined areas of interest.

## Development Commands

### Environment Setup
```bash
# Install dependencies (uses uv for package management)
uv sync

# Run the main script
python src/fire_timelapse.py <geojson_file> <start_date> <end_date>
```

### Testing & Development
```bash
# Development mode with caching (faster iteration)
python src/fire_timelapse.py inputs/example.geojson 2023-08-01 2023-08-31 --cache

# Keep frames for inspection
python src/fire_timelapse.py inputs/example.geojson 2023-08-01 2023-08-31 --keep-frames

# Adjust rendering speed/quality
python src/fire_timelapse.py inputs/example.geojson 2023-08-01 2023-08-31 --dpi 60  # faster
python src/fire_timelapse.py inputs/example.geojson 2023-08-01 2023-08-31 --dpi 100 # higher quality
```

### Code Quality
```bash
# Format code
black src/fire_timelapse.py

# Lint
ruff src/fire_timelapse.py
```

## Architecture Overview

### Data Processing Pipeline

The script follows a sequential 4-stage pipeline:

1. **API Data Fetching** (`fetch_fire_data`)
   - Chunks date ranges into 10-day periods (NASA FIRMS API limit)
   - Processes sequentially to avoid 403 rate limit errors
   - Uses global rate limiting with 0.3s delays between calls
   - Automatically batches into yearly segments to prevent data loss
   - Buffers AOI by 25km to fetch surrounding fire context

2. **Spatial Clipping** (`clip_fires_to_aoi`)
   - API returns rectangular bounding box data (with 25km buffer)
   - Uses `gpd.clip()` to filter to exact polygon boundaries
   - Returns both: all fires in buffer area + fires within AOI
   - Critical step: ensures fires are truly within AOI, not just bbox

3. **Frame Generation** (`generate_daily_frames`)
   - Creates heatmaps showing fire activity
   - Uses ALL fires in buffered area for visualization (provides context)
   - Uses KDE for ≥3 points, scatter plots for sparse data
   - Applies gnuplot2 colormap for smooth gradient visualization
   - Includes satellite basemap overlay (default)
   - Per-frame normalization: colors show relative density within that period

4. **Video Compilation** (`compile_video`)
   - Combines frames into MP4
   - H.264 codec with 3fps default
   - Outputs single video: `OUTPUT_{start}_{end}_{aoi_name}.mp4`

### Key Architectural Patterns

**Sequential API Processing**: Originally used parallel requests, but switched to sequential processing with explicit delays to ensure 100% data reliability. See lines 302-319 in src/fire_timelapse.py.

**25km Buffer System**: Fetches fire data for 25km beyond AOI boundaries to show context. Users can see both fires within and around their area of interest. The AOI boundary is clearly marked with a white line.

**Single Output System**: Generates one video showing fire detection frequency. No longer produces separate intensity videos.

**Coordinate System Handling**:
- Input/API: WGS84 (EPSG:4326)
- Basemap rendering: Web Mercator (EPSG:3857)
- Conversion happens in `generate_daily_frames` at appropriate points

**Frame Dimension Requirements**: H.264 codec requires even dimensions. PIL padding applied to ensure compliance.

## Configuration & Environment

### API Authentication
The script checks for `FIRMS_MAP_KEY` in this order:
1. `.env` file (recommended): `FIRMS_MAP_KEY=your_key_here`
2. Environment variable: `export FIRMS_MAP_KEY='your_key_here'`
3. `config.json`: `{"MAP_KEY": "your_key_here"}`

Get key at: https://firms.modaps.eosdis.nasa.gov/api/map_key/

### Directory Structure
```
fire-video-generator/
├── src/
│   └── fire_timelapse.py    # Main script (1000+ lines)
├── inputs/                  # GeoJSON AOI files
├── outputs/                 # Generated outputs (gitignored)
│   ├── videos/              # Final MP4 files
│   └── frames_frequency/    # Temporary frames (if --keep-frames)
├── .cache/                  # API response cache (gitignored)
├── pyproject.toml           # uv configuration
├── CLAUDE.md                # This file
└── README.md                # User documentation
```

## Important Constraints

### NASA FIRMS API
- **10-day maximum** per request (enforced in chunking logic)
- **2-3 month data delay** for MODIS_SP (science-grade data)
- **Rate limiting**: 5000 transactions per 10 minutes
- Sequential processing required to avoid 403 errors

### Data Processing
- **KDE requires ≥3 points**: Automatically falls back to scatter plots
- **Coordinate system**: Input must be WGS84, auto-converts if needed
- **Basemap dependency**: contextily must be installed for basemap features, checked at startup
- **25km buffer**: Applied to AOI for data fetch, viewport shows expanded area

### Video Output
- **Naming format**: `OUTPUT_{start_date}_{end_date}_{aoi_name}.mp4`
- **Default FPS**: 3 (configurable via `--fps`)
- **Default interval**: monthly (use `--interval daily` for day-by-day)
- **Default DPI**: 80 (use `--dpi 60` for speed, `--dpi 100+` for quality)
- **Basemap**: satellite by default (configurable: osm, terrain, none)
- **Colormap**: gnuplot2 (dark purple → blue → cyan → green → yellow → red → white)

## Code Organization

### Main Entry Point
`main()` function orchestrates the entire pipeline with progress reporting.

### Critical Functions
- `get_map_key()`: Multi-source API key retrieval with .env support
- `get_bounding_box()`: Extracts bounding box with 25km buffer using Azimuthal Equidistant projection
- `fetch_single_chunk()`: Handles individual API requests with retry logic
- `fetch_fire_data()`: Orchestrates sequential API requests with yearly batching
- `clip_fires_to_aoi()`: Returns both buffered and clipped fire datasets
- `generate_daily_frames()`: Core visualization engine with basemap integration
- `compile_video()`: FFmpeg wrapper with H.264 encoding

### Visualization Details
The `generate_daily_frames` function handles:
- Monthly vs daily interval switching
- Dark mode styling (#2b2b2b background, #e0e0e0 text)
- Basemap integration with Web Mercator projection
- gnuplot2 colormap application
- Timeline bar charts for monthly intervals
- Automatic layout adjustment based on AOI aspect ratio
- Per-frame color normalization (relative density within that time period)
- 25km buffer viewport rendering

## Development Notes

### Performance Tuning
- Use `--cache` during development to avoid re-fetching API data
- Cache stored in `.cache/` directory (not in outputs/)
- Lower `--dpi` (e.g., 60) for faster preview renders
- Increase `--dpi` (e.g., 100-120) for production quality
- Default DPI of 80 balances speed and quality

### Common Modifications
When modifying visualization:
- Colormap application at line ~631 (KDE plot)
- Frame styling starts around line ~520 (figure setup)
- Heatmap generation at line ~570-640
- Info box styling around line ~660
- Bar chart around line ~670-730

When modifying API handling:
- Rate limiting logic around line ~222-228
- Retry logic at line ~218-265
- Chunking algorithm at line ~151-183
- 25km buffer calculation in `get_bounding_box()` at line ~137-164

### Testing Considerations
- Use `inputs/example.geojson` for quick tests
- MODIS_SP has 2-3 month delay - avoid recent dates
- Small AOI + 1 month = ~30 seconds total processing
- Large AOI + 1 year = several minutes (mostly API fetching)

### Recent Changes (2024)
- Moved from root to `src/fire_timelapse.py`
- Changed cache location from `outputs/cache/` to `.cache/`
- Removed dual-output system (no longer generates intensity videos)
- Added 25km buffer for context visualization
- Implemented gnuplot2 colormap
- Removed title box from frames (cleaner visualization)
- Single video output with simplified naming

## Key Differences from Original Design

1. **No Title Box**: Removed decorative title to maximize visualization space
2. **Single Video**: Only generates frequency-based video, not intensity
3. **25km Buffer**: Shows fire context beyond AOI boundaries
4. **Basemap Default**: Satellite imagery enabled by default
5. **Sequential API**: Reliability over speed for data fetching
6. **Cache Location**: Moved to `.cache/` as it's intermediate data, not output

IMPORTANT: this context may or may not be relevant to your tasks. You should not respond to this context unless it is highly relevant to your task.
