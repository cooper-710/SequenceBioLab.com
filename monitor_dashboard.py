#!/usr/bin/env python3
"""
Standalone Resource Monitoring Dashboard
Run this to view real-time CPU and memory usage during report generation.
Access at http://localhost:5003
"""
import os
import sys
import time
import json
import threading
from pathlib import Path
from flask import Flask, render_template_string, jsonify, send_file
from datetime import datetime
from collections import defaultdict

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from app.utils.resource_monitor import find_report_processes, monitor_process_by_pid, PSUTIL_AVAILABLE
except ImportError:
    PSUTIL_AVAILABLE = False
    def find_report_processes():
        return []
    def monitor_process_by_pid(*args, **kwargs):
        return {"monitoring_available": False}

app = Flask(__name__)

# Store active monitoring sessions
active_monitors = {}
completed_sessions = []

# Directory for storing reports
REPORTS_DIR = Path(__file__).parent / "build" / "monitoring_reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Track processes and their monitoring data
process_tracking = {}  # pid -> {start_time, samples, cmdline, type}

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Report Generation Monitor</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        .header {
            background: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .header h1 {
            color: #333;
            margin-bottom: 10px;
        }
        .header p {
            color: #666;
        }
        .status-badge {
            display: inline-block;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 600;
            margin-top: 10px;
        }
        .status-active {
            background: #10b981;
            color: white;
        }
        .status-inactive {
            background: #ef4444;
            color: white;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .card {
            background: white;
            padding: 25px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .card h2 {
            color: #333;
            margin-bottom: 20px;
            font-size: 20px;
        }
        .metric {
            margin-bottom: 20px;
        }
        .metric-label {
            font-size: 14px;
            color: #666;
            margin-bottom: 5px;
        }
        .metric-value {
            font-size: 32px;
            font-weight: bold;
            color: #333;
        }
        .metric-unit {
            font-size: 18px;
            color: #999;
            margin-left: 5px;
        }
        .progress-bar {
            width: 100%;
            height: 30px;
            background: #e5e7eb;
            border-radius: 15px;
            overflow: hidden;
            margin-top: 10px;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            transition: width 0.3s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            font-size: 14px;
        }
        .process-list {
            background: white;
            padding: 25px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .process-item {
            padding: 15px;
            border-bottom: 1px solid #e5e7eb;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .process-item:last-child {
            border-bottom: none;
        }
        .process-info {
            flex: 1;
        }
        .process-name {
            font-weight: 600;
            color: #333;
            margin-bottom: 5px;
        }
        .process-details {
            font-size: 12px;
            color: #666;
        }
        .process-metrics {
            text-align: right;
        }
        .process-metric {
            display: inline-block;
            margin-left: 15px;
            font-size: 14px;
        }
        .process-metric-value {
            font-weight: 600;
            color: #667eea;
        }
        .no-processes {
            text-align: center;
            padding: 40px;
            color: #999;
        }
        .chart-container {
            margin-top: 20px;
            height: 200px;
            position: relative;
        }
        .refresh-info {
            text-align: center;
            color: #666;
            font-size: 12px;
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 Report Generation Monitor</h1>
            <p>Real-time CPU and Memory Usage Tracking</p>
            <span id="statusBadge" class="status-badge status-inactive">Monitoring Off</span>
        </div>
        
        <div class="grid">
            <div class="card">
                <h2>CPU Usage</h2>
                <div class="metric">
                    <div class="metric-label">Current</div>
                    <div class="metric-value">
                        <span id="cpuCurrent">0</span><span class="metric-unit">%</span>
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill" id="cpuBar" style="width: 0%">0%</div>
                    </div>
                </div>
                <div class="metric">
                    <div class="metric-label">Peak</div>
                    <div class="metric-value">
                        <span id="cpuPeak">0</span><span class="metric-unit">%</span>
                    </div>
                </div>
                <div class="metric">
                    <div class="metric-label">Average</div>
                    <div class="metric-value">
                        <span id="cpuAvg">0</span><span class="metric-unit">%</span>
                    </div>
                </div>
            </div>
            
            <div class="card">
                <h2>Memory Usage</h2>
                <div class="metric">
                    <div class="metric-label">Current</div>
                    <div class="metric-value">
                        <span id="memCurrent">0</span><span class="metric-unit">MB</span>
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill" id="memBar" style="width: 0%">0 MB</div>
                    </div>
                </div>
                <div class="metric">
                    <div class="metric-label">Peak</div>
                    <div class="metric-value">
                        <span id="memPeak">0</span><span class="metric-unit">MB</span>
                    </div>
                </div>
                <div class="metric">
                    <div class="metric-label">Average</div>
                    <div class="metric-value">
                        <span id="memAvg">0</span><span class="metric-unit">MB</span>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="process-list">
            <h2 style="margin-bottom: 20px; color: #333;">Active Report Processes</h2>
            <div id="processList">
                <div class="no-processes">No report generation processes detected. Start generating a report to see monitoring data.</div>
            </div>
        </div>
        
        <div class="process-list" style="margin-top: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                <h2 style="color: #333; margin: 0;">📥 Completed Reports</h2>
                <a href="/reports" style="background: #667eea; color: white; padding: 8px 16px; border-radius: 5px; text-decoration: none; font-weight: 600; font-size: 14px;">
                    View All Reports →
                </a>
            </div>
            <div id="completedReports">
                <div class="no-processes">No completed reports yet. Generate a report to see monitoring data.</div>
            </div>
        </div>
        
        <div class="refresh-info">
            Auto-refreshing every 2 seconds • Last update: <span id="lastUpdate">Never</span>
        </div>
    </div>
    
    <script>
        let cpuSamples = [];
        let memSamples = [];
        let maxSamples = 50;
        
        function updateMetrics(data) {
            const processes = data.processes || [];
            const completed = data.completed_sessions || [];
            const hasActive = processes.length > 0;
            
            // Update status badge
            const badge = document.getElementById('statusBadge');
            if (hasActive) {
                badge.textContent = 'Monitoring Active';
                badge.className = 'status-badge status-active';
            } else {
                badge.textContent = 'No Active Processes';
                badge.className = 'status-badge status-inactive';
            }
            
            // Aggregate metrics from all processes
            let totalCpu = 0;
            let totalMem = 0;
            let peakCpu = 0;
            let peakMem = 0;
            let avgCpu = 0;
            let avgMem = 0;
            
            if (processes.length > 0) {
                processes.forEach(p => {
                    totalCpu += p.cpu_percent || 0;
                    totalMem += p.memory_mb || 0;
                    peakCpu = Math.max(peakCpu, p.cpu_percent || 0);
                    peakMem = Math.max(peakMem, p.memory_mb || 0);
                });
                avgCpu = totalCpu / processes.length;
                avgMem = totalMem / processes.length;
            }
            
            // Update CPU metrics
            document.getElementById('cpuCurrent').textContent = totalCpu.toFixed(1);
            document.getElementById('cpuPeak').textContent = peakCpu.toFixed(1);
            document.getElementById('cpuAvg').textContent = avgCpu.toFixed(1);
            const cpuBar = document.getElementById('cpuBar');
            const cpuWidth = Math.min(100, totalCpu);
            cpuBar.style.width = cpuWidth + '%';
            cpuBar.textContent = totalCpu.toFixed(1) + '%';
            
            // Update Memory metrics
            document.getElementById('memCurrent').textContent = totalMem.toFixed(2);
            document.getElementById('memPeak').textContent = peakMem.toFixed(2);
            document.getElementById('memAvg').textContent = avgMem.toFixed(2);
            const memBar = document.getElementById('memBar');
            // Assume max reasonable memory is 4GB for progress bar
            const memWidth = Math.min(100, (totalMem / 4096) * 100);
            memBar.style.width = memWidth + '%';
            memBar.textContent = totalMem.toFixed(2) + ' MB';
            
            // Update process list
            const processList = document.getElementById('processList');
            if (processes.length === 0) {
                processList.innerHTML = '<div class="no-processes">No report generation processes detected. Start generating a report to see monitoring data.</div>';
            } else {
                processList.innerHTML = processes.map(p => {
                    const cmdline = p.cmdline || 'Unknown';
                    const scriptName = cmdline.includes('generate_pitcher_report') ? 'Pitcher Report' : 'Hitter Report';
                    return `
                        <div class="process-item">
                            <div class="process-info">
                                <div class="process-name">${scriptName}</div>
                                <div class="process-details">PID: ${p.pid} • ${cmdline.substring(0, 80)}...</div>
                            </div>
                            <div class="process-metrics">
                                <span class="process-metric">
                                    CPU: <span class="process-metric-value">${(p.cpu_percent || 0).toFixed(1)}%</span>
                                </span>
                                <span class="process-metric">
                                    Memory: <span class="process-metric-value">${(p.memory_mb || 0).toFixed(2)} MB</span>
                                </span>
                            </div>
                        </div>
                    `;
                }).join('');
            }
            
            // Update completed reports
            const completedReports = document.getElementById('completedReports');
            if (completed.length === 0) {
                completedReports.innerHTML = '<div class="no-processes">No completed reports yet. Generate a report to see monitoring data.</div>';
            } else {
                completedReports.innerHTML = completed.reverse().map(session => {
                    const stats = session.stats || {};
                    const date = new Date(session.timestamp).toLocaleString();
                    return `
                        <div class="process-item">
                            <div class="process-info">
                                <div class="process-name">${session.type.charAt(0).toUpperCase() + session.type.slice(1)} Report - ${date}</div>
                                <div class="process-details">
                                    Peak: ${stats.cpu?.peak?.toFixed(1) || 0}% CPU, ${stats.memory_mb?.peak?.toFixed(2) || 0} MB Memory • 
                                    Duration: ${(stats.duration_seconds || 0).toFixed(1)}s • 
                                    Recommendation: ${stats.render_recommendation || 'N/A'}
                                </div>
                            </div>
                            <div class="process-metrics">
                                <a href="/download/${session.id}" class="process-metric" style="text-decoration: none; background: #667eea; color: white; padding: 8px 16px; border-radius: 5px; font-weight: 600;">
                                    📥 Download Report
                                </a>
                            </div>
                        </div>
                    `;
                }).join('');
            }
            
            // Update last update time
            document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString();
        }
        
        function fetchData() {
            fetch('/api/processes')
                .then(response => response.json())
                .then(data => {
                    updateMetrics(data);
                })
                .catch(error => {
                    console.error('Error fetching data:', error);
                });
        }
        
        // Initial fetch
        fetchData();
        
        // Auto-refresh every 2 seconds
        setInterval(fetchData, 2000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template_string(DASHBOARD_HTML)

def track_process(pid, cmdline):
    """Start tracking a process"""
    if pid not in process_tracking:
        process_tracking[pid] = {
            "start_time": datetime.now(),
            "samples": [],
            "cmdline": cmdline,
            "type": "pitcher" if "pitcher_report" in cmdline else "hitter",
            "last_sample_time": None
        }

def update_process_tracking():
    """Background thread to continuously monitor and track processes"""
    while True:
        try:
            if not PSUTIL_AVAILABLE:
                time.sleep(5)
                continue
            
            current_processes = find_report_processes()
            current_pids = set()
            
            for proc_info in current_processes:
                pid = proc_info['pid']
                current_pids.add(pid)
                
                # Start tracking if new
                if pid not in process_tracking:
                    track_process(pid, proc_info.get('cmdline', ''))
                
                # Collect sample
                try:
                    import psutil
                    proc = psutil.Process(pid)
                    cpu = proc.cpu_percent(interval=0.1)
                    mem = proc.memory_info().rss / (1024 * 1024)
                    
                    sample = {
                        "timestamp": datetime.now().isoformat(),
                        "cpu_percent": cpu,
                        "memory_mb": mem
                    }
                    
                    process_tracking[pid]["samples"].append(sample)
                    process_tracking[pid]["last_sample_time"] = datetime.now()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # Process ended, generate report
                    if pid in process_tracking:
                        generate_session_report(pid)
                        del process_tracking[pid]
                except Exception:
                    pass
            
            # Check for processes that ended
            ended_pids = set(process_tracking.keys()) - current_pids
            for pid in ended_pids:
                generate_session_report(pid)
                del process_tracking[pid]
            
            time.sleep(2)
        except Exception:
            time.sleep(5)

def generate_session_report(pid):
    """Generate a downloadable report for a completed session"""
    if pid not in process_tracking:
        return
    
    session = process_tracking[pid]
    if not session["samples"]:
        return
    
    # Calculate statistics
    cpu_values = [s["cpu_percent"] for s in session["samples"]]
    mem_values = [s["memory_mb"] for s in session["samples"]]
    
    duration = (session["last_sample_time"] - session["start_time"]).total_seconds()
    
    stats = {
        "start_time": session["start_time"].isoformat(),
        "end_time": session["last_sample_time"].isoformat(),
        "duration_seconds": duration,
        "type": session["type"],
        "cmdline": session["cmdline"],
        "cpu": {
            "peak": max(cpu_values) if cpu_values else 0,
            "avg": sum(cpu_values) / len(cpu_values) if cpu_values else 0,
            "min": min(cpu_values) if cpu_values else 0
        },
        "memory_mb": {
            "peak": max(mem_values) if mem_values else 0,
            "avg": sum(mem_values) / len(mem_values) if mem_values else 0,
            "min": min(mem_values) if mem_values else 0
        },
        "samples_count": len(session["samples"])
    }
    
    # Generate Render subscription recommendation
    mem_peak_gb = stats["memory_mb"]["peak"] / 1024
    cpu_peak = stats["cpu"]["peak"]
    
    if mem_peak_gb <= 0.5 and cpu_peak <= 50:
        recommendation = "Starter ($7/month) - 512MB RAM, Shared CPU"
        recommendation_level = "starter"
    elif mem_peak_gb <= 1.0 and cpu_peak <= 100:
        recommendation = "Standard ($25/month) - 1GB RAM, Shared CPU"
        recommendation_level = "standard"
    elif mem_peak_gb <= 2.0:
        recommendation = "Pro ($85/month) - 2GB RAM, Dedicated CPU"
        recommendation_level = "pro"
    elif mem_peak_gb <= 4.0:
        recommendation = "Pro+ ($230/month) - 4GB RAM, Dedicated CPU"
        recommendation_level = "pro_plus"
    else:
        recommendation = "Advanced ($400+/month) - 8GB+ RAM, Dedicated CPU"
        recommendation_level = "advanced"
    
    stats["render_recommendation"] = recommendation
    stats["render_level"] = recommendation_level
    
    # Generate HTML report
    report_id = f"report_{pid}_{int(session['start_time'].timestamp())}"
    report_file = REPORTS_DIR / f"{report_id}.html"
    
    html_content = generate_html_report(stats, session["samples"])
    report_file.write_text(html_content, encoding='utf-8')
    
    # Also save JSON data
    json_file = REPORTS_DIR / f"{report_id}.json"
    json_file.write_text(json.dumps(stats, indent=2), encoding='utf-8')
    
    # Add to completed sessions
    completed_sessions.append({
        "id": report_id,
        "timestamp": session["start_time"].isoformat(),
        "type": session["type"],
        "stats": stats,
        "report_file": str(report_file),
        "json_file": str(json_file)
    })
    
    # Keep only last 50 sessions
    if len(completed_sessions) > 50:
        completed_sessions.pop(0)

def generate_html_report(stats, samples):
    """Generate HTML report content"""
    cpu_peak = stats["cpu"]["peak"]
    cpu_avg = stats["cpu"]["avg"]
    mem_peak = stats["memory_mb"]["peak"]
    mem_avg = stats["memory_mb"]["avg"]
    duration = stats["duration_seconds"]
    
    # Generate time series data for chart
    time_data = []
    cpu_data = []
    mem_data = []
    start_time = datetime.fromisoformat(stats["start_time"])
    
    for i, sample in enumerate(samples):
        sample_time = datetime.fromisoformat(sample["timestamp"])
        elapsed = (sample_time - start_time).total_seconds()
        time_data.append(round(elapsed, 1))
        cpu_data.append(round(sample["cpu_percent"], 1))
        mem_data.append(round(sample["memory_mb"], 2))
    
    # Format data for JavaScript
    time_data_js = json.dumps(time_data)
    cpu_data_js = json.dumps(cpu_data)
    mem_data_js = json.dumps(mem_data)
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Resource Usage Report - {stats['type'].title()} Report Generation</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{ color: #333; margin-bottom: 10px; }}
        .subtitle {{ color: #666; margin-bottom: 30px; }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
        }}
        .stat-label {{ font-size: 14px; opacity: 0.9; margin-bottom: 5px; }}
        .stat-value {{ font-size: 32px; font-weight: bold; }}
        .recommendation {{
            background: #10b981;
            color: white;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
        }}
        .recommendation h2 {{ margin-bottom: 10px; }}
        .chart-container {{
            margin: 30px 0;
            height: 400px;
            position: relative;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background: #f5f5f5;
            font-weight: 600;
        }}
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            color: #666;
            font-size: 14px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Resource Usage Report</h1>
        <p class="subtitle">{stats['type'].title()} Report Generation - {datetime.fromisoformat(stats['start_time']).strftime('%Y-%m-%d %H:%M:%S')}</p>
        
        <div class="recommendation">
            <h2>💡 Render Subscription Recommendation</h2>
            <p style="font-size: 18px; margin-top: 10px;">{stats['render_recommendation']}</p>
            <p style="margin-top: 10px; opacity: 0.9;">Based on peak memory usage of {mem_peak:.2f} MB and peak CPU of {cpu_peak:.1f}%</p>
        </div>
        
        <div class="grid">
            <div class="stat-card">
                <div class="stat-label">Peak CPU Usage</div>
                <div class="stat-value">{cpu_peak:.1f}%</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Average CPU Usage</div>
                <div class="stat-value">{cpu_avg:.1f}%</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Peak Memory Usage</div>
                <div class="stat-value">{mem_peak:.2f} MB</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Average Memory Usage</div>
                <div class="stat-value">{mem_avg:.2f} MB</div>
            </div>
        </div>
        
        <div class="chart-container">
            <canvas id="usageChart"></canvas>
        </div>
        
        <h2 style="margin-top: 40px; margin-bottom: 20px;">Summary Statistics</h2>
        <table>
            <tr>
                <th>Metric</th>
                <th>Value</th>
            </tr>
            <tr>
                <td>Report Type</td>
                <td>{stats['type'].title()} Report</td>
            </tr>
            <tr>
                <td>Duration</td>
                <td>{duration:.1f} seconds ({duration/60:.1f} minutes)</td>
            </tr>
            <tr>
                <td>Start Time</td>
                <td>{datetime.fromisoformat(stats['start_time']).strftime('%Y-%m-%d %H:%M:%S')}</td>
            </tr>
            <tr>
                <td>End Time</td>
                <td>{datetime.fromisoformat(stats['end_time']).strftime('%Y-%m-%d %H:%M:%S')}</td>
            </tr>
            <tr>
                <td>CPU Peak</td>
                <td>{cpu_peak:.1f}%</td>
            </tr>
            <tr>
                <td>CPU Average</td>
                <td>{cpu_avg:.1f}%</td>
            </tr>
            <tr>
                <td>CPU Minimum</td>
                <td>{stats['cpu']['min']:.1f}%</td>
            </tr>
            <tr>
                <td>Memory Peak</td>
                <td>{mem_peak:.2f} MB ({mem_peak/1024:.2f} GB)</td>
            </tr>
            <tr>
                <td>Memory Average</td>
                <td>{mem_avg:.2f} MB ({mem_avg/1024:.2f} GB)</td>
            </tr>
            <tr>
                <td>Memory Minimum</td>
                <td>{stats['memory_mb']['min']:.2f} MB</td>
            </tr>
            <tr>
                <td>Samples Collected</td>
                <td>{stats['samples_count']}</td>
            </tr>
        </table>
        
        <div class="footer">
            <p>Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>This report helps determine the appropriate Render subscription tier for your report generation workload.</p>
        </div>
    </div>
    
    <script>
        const ctx = document.getElementById('usageChart').getContext('2d');
        const timeData = {time_data_js};
        const cpuData = {cpu_data_js};
        const memData = {mem_data_js};
        
        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: timeData.map(t => t.toFixed(1) + 's'),
                datasets: [
                    {{
                        label: 'CPU Usage (%)',
                        data: cpuData,
                        borderColor: 'rgb(102, 126, 234)',
                        backgroundColor: 'rgba(102, 126, 234, 0.1)',
                        yAxisID: 'y',
                        tension: 0.4
                    }},
                    {{
                        label: 'Memory Usage (MB)',
                        data: memData,
                        borderColor: 'rgb(118, 75, 162)',
                        backgroundColor: 'rgba(118, 75, 162, 0.1)',
                        yAxisID: 'y1',
                        tension: 0.4
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{
                    mode: 'index',
                    intersect: false,
                }},
                scales: {{
                    x: {{
                        title: {{
                            display: true,
                            text: 'Time (seconds)'
                        }}
                    }},
                    y: {{
                        type: 'linear',
                        display: true,
                        position: 'left',
                        title: {{
                            display: true,
                            text: 'CPU Usage (%)'
                        }}
                    }},
                    y1: {{
                        type: 'linear',
                        display: true,
                        position: 'right',
                        title: {{
                            display: true,
                            text: 'Memory Usage (MB)'
                        }},
                        grid: {{
                            drawOnChartArea: false,
                        }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""

# Start background tracking thread
tracking_thread = threading.Thread(target=update_process_tracking, daemon=True)
tracking_thread.start()

@app.route('/api/processes')
def api_processes():
    """API endpoint to get current report processes"""
    if not PSUTIL_AVAILABLE:
        return jsonify({
            "error": "psutil not available",
            "processes": [],
            "completed_sessions": completed_sessions[-10:]  # Last 10
        })
    
    processes = find_report_processes()
    
    # Update CPU percentages for all processes
    for proc_info in processes:
        try:
            import psutil
            proc = psutil.Process(proc_info['pid'])
            proc_info['cpu_percent'] = proc.cpu_percent(interval=0.1)
            proc_info['memory_mb'] = proc.memory_info().rss / (1024 * 1024)
            proc_info['status'] = proc.status()
            
            # Start tracking if not already
            if proc_info['pid'] not in process_tracking:
                track_process(proc_info['pid'], proc_info.get('cmdline', ''))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            proc_info['cpu_percent'] = 0
            proc_info['memory_mb'] = 0
        except Exception:
            pass
    
    return jsonify({
        "processes": processes,
        "timestamp": datetime.now().isoformat(),
        "monitoring_available": PSUTIL_AVAILABLE,
        "completed_sessions": completed_sessions[-10:]  # Last 10 completed
    })

@app.route('/download/<report_id>')
def download_report(report_id):
    """Download a generated report"""
    report_file = REPORTS_DIR / f"{report_id}.html"
    if report_file.exists():
        return send_file(str(report_file), as_attachment=True, download_name=f"{report_id}.html")
    return jsonify({"error": "Report not found"}), 404

@app.route('/api/reports')
def api_reports():
    """Get list of all available reports"""
    # Also check for existing reports in the directory
    existing_reports = []
    if REPORTS_DIR.exists():
        for json_file in REPORTS_DIR.glob("*.json"):
            try:
                report_data = json.loads(json_file.read_text(encoding='utf-8'))
                report_id = json_file.stem
                html_file = REPORTS_DIR / f"{report_id}.html"
                if html_file.exists():
                    existing_reports.append({
                        "id": report_id,
                        "timestamp": report_data.get("start_time", ""),
                        "type": report_data.get("type", "unknown"),
                        "stats": report_data,
                        "report_file": str(html_file),
                        "json_file": str(json_file)
                    })
            except Exception:
                pass
    
    # Combine with in-memory sessions
    all_reports = completed_sessions + existing_reports
    # Remove duplicates and sort by timestamp
    seen_ids = set()
    unique_reports = []
    for report in sorted(all_reports, key=lambda x: x.get("timestamp", ""), reverse=True):
        if report["id"] not in seen_ids:
            seen_ids.add(report["id"])
            unique_reports.append(report)
    
    return jsonify({
        "reports": unique_reports[:20],  # Last 20
        "total": len(unique_reports)
    })

@app.route('/reports')
def reports_page():
    """Dedicated page to view all reports"""
    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Monitoring Reports</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        .header {
            background: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .header h1 { color: #333; margin-bottom: 10px; }
        .header a {
            color: #667eea;
            text-decoration: none;
            font-weight: 600;
        }
        .reports-list {
            background: white;
            padding: 25px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .report-item {
            padding: 20px;
            border-bottom: 1px solid #e5e7eb;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .report-item:last-child { border-bottom: none; }
        .report-info h3 { color: #333; margin-bottom: 8px; }
        .report-info p { color: #666; font-size: 14px; }
        .download-btn {
            background: #667eea;
            color: white;
            padding: 10px 20px;
            border-radius: 5px;
            text-decoration: none;
            font-weight: 600;
        }
        .download-btn:hover { background: #5568d3; }
        .no-reports {
            text-align: center;
            padding: 40px;
            color: #999;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 Monitoring Reports</h1>
            <p>View and download resource usage reports</p>
            <a href="/">← Back to Dashboard</a>
        </div>
        <div class="reports-list">
            <div id="reportsList">
                <div class="no-reports">Loading reports...</div>
            </div>
        </div>
    </div>
    <script>
        function loadReports() {
            fetch('/api/reports')
                .then(response => response.json())
                .then(data => {
                    const reports = data.reports || [];
                    const list = document.getElementById('reportsList');
                    
                    if (reports.length === 0) {
                        list.innerHTML = '<div class="no-reports">No reports available yet. Generate a report to see monitoring data.</div>';
                        return;
                    }
                    
                    list.innerHTML = reports.map(report => {
                        const stats = report.stats || {};
                        const date = new Date(report.timestamp || Date.now()).toLocaleString();
                        const type = (report.type || 'unknown').charAt(0).toUpperCase() + (report.type || 'unknown').slice(1);
                        return `
                            <div class="report-item">
                                <div class="report-info">
                                    <h3>${type} Report - ${date}</h3>
                                    <p>
                                        Peak: ${(stats.cpu?.peak || 0).toFixed(1)}% CPU, ${(stats.memory_mb?.peak || 0).toFixed(2)} MB Memory • 
                                        Duration: ${(stats.duration_seconds || 0).toFixed(1)}s • 
                                        Recommendation: ${stats.render_recommendation || 'N/A'}
                                    </p>
                                </div>
                                <a href="/download/${report.id}" class="download-btn">📥 Download</a>
                            </div>
                        `;
                    }).join('');
                })
                .catch(error => {
                    console.error('Error loading reports:', error);
                    document.getElementById('reportsList').innerHTML = 
                        '<div class="no-reports">Error loading reports. Please refresh the page.</div>';
                });
        }
        
        loadReports();
        setInterval(loadReports, 5000); // Refresh every 5 seconds
    </script>
</body>
</html>
""")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5003))
    print(f"\n{'='*60}")
    print(f"📊 Report Generation Monitor Dashboard")
    print(f"{'='*60}")
    print(f"Starting server on http://localhost:{port}")
    print(f"Open this URL in your browser to view monitoring data")
    print(f"{'='*60}\n")
    
    if not PSUTIL_AVAILABLE:
        print("⚠️  WARNING: psutil is not installed. Install it with: pip install psutil")
        print("   Monitoring will not work without psutil.\n")
    
    app.run(debug=True, host='127.0.0.1', port=port, use_reloader=False)

