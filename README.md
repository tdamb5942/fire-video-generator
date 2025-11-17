# NASA FIRMS Fire Timelapse Generator

Generate MP4 timelapse videos showing fire activity heatmaps within a GeoJSON-defined Area of Interest (AOI) using NASA FIRMS MODIS_SP data.

## Features

- **Dual Output**: Generates TWO videos per run
  - **Frequency video**: Shows where fires occur most often (detection count)
  - **Intensity video**: Shows where fires burn hottest (Fire Radiative Power in MW)
- Fetches fire detection data from NASA FIRMS API (MODIS Standard Processing)
- Parallel API requests for 10-20x speed improvement
- Handles API's 10-day request limit with automatic chunking
- Clips fire points to exact polygon boundaries (not just bounding box)
- Generates smooth KDE heatmaps weighted by frequency or intensity
- Compiles daily/monthly frames into MP4 videos
- Includes progress bars and detailed user feedback
- Optional caching for development/testing
- Handles edge cases: no fires, sparse data, API failures

## Requirements

This project uses `uv` for dependency management. The required packages are:

- geopandas >= 0.14.0
- pandas >= 2.0.0
- matplotlib >= 3.7.0
- seaborn >= 0.12.0
- requests >= 2.31.0
- imageio >= 2.31.0
- imageio-ffmpeg >= 0.4.9
- shapely >= 2.0.0
- tqdm >= 4.66.0
- contextily >= 1.3.0 (optional, for basemap overlays)

## Project Structure

```
fire-video-generator/
├── inputs/              # Place your GeoJSON files here
│   └── example.geojson  # Example test area
├── outputs/             # Generated outputs (gitignored)
│   ├── videos/          # MP4 timelapse videos
│   ├── frames/          # Temporary PNG frames
│   └── cache/           # API response cache (when --cache is used)
├── fire_timelapse.py    # Main script
└── README.md
```

## Installation

1. Clone this repository
2. Install dependencies using uv:
   ```bash
   uv sync
   ```
3. **(Optional)** For basemap overlays, install contextily:
   ```bash
   uv add contextily
   ```

## NASA FIRMS API Key

You need a free NASA FIRMS MAP_KEY to use this tool.

### Get Your MAP_KEY

1. Register at: https://firms.modaps.eosdis.nasa.gov/api/map_key/
2. You'll receive a 32-character key via email

### Configure MAP_KEY

Choose one of these methods:

**Option 1: Environment Variable (Recommended)**
```bash
export FIRMS_MAP_KEY='your_32_character_key_here'
```

**Option 2: Config File**
Create a `config.json` file in the project directory:
```json
{
  "MAP_KEY": "your_32_character_key_here"
}
```

## Usage

### Basic Usage

```bash
python fire_timelapse.py <geojson_file> <start_date> <end_date>
```

### Examples

**Generate a one-month timelapse:**
```bash
python fire_timelapse.py inputs/example.geojson 2023-08-01 2023-08-31
```

**Custom output filename and frame rate:**
```bash
python fire_timelapse.py inputs/your_area.geojson 2023-01-01 2023-12-31 -o outputs/videos/yearly_fires.mp4 --fps 5
```

**Development mode with caching:**
```bash
python fire_timelapse.py inputs/your_area.geojson 2023-06-01 2023-06-30 --cache
```

**Keep frame files for inspection:**
```bash
python fire_timelapse.py inputs/your_area.geojson 2023-08-01 2023-08-15 --keep-frames
```

**With satellite basemap overlay:**
```bash
python fire_timelapse.py inputs/your_area.geojson 2023-08-01 2023-08-31 --basemap satellite
```

**With OpenStreetMap basemap:**
```bash
python fire_timelapse.py inputs/your_area.geojson 2023-08-01 2023-08-31 --basemap osm
```

**With terrain basemap:**
```bash
python fire_timelapse.py inputs/your_area.geojson 2023-08-01 2023-08-31 --basemap terrain
```

### Command-Line Arguments

**Positional Arguments:**
- `geojson` - Path to GeoJSON file defining the AOI
- `start_date` - Start date in YYYY-MM-DD format
- `end_date` - End date in YYYY-MM-DD format

**Optional Arguments:**
- `-o, --output` - Base output filename (default: `outputs/videos/OUTPUT_{input_filename}.mp4`)
  - Script will append `_frequency` and `_intensity` to create two videos
  - Example: `--output my_video.mp4` → `my_video_frequency.mp4` and `my_video_intensity.mp4`
- `--fps` - Frames per second for video (default: 3)
- `--cache` - Cache API responses in `outputs/cache/` (useful for development/testing)
- `--keep-frames` - Keep temporary PNG frames in `outputs/frames/` after video generation
- `--basemap` - Add basemap overlay: `osm` (OpenStreetMap), `satellite` (Esri WorldImagery), or `terrain` (Stamen Terrain)
  - Requires contextily: `uv add contextily`
- `-h, --help` - Show help message

## Understanding Frequency vs Intensity

Each run generates **two complementary visualizations** to provide different insights:

### Frequency Video (Detection Count)
- **What it shows**: WHERE fires happen most often
- **Use case**: Identify areas with persistent fire activity
- **Metric**: Number of fire detections
- **Example insight**: "This area had 500 fire detections - lots of small agricultural burns"

### Intensity Video (Fire Radiative Power)
- **What it shows**: WHERE fires burn most intensely
- **Use case**: Identify areas with severe fire events
- **Metric**: Total Fire Radiative Power in megawatts (MW)
- **Example insight**: "This area had 15,000 MW - a few massive wildfires"

**Why both matter**: An area with many small fires (high frequency, low intensity) tells a different story than an area with one massive wildfire (low frequency, high intensity). Both videos together provide complete fire behavior analysis.

