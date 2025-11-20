# NASA FIRMS Fire Timelapse Generator

Generate MP4 timelapse videos showing fire activity heatmaps within a GeoJSON-defined Area of Interest (AOI) using NASA FIRMS MODIS_SP data.

## Features

- Fetches fire detection data from NASA FIRMS API (MODIS Standard Processing)
- Sequential API requests with automatic retry logic for 100% reliability
- Handles API's 10-day request limit with automatic chunking
- Expands AOI by 25km buffer to show fire context beyond boundaries
- Clips fire points to exact polygon boundaries
- Generates smooth KDE heatmaps with customizable colormaps
- Includes satellite, terrain, or street map basemap overlays
- Compiles monthly frames into MP4 videos with timeline bar charts
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
- python-dotenv >= 1.0.0 (for .env file support)
- contextily >= 1.3.0 (optional, for basemap overlays)
- Pillow >= 10.0.0

## Project Structure

```
fire-video-generator/
├── src/
│   └── fire_timelapse.py  # Main script
├── inputs/                # Place your GeoJSON files here
│   └── example.geojson    # Example test area
├── outputs/               # Generated outputs (gitignored)
│   └── videos/            # MP4 timelapse videos
├── .cache/                # API response cache (gitignored)
├── pyproject.toml
├── CLAUDE.md              # Development documentation
└── README.md
```

## Installation

1. Clone this repository
2. Install dependencies using uv:
   ```bash
   uv sync
   ```

## NASA FIRMS API Key

You need a free NASA FIRMS MAP_KEY to use this tool.

### Get Your MAP_KEY

1. Register at: https://firms.modaps.eosdis.nasa.gov/api/map_key/
2. You'll receive a 32-character key via email

### Configure MAP_KEY

Choose one of these methods:

**Option 1: .env File (Recommended)**
Create a `.env` file in the project directory:
```bash
FIRMS_MAP_KEY=your_32_character_key_here
```

**Option 2: Environment Variable**
```bash
export FIRMS_MAP_KEY='your_32_character_key_here'
```

**Option 3: Config File**
Create a `config.json` file in the project directory:
```json
{
  "MAP_KEY": "your_32_character_key_here"
}
```

## Usage

### Basic Usage

```bash
python src/fire_timelapse.py <geojson_file> <start_date> <end_date>
```

### Examples

**Generate a one-month timelapse:**
```bash
python src/fire_timelapse.py inputs/example.geojson 2023-08-01 2023-08-31
```

**Custom frame rate:**
```bash
python src/fire_timelapse.py inputs/your_area.geojson 2023-01-01 2023-12-31 --fps 5
```

**Development mode with caching:**
```bash
python src/fire_timelapse.py inputs/your_area.geojson 2023-06-01 2023-06-30 --cache
```

**Keep frame files for inspection:**
```bash
python src/fire_timelapse.py inputs/your_area.geojson 2023-08-01 2023-08-15 --keep-frames
```

**With satellite basemap overlay (default):**
```bash
python src/fire_timelapse.py inputs/your_area.geojson 2023-08-01 2023-08-31
```

**With OpenStreetMap basemap:**
```bash
python src/fire_timelapse.py inputs/your_area.geojson 2023-08-01 2023-08-31 --basemap osm
```

**With terrain basemap:**
```bash
python src/fire_timelapse.py inputs/your_area.geojson 2023-08-01 2023-08-31 --basemap terrain
```

**Daily interval instead of monthly:**
```bash
python src/fire_timelapse.py inputs/your_area.geojson 2023-08-01 2023-08-31 --interval daily
```

**Adjust rendering quality:**
```bash
# Faster rendering (lower quality)
python src/fire_timelapse.py inputs/your_area.geojson 2023-08-01 2023-08-31 --dpi 60

# Higher quality (slower rendering)
python src/fire_timelapse.py inputs/your_area.geojson 2023-08-01 2023-08-31 --dpi 100
```

### Command-Line Arguments

**Positional Arguments:**
- `geojson` - Path to GeoJSON file defining the AOI
- `start_date` - Start date in YYYY-MM-DD format
- `end_date` - End date in YYYY-MM-DD format

**Optional Arguments:**
- `-o, --output` - Output filename (default: `outputs/videos/OUTPUT_{start}_{end}_{aoi_name}.mp4`)
- `--fps` - Frames per second for video (default: 3)
- `--cache` - Cache API responses in `.cache/` (useful for development/testing)
- `--keep-frames` - Keep temporary PNG frames after video generation
- `--basemap` - Add basemap overlay: `osm`, `satellite` (default), `terrain`, or `none`
- `--interval` - Time interval: `monthly` (default) or `daily`
- `--dpi` - Frame resolution (default: 80, try 60 for speed or 100+ for quality)
- `-h, --help` - Show help message

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

