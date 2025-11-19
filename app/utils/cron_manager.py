"""
Utility for managing cron jobs for scheduled data refresh
"""
import subprocess
from pathlib import Path
from typing import Optional, Tuple

ROOT_DIR = Path(__file__).parent.parent.parent.resolve()
UPDATE_SCRIPT = ROOT_DIR / "scripts" / "update_csv_data.py"
LOG_FILE = ROOT_DIR / "logs" / "data_update.log"


def get_current_cron_job() -> Optional[str]:
    """Get the current cron job for data refresh if it exists."""
    try:
        result = subprocess.run(
            ['crontab', '-l'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'update_csv_data.py' in line and not line.strip().startswith('#'):
                    return line.strip()
    except Exception:
        pass
    return None


def create_cron_job(hour: int, minute: int) -> Tuple[bool, str]:
    """
    Create or update the cron job for scheduled data refresh.
    Returns (success, message)
    """
    try:
        # Get current crontab
        result = subprocess.run(
            ['crontab', '-l'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        lines = []
        if result.returncode == 0:
            lines = result.stdout.split('\n')
        
        # Remove any existing data refresh cron job
        lines = [line for line in lines if 'update_csv_data.py' not in line or line.strip().startswith('#')]
        
        # Add new cron job
        python_path = subprocess.run(
            ['which', 'python3'],
            capture_output=True,
            text=True,
            timeout=5
        ).stdout.strip()
        
        if not python_path:
            return False, "Could not find python3 executable"
        
        cron_line = f"{minute} {hour} * * * cd {ROOT_DIR} && {python_path} {UPDATE_SCRIPT} >> {LOG_FILE} 2>&1"
        lines.append(cron_line)
        
        # Write new crontab
        process = subprocess.Popen(
            ['crontab', '-'],
            stdin=subprocess.PIPE,
            text=True
        )
        process.communicate(input='\n'.join(lines))
        
        if process.returncode == 0:
            return True, f"Scheduled refresh enabled for {hour:02d}:{minute:02d}"
        else:
            return False, "Failed to update crontab"
            
    except Exception as e:
        return False, f"Error creating cron job: {str(e)}"


def remove_cron_job() -> Tuple[bool, str]:
    """Remove the cron job for scheduled data refresh."""
    try:
        result = subprocess.run(
            ['crontab', '-l'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return True, "No cron job found"
        
        lines = result.stdout.split('\n')
        filtered_lines = [line for line in lines if 'update_csv_data.py' not in line or line.strip().startswith('#')]
        
        if len(filtered_lines) == len(lines):
            return True, "No cron job found"
        
        # Write updated crontab
        process = subprocess.Popen(
            ['crontab', '-'],
            stdin=subprocess.PIPE,
            text=True
        )
        process.communicate(input='\n'.join(filtered_lines))
        
        if process.returncode == 0:
            return True, "Scheduled refresh disabled"
        else:
            return False, "Failed to update crontab"
            
    except Exception as e:
        return False, f"Error removing cron job: {str(e)}"


def get_cron_status() -> dict:
    """Get the current status of the cron job."""
    cron_job = get_current_cron_job()
    if cron_job:
        # Parse the cron line to extract hour and minute
        parts = cron_job.split()
        if len(parts) >= 2:
            try:
                minute = int(parts[0])
                hour = int(parts[1])
                return {
                    'enabled': True,
                    'hour': hour,
                    'minute': minute,
                    'cron_line': cron_job
                }
            except ValueError:
                pass
    
    return {
        'enabled': False,
        'hour': None,
        'minute': None,
        'cron_line': None
    }