## GeoJSON Format

Your GeoJSON file should contain a polygon or multipolygon defining the Area of Interest. Place your GeoJSON files in the `inputs/` directory. See `inputs/example.geojson` for a template.

Example:
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {
        "name": "My Area"
      },
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [-122.5, 37.5],
            [-122.0, 37.5],
            [-122.0, 38.0],
            [-122.5, 38.0],
            [-122.5, 37.5]
          ]
        ]
      }
    }
  ]
}
```

## How It Works

1. **Load AOI**: Reads GeoJSON file and extracts bounding box
2. **Fetch Data**: Queries NASA FIRMS API in parallel (10-day chunks, up to 20 concurrent requests)
3. **Clip to Polygon**: Filters fire points to exact AOI boundaries
4. **Generate Frames (Frequency)**: Creates daily/monthly heatmap visualizations showing fire frequency
   - Uses Kernel Density Estimation (KDE) for 3+ points (uniform weighting)
   - Falls back to scatter plots for sparse data
   - Overlays on basemap tiles (satellite, street map, or terrain)
5. **Compile Frequency Video**: Combines frames into MP4 using H.264 codec
6. **Generate Frames (Intensity)**: Creates daily/monthly heatmap visualizations showing fire intensity
   - KDE weighted by Fire Radiative Power (FRP) values
   - Point sizes scaled by FRP for visual emphasis
   - Shows total MW instead of detection counts
7. **Compile Intensity Video**: Combines FRP-weighted frames into second MP4
8. **Cleanup**: Removes temporary files (unless `--keep-frames` is used)

## Basemap Options

To add geographic context to your visualizations, you can overlay fire data on actual maps using the `--basemap` option:

- **`--basemap osm`**: OpenStreetMap street map (good for seeing roads, cities, boundaries)
- **`--basemap satellite`**: Esri WorldImagery satellite imagery (best for visualizing natural areas)
- **`--basemap terrain`**: Stamen Terrain map (shows topography and elevation)

**Requirements**: Install contextily with `uv add contextily`

**Note**: Basemap tiles are downloaded in real-time, so the first render may take longer due to network requests. The tiles are cached by contextily for subsequent frames in the same area.

## Important Notes

### Data Availability
- **MODIS_SP has a 2-3 month processing delay**
- Recent dates will have no data (this is normal)
- For near-real-time data, NASA offers other sources (VIIRS, MODIS NRT)
- This tool uses MODIS_SP for science-grade processed data

### API Limits
- Maximum 10 days per request (automatically handled)
- 5000 transactions per 10-minute window
- Script includes 0.5-second delays between requests

### Performance
- Large areas or long date ranges will take time
- Use `--cache` during development to avoid re-fetching data
- Cache files are stored in `outputs/cache/` directory
- All outputs (videos, frames, cache) are stored in the `outputs/` directory and gitignored

## Troubleshooting

**"No fire data found"**
- Check your date range (remember the 2-3 month delay)
- Verify your AOI has fire activity during that period
- Try a broader date range or different area

**"MAP_KEY not configured"**
- Set the FIRMS_MAP_KEY environment variable
- Or create a config.json file with your key
- Get your key at https://firms.modaps.eosdis.nasa.gov/api/map_key/

**"API request failed"**
- Check your internet connection
- Verify your MAP_KEY is valid (32 characters)
- You may have hit the rate limit (wait a few minutes)

**Video quality issues**
- Adjust `--fps` parameter (higher = smoother, longer duration)
- Check the generated frames in `outputs/frames/` with `--keep-frames`
- Ensure sufficient fire points exist for heatmap generation

## Examples of Use Cases

- **Wildfire Monitoring**: Track fire progression during fire season
- **Climate Research**: Analyze historical fire patterns
- **Environmental Studies**: Study fire activity in specific ecosystems
- **Risk Assessment**: Visualize fire frequency in vulnerable areas

## Output

The script generates **TWO videos** per run:

1. **Frequency-based video** (`*_frequency.mp4`):
   - Heatmap shows fire detection frequency (where fires happen most often)
   - Info box displays detection counts
   - Bar chart shows number of detections per month

2. **Intensity-based video** (`*_intensity.mp4`):
   - Heatmap weighted by Fire Radiative Power (FRP) - shows where fires burn hottest
   - Larger/brighter areas = higher radiative power output
   - Info box displays total FRP in megawatts (MW)
   - Bar chart shows total FRP per month

### Example Output Files

Input: `inputs/Mangabe_Buffer_50km.geojson`

Outputs:
- `outputs/videos/OUTPUT_Mangabe_Buffer_50km_frequency.mp4` (frequency-based)
- `outputs/videos/OUTPUT_Mangabe_Buffer_50km_intensity.mp4` (intensity-based)

### Additional Outputs
- Optional: Individual PNG frames in `outputs/frames_frequency/` and `outputs/frames_intensity/` (if `--keep-frames` is used)
- Optional: Cached API responses in `outputs/cache/` (if `--cache` is used)
- Console output with statistics and progress

### Video Frame Contents

Each video frame includes:
- Fire activity heatmap (weighted by frequency or FRP)
- AOI boundary outline
- Date label showing full date range
- Month/year and metric value (detections or MW)
- Timeline bar chart (for monthly intervals)
- Optional: Basemap overlay (satellite imagery, street map, or terrain)

## License

MIT

## Credits

- NASA FIRMS for fire detection data
- Generated with Claude Code

## Support

For issues or questions:
- Check NASA FIRMS documentation: https://firms.modaps.eosdis.nasa.gov/
- Verify your GeoJSON format at: http://geojson.io/

---

**Note**: This tool is for educational and research purposes. Always verify fire data with official sources for emergency response.
