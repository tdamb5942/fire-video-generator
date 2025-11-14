# NASA FIRMS Fire Timelapse Generator - Project Brief

## Executive Summary
Create a Python script that generates MP4 timelapse videos showing fire activity heatmaps within a GeoJSON-defined Area of Interest (AOI) using NASA FIRMS data.

## Project Requirements

### Core Functionality
1. Accept a GeoJSON file defining the geographic AOI
2. Accept start and end date parameters
3. Fetch fire detection data from NASA FIRMS API
4. Generate daily heatmap visualizations
5. Compile frames into an MP4 video

### Data Source Specification
- **Use MODIS_SP exclusively** (MODIS Standard Processing)
- Resolution: 1km
- Quality: Science-grade processed data
- Typical delay: 2-3 months from acquisition
- Available from: November 2000 to present

## NASA FIRMS API Specifications

### API Endpoint
```
https://firms.modaps.eosdis.nasa.gov/api/area/csv/[MAP_KEY]/[SOURCE]/[AREA_COORDINATES]/[DAY_RANGE]/[DATE]
```

### Required Parameters
- `MAP_KEY`: 32-character authentication key (free registration required)
- `SOURCE`: Use `MODIS_SP` 
- `AREA_COORDINATES`: Bounding box as `west,south,east,north` (e.g., `-122.5,37.5,-122.0,38.0`)
- `DAY_RANGE`: Number of days to query (1-10 maximum per request)
- `DATE`: Starting date in `YYYY-MM-DD` format

### API Constraints
- **Maximum 10 days per request** - Critical constraint for chunking logic
- **Rate limit**: 5000 transactions per 10-minute window
- **Response format**: CSV with fire detection points
- **No data response**: Returns text "No data" when no fires detected

### API Registration
- Registration URL: `https://firms.modaps.eosdis.nasa.gov/api/map_key/`
- Process: Email registration → Receive MAP_KEY → Use in all API calls

## Technical Architecture

### Required Python Libraries
```
geopandas    # GeoJSON handling and spatial operations
pandas       # CSV data manipulation
matplotlib   # Visualization framework
seaborn      # Statistical visualization (KDE heatmaps)
requests     # HTTP API calls
imageio      # Video generation (preferred over moviepy for memory efficiency)
shapely      # Geometry operations (dependency of geopandas)
tqdm         # Progress bars for user feedback
```

### Implementation Strategy

#### 1. Data Acquisition Logic
- **Chunk requests into 10-day periods** (API maximum)
- For a 30-day period: Make 3 API calls instead of 30
- For a 365-day period: Make 37 API calls instead of 365
- Implement 0.5-second delay between API calls (rate limit respect)

#### 2. Spatial Processing Workflow
```
1. Load GeoJSON → Extract bounding box for API
2. Fetch data for bounding box (rectangular area)
3. Convert CSV to GeoDataFrame with point geometries
4. Clip points to exact AOI polygon (critical step)
5. Process by date for frame generation
```

#### 3. Visualization Approach
- Use kernel density estimation (KDE) for smooth heatmaps
- Fallback to scatter plot when <3 points (KDE requirement)
- Each frame should show:
  - AOI boundary (black outline)
  - Fire activity (heatmap or points)
  - Date label
  - Optional: Statistics overlay (daily count, cumulative count)

#### 4. Video Generation
- Save frames as temporary PNG files
- Compile using imageio at 3-5 fps
- Use H.264 codec for MP4 output
- Clean up temporary files after compilation

## Data Field Specifications

### Key MODIS_SP Fields
- `latitude`, `longitude`: Fire detection coordinates
- `acq_date`: Acquisition date (YYYY-MM-DD format)
- `acq_time`: Acquisition time (HHMM format)
- `brightness`: Brightness temperature (Kelvin)
- `confidence`: Detection confidence (0-100%)
- `frp`: Fire Radiative Power (megawatts) - use for intensity weighting if desired
- `daynight`: D (day) or N (night)

## Implementation Requirements

### Command-Line Interface
Script should accept:
- Positional argument 1: Path to GeoJSON file
- Positional argument 2: Start date (YYYY-MM-DD)
- Positional argument 3: End date (YYYY-MM-DD)
- Optional: `-o` or `--output` for output filename (default: `fire_timelapse.mp4`)
- Optional: `--fps` for frames per second (default: 3)
- Optional: `--cache` to cache API responses during development

### Error Handling
- Validate GeoJSON file exists and is readable
- Validate date format and logical order (start < end)
- Handle API failures gracefully (network errors, 403 forbidden)
- Handle "No data" responses for periods without fires
- Check for MAP_KEY configuration before running

### Performance Optimizations
1. **API Response Caching** (development feature)
   - Hash API URLs to create cache filenames
   - Store successful responses as CSV files
   - Check cache before making API calls
   - Add flag to disable for production runs

2. **Memory Management**
   - Process data in chunks if date range >1 year
   - Close matplotlib figures after saving frames
   - Use generator patterns where applicable

3. **User Feedback**
   - Progress bars for long-running operations
   - Clear status messages for each processing step
   - Summary statistics at completion

## Example Workflow

### For a 30-day period in California:
1. Load California GeoJSON (polygon)
2. Extract bounding box: `-124.48,-114.13,32.53,42.01`
3. Make 3 API calls (days 1-10, 11-20, 21-30)
4. Combine ~500-2000 fire points (typical)
5. Clip to exact California boundary
6. Generate 30 frames (one per day)
7. Compile into ~10-second video at 3 fps

## Quality Assurance Checks
- Verify fire points are within AOI after clipping
- Handle edge cases: No fires, single fire, sparse data
- Ensure date continuity in output (include days with no fires)
- Validate coordinate systems (ensure WGS84/EPSG:4326)

## Deliverables
1. Single Python script (`fire_timelapse.py`)
2. Requirements file (`requirements.txt`)
3. Example GeoJSON file for testing
4. README with usage instructions

## Success Criteria
- Script successfully fetches MODIS_SP data for any valid date range
- Correctly clips fire data to exact AOI boundaries
- Generates smooth video with clear visualization
- Handles API rate limits without failing
- Provides informative user feedback throughout process

## Additional Considerations
- The script should be self-contained (single file)
- Use clear variable names and include docstrings
- Follow PEP 8 style guidelines
- Include helpful error messages that guide users to solutions

## Testing Scenarios
1. Small AOI, short period (1 week)
2. Large AOI, medium period (1 month)  
3. Small AOI, long period (1 year)
4. Period with no fires (should handle gracefully)
5. Invalid API key (should provide clear error)

---

## Important Notes for Implementation
- MODIS_SP data has 2-3 month processing delay, so recent dates will have no data
- Each 10-day chunk may return 0-10,000+ points depending on AOI size and fire activity
- The clipping step is critical - API returns rectangular area, must clip to exact polygon
- KDE visualization requires minimum 3 points; implement fallback for sparse data