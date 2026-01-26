"""
Resource monitoring utilities for report generation
"""
import os
import time
import threading
from typing import Dict, List, Optional
from datetime import datetime

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


class ResourceMonitor:
    """Monitor CPU and memory usage for a process"""
    
    def __init__(self, process_pid: Optional[int] = None, interval: float = 1.0):
        """
        Args:
            process_pid: Process ID to monitor (None = current process)
            interval: Sampling interval in seconds
        """
        self.process_pid = process_pid or os.getpid()
        self.interval = interval
        self.monitoring = False
        self.samples: List[Dict] = []
        self.monitor_thread: Optional[threading.Thread] = None
        
    def start(self):
        """Start monitoring in background thread"""
        if not PSUTIL_AVAILABLE:
            return
        
        self.monitoring = True
        self.samples = []
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
    
    def stop(self):
        """Stop monitoring"""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2.0)
    
    def _monitor_loop(self):
        """Main monitoring loop"""
        try:
            process = psutil.Process(self.process_pid)
            while self.monitoring:
                try:
                    # Get CPU and memory info
                    cpu_percent = process.cpu_percent(interval=None)
                    memory_info = process.memory_info()
                    memory_mb = memory_info.rss / (1024 * 1024)  # Convert to MB
                    
                    # Get system-wide CPU if available
                    system_cpu = psutil.cpu_percent(interval=None)
                    
                    sample = {
                        "timestamp": datetime.now().isoformat(),
                        "cpu_percent": cpu_percent,
                        "system_cpu_percent": system_cpu,
                        "memory_mb": memory_mb,
                        "memory_mb_formatted": f"{memory_mb:.2f}"
                    }
                    
                    self.samples.append(sample)
                    time.sleep(self.interval)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    break
        except Exception:
            pass  # Fail silently if monitoring fails
    
    def get_summary(self) -> Dict:
        """Get summary statistics"""
        if not self.samples:
            return {
                "monitoring_available": PSUTIL_AVAILABLE,
                "samples_count": 0
            }
        
        cpu_values = [s["cpu_percent"] for s in self.samples if s["cpu_percent"] is not None]
        memory_values = [s["memory_mb"] for s in self.samples]
        
        summary = {
            "monitoring_available": PSUTIL_AVAILABLE,
            "samples_count": len(self.samples),
            "duration_seconds": len(self.samples) * self.interval,
            "cpu": {
                "max": max(cpu_values) if cpu_values else 0,
                "avg": sum(cpu_values) / len(cpu_values) if cpu_values else 0,
                "min": min(cpu_values) if cpu_values else 0
            },
            "memory_mb": {
                "max": max(memory_values) if memory_values else 0,
                "avg": sum(memory_values) / len(memory_values) if memory_values else 0,
                "min": min(memory_values) if memory_values else 0,
                "peak": max(memory_values) if memory_values else 0
            },
            "samples": self.samples[-50:]  # Last 50 samples
        }
        
        return summary
    
    def print_summary(self):
        """Print a formatted summary"""
        summary = self.get_summary()
        if not summary["monitoring_available"]:
            print("Resource monitoring not available (psutil not installed)")
            return
        
        if summary["samples_count"] == 0:
            print("No monitoring data collected")
            return
        
        print("\n" + "="*60)
        print("RESOURCE USAGE SUMMARY")
        print("="*60)
        print(f"Duration: {summary['duration_seconds']:.1f} seconds")
        print(f"Samples: {summary['samples_count']}")
        print("\nCPU Usage:")
        print(f"  Peak:   {summary['cpu']['max']:.1f}%")
        print(f"  Average: {summary['cpu']['avg']:.1f}%")
        print(f"  Min:    {summary['cpu']['min']:.1f}%")
        print("\nMemory Usage:")
        print(f"  Peak:   {summary['memory_mb']['peak']:.2f} MB")
        print(f"  Average: {summary['memory_mb']['avg']:.2f} MB")
        print(f"  Min:    {summary['memory_mb']['min']:.2f} MB")
        print("="*60 + "\n")


def monitor_process_by_pid(pid: int, duration: float, interval: float = 1.0) -> Dict:
    """
    Monitor a process by PID for a specific duration.
    This is safe to use - if monitoring fails, it just returns empty data.
    
    Args:
        pid: Process ID to monitor
        duration: How long to monitor (seconds)
        interval: Sampling interval in seconds
    
    Returns:
        Summary dictionary with resource usage
    """
    if not PSUTIL_AVAILABLE:
        return {"monitoring_available": False, "error": "psutil not installed"}
    
    samples = []
    start_time = time.time()
    end_time = start_time + duration
    
    try:
        proc = psutil.Process(pid)
        while time.time() < end_time:
            try:
                # Check if process still exists
                if not proc.is_running():
                    break
                
                cpu_percent = proc.cpu_percent(interval=None)
                memory_info = proc.memory_info()
                memory_mb = memory_info.rss / (1024 * 1024)
                
                samples.append({
                    "timestamp": datetime.now().isoformat(),
                    "cpu_percent": cpu_percent,
                    "memory_mb": memory_mb
                })
                time.sleep(interval)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
            except Exception:
                # Any other error, just continue
                time.sleep(interval)
        
        # Calculate summary
        if samples:
            cpu_values = [s["cpu_percent"] for s in samples if s["cpu_percent"] is not None]
            memory_values = [s["memory_mb"] for s in samples]
            
            return {
                "monitoring_available": True,
                "samples_count": len(samples),
                "duration_seconds": time.time() - start_time,
                "cpu": {
                    "max": max(cpu_values) if cpu_values else 0,
                    "avg": sum(cpu_values) / len(cpu_values) if cpu_values else 0,
                    "min": min(cpu_values) if cpu_values else 0
                },
                "memory_mb": {
                    "max": max(memory_values) if memory_values else 0,
                    "avg": sum(memory_values) / len(memory_values) if memory_values else 0,
                    "min": min(memory_values) if memory_values else 0,
                    "peak": max(memory_values) if memory_values else 0
                },
                "samples": samples
            }
    except Exception as e:
        # Fail silently - don't break report generation
        return {
            "monitoring_available": True,
            "error": str(e),
            "samples_count": 0
        }
    
    return {"monitoring_available": True, "samples_count": 0}


def find_report_processes() -> List[Dict]:
    """
    Find all Python processes running generate_report.py or generate_pitcher_report.py
    
    Returns:
        List of process info dictionaries
    """
    if not PSUTIL_AVAILABLE:
        return []
    
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cpu_percent', 'memory_info']):
        try:
            cmdline = proc.info.get('cmdline', [])
            cmdline_str = ' '.join(str(cmd) for cmd in cmdline)
            
            if 'generate_report.py' in cmdline_str or 'generate_pitcher_report.py' in cmdline_str:
                memory_mb = proc.info['memory_info'].rss / (1024 * 1024) if proc.info.get('memory_info') else 0
                processes.append({
                    "pid": proc.info['pid'],
                    "name": proc.info.get('name', 'python'),
                    "cmdline": cmdline_str,
                    "cpu_percent": proc.info.get('cpu_percent', 0),
                    "memory_mb": memory_mb,
                    "status": proc.status() if hasattr(proc, 'status') else 'unknown'
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        except Exception:
            pass
    
    return processes


