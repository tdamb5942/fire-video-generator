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
python fire_timelapse.py <geojson_file> <start_date> <end_date>
```

### Testing & Development
```bash
# Development mode with caching (faster iteration)
python fire_timelapse.py inputs/example.geojson 2023-08-01 2023-08-31 --cache

# Keep frames for inspection
python fire_timelapse.py inputs/example.geojson 2023-08-01 2023-08-31 --keep-frames

# Adjust rendering speed/quality
python fire_timelapse.py inputs/example.geojson 2023-08-01 2023-08-31 --dpi 60  # faster
python fire_timelapse.py inputs/example.geojson 2023-08-01 2023-08-31 --dpi 100 # higher quality
```

### Code Quality
```bash
# Format code
black fire_timelapse.py

# Lint
ruff fire_timelapse.py
```

## Architecture Overview

### Data Processing Pipeline

The script follows a sequential 6-stage pipeline:

1. **API Data Fetching** (`fetch_fire_data`)
   - Chunks date ranges into 10-day periods (NASA FIRMS API limit)
   - Processes sequentially to avoid 403 rate limit errors
   - Uses global rate limiting with 0.3s delays between calls
   - Automatically batches into yearly segments to prevent data loss

2. **Spatial Clipping** (`clip_fires_to_aoi`)
   - API returns rectangular bounding box data
   - Uses `gpd.clip()` to filter to exact polygon boundaries
   - Critical step: ensures fires are truly within AOI, not just bbox

3. **Frequency Frame Generation** (`generate_daily_frames` with `weight_by='count'`)
   - Creates heatmaps showing WHERE fires happen most often
   - Uses KDE for ≥3 points, scatter plots for sparse data
   - Metric: detection count

4. **Frequency Video Compilation** (`compile_video`)
   - Combines frequency frames into MP4
   - H.264 codec with 3fps default

5. **Intensity Frame Generation** (`generate_daily_frames` with `weight_by='frp'`)
   - Creates heatmaps showing WHERE fires burn hottest
   - Weights KDE by Fire Radiative Power (FRP)
   - Metric: total MW

6. **Intensity Video Compilation** (`compile_video`)
   - Combines intensity frames into second MP4

### Key Architectural Patterns

**Sequential API Processing**: Originally used parallel requests, but switched to sequential processing with explicit delays to ensure 100% data reliability. See lines 302-319 in fire_timelapse.py.

**Dual Output System**: Every run produces TWO videos (frequency + intensity) to provide complementary insights. This is intentional and should be maintained.

**Coordinate System Handling**:
- Input/API: WGS84 (EPSG:4326)
- Basemap rendering: Web Mercator (EPSG:3857)
- Conversion happens in `generate_daily_frames` at line 408-416

**Frame Dimension Requirements**: H.264 codec requires even dimensions. PIL padding applied at lines 741-754 to ensure compliance.

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
├── inputs/              # GeoJSON AOI files
├── outputs/             # All outputs (gitignored)
│   ├── videos/          # Final MP4 files
│   ├── frames_frequency/   # Temporary frequency frames
│   ├── frames_intensity/   # Temporary intensity frames
│   └── cache/           # API response cache (if --cache used)
├── fire_timelapse.py    # Main script (999 lines)
└── pyproject.toml       # uv configuration
```

## Important Constraints

### NASA FIRMS API
- **10-day maximum** per request (enforced at line 151-183)
- **2-3 month data delay** for MODIS_SP (science-grade data)
- **Rate limiting**: 5000 transactions per 10 minutes
- Sequential processing required to avoid 403 errors

### Data Processing
- **KDE requires ≥3 points**: Automatically falls back to scatter plots (line 534-582)
- **Coordinate system**: Input must be WGS84, auto-converts if needed (line 122-128)
- **Basemap dependency**: contextily must be installed for basemap features, checked at startup (line 894-904)

### Video Output
- **Naming format**: `OUTPUT_{FREQUENCY|INTENSITY}_{start_date}_{end_date}_{aoi_name}.mp4`
- **Default FPS**: 3 (configurable via `--fps`)
- **Default interval**: monthly (use `--interval daily` for day-by-day)
- **Last frame hold**: 3 extra frames to prevent abrupt endings (line 769)

## Code Organization

### Main Entry Point
`main()` function (lines 853-994) orchestrates the entire pipeline with progress reporting.

### Critical Functions
- `get_map_key()`: Multi-source API key retrieval with .env support
- `fetch_single_chunk()`: Handles individual API requests with retry logic
- `fetch_fire_data()`: Orchestrates sequential API requests with yearly batching
- `generate_daily_frames()`: Core visualization engine supporting both frequency and intensity modes
- `compile_video()`: FFmpeg wrapper with H.264 encoding

### Visualization Details
The `generate_daily_frames` function (lines 372-758) handles:
- Monthly vs daily interval switching
- Frequency vs intensity weighting via `weight_by` parameter
- Dark mode styling (#2b2b2b background, #e0e0e0 text)
- Basemap integration with Web Mercator projection
- Timeline bar charts for monthly intervals
- Automatic layout adjustment based on AOI aspect ratio

## Development Notes

### Performance Tuning
- Use `--cache` during development to avoid re-fetching API data
- Lower `--dpi` (e.g., 60) for faster preview renders
- Increase `--dpi` (e.g., 100-120) for production quality
- Default DPI of 80 balances speed and quality

### Common Modifications
When modifying visualization:
- Frame styling starts at line 499 (figure setup)
- Heatmap generation at line 534-582
- Info box styling at line 649-653
- Bar chart at line 656-723

When modifying API handling:
- Rate limiting at line 222-228
- Retry logic at line 218-265
- Chunking algorithm at line 151-183

### Testing Considerations
- Use `inputs/example.geojson` for quick tests
- MODIS_SP has 2-3 month delay - avoid recent dates
- Small AOI + 1 month = ~30 seconds total processing
- Large AOI + 1 year = several minutes (mostly API fetching)