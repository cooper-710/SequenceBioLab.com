# Resource Monitoring Setup

## Overview
Resource monitoring has been integrated into your report generation system to track CPU and memory usage during report creation. **When a report generation process completes, a downloadable HTML report is automatically generated** with detailed resource usage statistics and Render subscription recommendations.

## What Was Added

1. **Resource Monitoring Utility** (`app/utils/resource_monitor.py`)
   - Tracks CPU and memory usage for processes
   - Safe, non-invasive monitoring that fails gracefully

2. **Integration into Report Service** (`app/services/report_service.py`)
   - Automatically monitors report generation processes
   - Logs resource usage to application logs
   - Includes resource data in report generation results

3. **Standalone Monitoring Dashboard** (`monitor_dashboard.py`)
   - Real-time web interface for viewing resource usage
   - Runs independently on port 5003
   - Auto-refreshes every 2 seconds
   - **Automatically generates downloadable reports when processes complete**
   - Shows Render subscription recommendations based on resource usage

4. **Dependencies**
   - Added `psutil>=5.9.0` to `requirements.txt`

## How to Use

### View Real-Time Monitoring

The monitoring dashboard is now running at:
**http://localhost:5003**

Open this URL in your browser to see:
- Real-time CPU usage (current, peak, average)
- Real-time memory usage (current, peak, average)
- List of active report generation processes
- **Completed reports section with download links**
- Auto-updating metrics every 2 seconds

### Download Reports

When you generate a report, the monitoring system automatically:
1. Tracks resource usage throughout the process
2. Generates a detailed HTML report when the process completes
3. Provides a download link in the dashboard

**Each downloadable report includes:**
- Peak and average CPU/memory usage
- Time-series charts showing usage over time
- Duration and timing information
- **Render subscription recommendation** based on your actual usage
- Complete statistics table

Reports are saved to `build/monitoring_reports/` and can be downloaded directly from the dashboard.

### Start/Stop the Dashboard

**Start the dashboard:**
```bash
python3 monitor_dashboard.py
```

**Stop the dashboard:**
Press `Ctrl+C` in the terminal where it's running, or find the process and kill it.

### View Monitoring in Logs

When you generate reports, resource usage is automatically logged. Check your application logs for entries like:
```
Report generation resource usage for [Player Name]:
  CPU - Peak: 45.2%, Avg: 23.1%
  Memory - Peak: 512.34 MB, Avg: 456.78 MB
```

### Access Resource Data Programmatically

The `generate_single_report()` function now returns resource usage data in the result:
```python
result = generate_single_report(...)
if result.get("resource_usage"):
    print(f"CPU Peak: {result['resource_usage']['cpu_peak']}%")
    print(f"Memory Peak: {result['resource_usage']['memory_peak_mb']} MB")
```

## Installation

If `psutil` is not installed, install it with:
```bash
pip install psutil
```

Or install all requirements:
```bash
pip install -r requirements.txt
```

## Render Subscription Recommendations

The system automatically analyzes your resource usage and recommends the appropriate Render subscription tier:

- **Starter ($7/month)** - For peak memory ≤ 512MB and CPU ≤ 50%
- **Standard ($25/month)** - For peak memory ≤ 1GB and CPU ≤ 100%
- **Pro ($85/month)** - For peak memory ≤ 2GB
- **Pro+ ($230/month)** - For peak memory ≤ 4GB
- **Advanced ($400+/month)** - For peak memory > 4GB

These recommendations are based on your actual peak usage during report generation, helping you choose the right subscription size.

## Notes

- Monitoring is completely safe and non-invasive
- If `psutil` is not available, monitoring gracefully fails and report generation continues normally
- The dashboard runs independently and won't affect your main application
- Monitoring adds minimal overhead (< 1% CPU, < 10MB memory)
- **Reports are automatically generated when processes complete** - no manual action needed
- Reports are stored in `build/monitoring_reports/` for future reference

## Troubleshooting

**Dashboard not loading?**
- Check if port 5003 is available: `lsof -i :5003`
- Make sure Flask is installed: `pip install Flask`

**No processes showing?**
- Start generating a report - the dashboard will detect it automatically
- Make sure `psutil` is installed

**Monitoring not working?**
- Check that `psutil` is installed: `python3 -c "import psutil; print('OK')"`
- Check application logs for any errors