1. **Load AOI**: Reads GeoJSON file and buffers by 25km to fetch surrounding fire data
2. **Fetch Data**: Queries NASA FIRMS API sequentially in 10-day chunks (yearly batches)
3. **Spatial Processing**: Converts fire detections to points and prepares both buffered and clipped datasets
4. **Generate Frames**: Creates monthly/daily heatmap visualizations
   - Uses all fires in buffered area for visualization (shows context)
   - Uses Kernel Density Estimation (KDE) for 3+ points with gnuplot2 colormap
   - Falls back to scatter plots for sparse data
   - Overlays on basemap tiles (satellite by default)
   - Includes timeline bar chart for monthly intervals
5. **Compile Video**: Combines frames into MP4 using H.264 codec
6. **Cleanup**: Removes temporary files (unless `--keep-frames` is used)

## Basemap Options

To add geographic context to your visualizations, you can overlay fire data on actual maps using the `--basemap` option:

- **`--basemap satellite`** (default): Esri WorldImagery satellite imagery
- **`--basemap osm`**: OpenStreetMap street map (roads, cities, boundaries)
- **`--basemap terrain`**: Stamen Terrain map (topography and elevation)
- **`--basemap none`**: No basemap, just fire data and AOI boundary

Basemap tiles are downloaded in real-time and cached by contextily for subsequent frames.

## Visualization Details

### 25km Buffer Zone
The script fetches fire data for 25km beyond your AOI boundaries. This shows fire activity in the surrounding area, providing important context for understanding fire patterns relative to your AOI.

### Colormap
Uses the 'gnuplot2' colormap by default:
- Dark purple/black (low fire density)
- Blue → Cyan → Green
- Yellow → Orange → Red
- Pink/White (high fire density)

Each frame normalizes independently, so colors show relative density within that time period.

### Monthly Bar Chart
Monthly interval mode includes a timeline bar chart showing:
- Fire detection counts for each month
- Current month highlighted in red
- Other months in gray
- Helps visualize temporal patterns

## Important Notes

### Data Availability
- **MODIS_SP has a 2-3 month processing delay**
- Recent dates will have no data (this is normal)
- For near-real-time data, NASA offers other sources (VIIRS, MODIS NRT)
- This tool uses MODIS_SP for science-grade processed data

### API Processing
- **Sequential processing** with 0.3s delays between requests
- Automatic retry logic with exponential backoff
- Processes in yearly batches to prevent data loss
- Maximum 10 days per request (automatically handled)

### Performance
- Small AOI + 1 month ≈ 30-60 seconds
- Large AOI + 1 year ≈ several minutes (mostly API fetching)
- Use `--cache` during development to avoid re-fetching data
- Lower `--dpi` for faster rendering, higher for better quality

## Output

The script generates one MP4 video per run:

**Filename format**: `OUTPUT_{start_date}_{end_date}_{aoi_name}.mp4`

Example: `OUTPUT_2023-08-01_2023-08-31_example.mp4`

### Video Frame Contents

Each video frame includes:
- Fire activity heatmap (KDE with gnuplot2 colormap)
- AOI boundary outline (white line)
- Basemap overlay (satellite imagery by default)
- Month/year label
- Detection count for that period
- Timeline bar chart (for monthly intervals)

### Additional Outputs
- Optional: Individual PNG frames in `outputs/frames_frequency/` (if `--keep-frames` is used)
- Optional: Cached API responses in `.cache/` (if `--cache` is used)

## Troubleshooting

**"No fire data found"**
- Check your date range (remember the 2-3 month delay)
- Verify your AOI has fire activity during that period
- Try a broader date range or different area

**"MAP_KEY not configured"**
- Create a `.env` file with your FIRMS_MAP_KEY
- Or set the environment variable
- Get your key at https://firms.modaps.eosdis.nasa.gov/api/map_key/

**"API request failed"**
- Check your internet connection
- Verify your MAP_KEY is valid (32 characters)
- You may have hit the rate limit (script will retry automatically)

**"Basemap requested but contextily is not installed"**
- Install with: `uv add contextily`
- Or run with `--basemap none`

**Video quality issues**
- Adjust `--dpi` parameter (default 80, try 60-120)
- Check generated frames with `--keep-frames`
- Ensure sufficient fire points exist for heatmap generation

## Examples of Use Cases

- **Wildfire Monitoring**: Track fire progression during fire season
- **Climate Research**: Analyze historical fire patterns
- **Environmental Studies**: Study fire activity in specific ecosystems
- **Risk Assessment**: Visualize fire frequency in vulnerable areas
- **Agricultural Monitoring**: Track controlled burns and crop residue burning

## Development

For development and testing:

1. Use `--cache` to avoid repeated API calls
2. Use `--keep-frames` to inspect individual frames
3. Test with small date ranges first (1 week to 1 month)
4. Use lower `--dpi` (e.g., 60) for faster iteration

Cache files are stored in `.cache/` and are automatically used on subsequent runs with the same parameters.

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
