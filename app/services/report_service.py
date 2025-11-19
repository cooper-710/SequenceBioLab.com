"""
Report generation service
"""
import os
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from app.config import Config
from app.utils.helpers import sanitize_filename_component
from app.utils.file_utils import report_exists_for_player
from app.constants import REPORT_LEAD_DAYS
from app.utils.formatters import extract_game_datetime

# Global job status (replace with Redis in production)
job_status: Dict[str, Any] = {}

# Pending report keys (for preventing duplicate reports)
_pending_report_keys: set = set()
_pending_report_lock = threading.Lock()


def generate_single_report(
    hitter_name: str,
    team: str = "AUTO",
    season_start: str = "2025-03-20",
    use_next_series: bool = False,
    opponent_team: Optional[str] = None,
    pdf_name: Optional[str] = None
) -> Dict[str, Any]:
    """Generate a single report and return the PDF path"""
    try:
        # Activate virtual environment and run the report generation
        venv_python = Config.ROOT_DIR / "venv" / "bin" / "python3"
        if not venv_python.exists():
            venv_python = "python3"
        
        script_path = Config.ROOT_DIR / "src" / "generate_report.py"
        template_path = Config.ROOT_DIR / "src" / "templates" / "hitter_report.html"
        
        cmd = [
            str(venv_python),
            str(script_path),
            "--team", team,
            "--hitter", hitter_name,
            "--season_start", season_start,
            "--out", str(Config.PDF_OUTPUT_DIR),
            "--template", str(template_path)
        ]
        
        if pdf_name:
            cmd.extend(["--pdf_name", pdf_name])

        if opponent_team and opponent_team.strip():
            cmd.extend(["--opponent", opponent_team.strip()])
        
        if use_next_series:
            cmd.append("--use-next-series")
        
        # Run the command with environment variable to suppress urllib3 warnings
        env = os.environ.copy()
        env['PYTHONWARNINGS'] = 'ignore::UserWarning:urllib3,ignore::Warning'
        
        result = subprocess.run(
            cmd,
            cwd=str(Config.ROOT_DIR / "src"),
            capture_output=True,
            text=True,
            timeout=Config.REPORT_TIMEOUT,
            env=env
        )
        
        # First, check if PDF was generated (even if returncode != 0, warnings might cause non-zero exit)
        output_lines = result.stdout.split('\n')
        pdf_path = None
        
        for line in output_lines:
            if "Saved report:" in line:
                pdf_path = line.split("Saved report:")[-1].strip()
                break
        
        # If we can't find it from output, try to find it by name
        if not pdf_path or not Path(pdf_path).exists():
            # Look for PDFs with the player's name
            safe_name = hitter_name.replace(' ', '_').replace('"', '')
            pdf_files = list(Config.PDF_OUTPUT_DIR.glob(f"*{safe_name}*.pdf"))
            if pdf_files:
                # Sort by modification time and get the most recent
                pdf_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                pdf_path = str(pdf_files[0])
        
        # If PDF was generated, return success regardless of returncode
        if pdf_path and Path(pdf_path).exists():
            return {
                "success": True,
                "pdf_path": pdf_path,
                "pdf_filename": Path(pdf_path).name
            }
        
        # If no PDF found and returncode != 0, report the error
        if result.returncode != 0:
            # Combine stderr and stdout to get full error
            error_msg = ""
            if result.stderr:
                error_msg += result.stderr
            if result.stdout and result.stdout.strip():
                error_msg += "\n" + result.stdout if error_msg else result.stdout
            
            if not error_msg.strip():
                error_msg = "Unknown error"
            
            # Filter out urllib3 warnings - they're not fatal errors
            lines = error_msg.split('\n')
            filtered_lines = []
            skip_next_n_lines = 0
            
            for i, line in enumerate(lines):
                # Skip lines after warnings.warn( calls
                if skip_next_n_lines > 0:
                    skip_next_n_lines -= 1
                    continue
                
                # Skip urllib3/OpenSSL warnings
                if any(keyword in line for keyword in ['NotOpenSSLWarning', 'urllib3', 'site-packages/urllib3', 'OpenSSL']):
                    # If we see warnings.warn(, skip the next few lines too
                    if 'warnings.warn(' in line:
                        skip_next_n_lines = 2
                    continue
                
                # Skip lines that are just file paths to urllib3
                if line.strip().startswith('/Users') and ('urllib3' in line or 'site-packages' in line):
                    continue
                
                # Skip warning-related lines
                if 'warnings.warn(' in line or '__init__.py' in line and 'site-packages' in line:
                    skip_next_n_lines = 1
                    continue
                
                # Keep non-empty lines that aren't warnings
                if line.strip() and not line.strip().startswith('warnings.'):
                    filtered_lines.append(line)
            
            # If we filtered everything, keep some context
            if filtered_lines:
                filtered_error = '\n'.join(filtered_lines)
            else:
                # If only warnings were present, check if stdout has useful info
                if result.stdout and result.stdout.strip():
                    filtered_error = result.stdout.strip()
                else:
                    filtered_error = "Report generation failed (check logs for details)"
            
            # Get the actual error message (last meaningful line or traceback)
            error_lines = filtered_error.split('\n')
            # Look for the actual exception message
            actual_error = None
            for i in range(len(error_lines) - 1, -1, -1):
                line = error_lines[i].strip()
                if line and not line.startswith('File ') and not line.startswith('Traceback'):
                    if 'Error' in line or 'Exception' in line or ':' in line:
                        actual_error = line
                        break
            
            if actual_error:
                filtered_error = actual_error + "\n\n" + filtered_error[:300]
            
            return {
                "success": False,
                "error": f"Error generating report: {filtered_error[:800]}"
            }
        
        # If returncode is 0 but no PDF found
        return {
            "success": False,
            "error": "Report generation completed but PDF file not found"
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Report generation timed out (over {Config.REPORT_TIMEOUT // 60} minutes)"
        }
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error generating report: {e}", exc_info=True)
        return {
            "success": False,
            "error": f"Error: {str(e)}"
        }


def generate_report_background(
    hitter_name: str,
    team: str = "AUTO",
    season_start: str = "2025-03-20",
    use_next_series: bool = False,
    opponent_team: Optional[str] = None,
    job_id: Optional[str] = None
) -> None:
    """Generate a single report in the background"""
    if job_id is None:
        job_id = str(uuid.uuid4())
    
    result = generate_single_report(hitter_name, team, season_start, use_next_series, opponent_team)
    
    if result["success"]:
        job_status[job_id] = {
            "status": "completed",
            "message": "Report generated successfully!",
            "pdf_path": result["pdf_path"],
            "pdf_filename": result["pdf_filename"]
        }
    else:
        job_status[job_id] = {
            "status": "error",
            "message": result.get("error", "Unknown error")
        }


def parse_player_entry(entry: str) -> tuple:
    """Parse a player entry that may include team and opponent.
    
    Format: "Player Name | Team | Opponent"
    Returns: (player_name, team, opponent)
    """
    parts = [p.strip() for p in entry.split('|')]
    player_name = parts[0].strip() if parts else ""
    team = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    opponent = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
    
    return player_name, team, opponent


def generate_batch_reports(
    player_entries: List[str],
    default_team: str,
    season_start: str,
    use_next_series: bool,
    default_opponent: Optional[str],
    job_id: str
) -> None:
    """Generate reports for multiple players with individual settings"""
    total = len(player_entries)
    completed = 0
    failed = 0
    pdfs = []
    errors = []
    
    for i, entry in enumerate(player_entries):
        # Parse player entry
        hitter_name, team, opponent = parse_player_entry(entry)
        
        if not hitter_name:
            failed += 1
            errors.append(f"Entry {i+1}: Invalid player name")
            continue
        
        # Use entry-specific settings or defaults
        player_team = team if team else default_team
        player_opponent = opponent if opponent else default_opponent
        
        # Update job status
        status_msg = f"Generating report {i+1} of {total}: {hitter_name}"
        job_status[job_id] = {
            "status": "processing",
            "message": status_msg,
            "total": total,
            "completed": completed,
            "failed": failed,
            "current": i + 1
        }
        
        # Generate single report
        result = generate_single_report(
            hitter_name, player_team, season_start, use_next_series, player_opponent
        )
        
        if result["success"]:
            completed += 1
            pdfs.append({
                "player": hitter_name,
                "pdf_path": result["pdf_path"],
                "pdf_filename": result["pdf_filename"]
            })
        else:
            failed += 1
            errors.append(f"{hitter_name}: {result.get('error', 'Unknown error')}")
    
    # Final status
    job_status[job_id] = {
        "status": "completed" if failed == 0 else "partial",
        "message": f"Completed {completed} of {total} reports" + (f" ({failed} failed)" if failed > 0 else ""),
        "total": total,
        "completed": completed,
        "failed": failed,
        "pdfs": pdfs,
        "errors": errors
    }


def generate_single_pitcher_report(
    pitcher_name: str,
    team: str = "AUTO",
    season_start: str = "2025-03-20",
    use_next_series: bool = False,
    opponent_team: Optional[str] = None
) -> Dict[str, Any]:
    """Generate a single pitcher report and return the PDF path"""
    try:
        venv_python = Config.ROOT_DIR / "venv" / "bin" / "python3"
        if not venv_python.exists():
            venv_python = "python3"
        
        script_path = Config.ROOT_DIR / "src" / "generate_pitcher_report.py"
        template_path = Config.ROOT_DIR / "src" / "templates" / "pitcher_report.html"
        
        cmd = [
            str(venv_python),
            str(script_path),
            "--team", team,
            "--pitcher", pitcher_name,
            "--season_start", season_start,
            "--out", str(Config.PDF_OUTPUT_DIR),
            "--template", str(template_path)
        ]

        if opponent_team and opponent_team.strip():
            cmd.extend(["--opponent", opponent_team.strip()])
        
        if use_next_series:
            cmd.append("--use-next-series")
        
        env = os.environ.copy()
        env['PYTHONWARNINGS'] = 'ignore::UserWarning:urllib3,ignore::Warning'
        
        result = subprocess.run(
            cmd,
            cwd=str(Config.ROOT_DIR / "src"),
            capture_output=True,
            text=True,
            timeout=Config.REPORT_TIMEOUT,
            env=env
        )
        
        output_lines = result.stdout.split('\n')
        pdf_path = None
        
        for line in output_lines:
            if "Saved report:" in line:
                pdf_path = line.split("Saved report:")[-1].strip()
                break
        
        if not pdf_path or not Path(pdf_path).exists():
            safe_name = pitcher_name.replace(' ', '_').replace('"', '')
            pdf_files = list(Config.PDF_OUTPUT_DIR.glob(f"*{safe_name}*.pdf"))
            if pdf_files:
                pdf_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                pdf_path = str(pdf_files[0])
        
        if pdf_path and Path(pdf_path).exists():
            return {
                "success": True,
                "pdf_path": pdf_path,
                "pdf_filename": Path(pdf_path).name
            }
        
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown error"
            # Filter warnings (same as hitter report)
            lines = error_msg.split('\n')
            filtered_lines = [line for line in lines if line.strip() and 'urllib3' not in line and 'OpenSSL' not in line]
            filtered_error = '\n'.join(filtered_lines) if filtered_lines else "Report generation failed"
            
            return {
                "success": False,
                "error": f"Error generating report: {filtered_error[:800]}"
            }
        
        return {
            "success": False,
            "error": "Report generation completed but PDF file not found"
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Report generation timed out (over {Config.REPORT_TIMEOUT // 60} minutes)"
        }
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error generating pitcher report: {e}", exc_info=True)
        return {
            "success": False,
            "error": f"Error: {str(e)}"
        }


def generate_pitcher_report_background(
    pitcher_name: str,
    team: str = "AUTO",
    season_start: str = "2025-03-20",
    use_next_series: bool = False,
    opponent_team: Optional[str] = None,
    job_id: Optional[str] = None
) -> None:
    """Generate a single pitcher report in the background"""
    if job_id is None:
        job_id = str(uuid.uuid4())
    
    result = generate_single_pitcher_report(pitcher_name, team, season_start, use_next_series, opponent_team)
    
    if result["success"]:
        job_status[job_id] = {
            "status": "completed",
            "message": "Report generated successfully!",
            "pdf_path": result["pdf_path"],
            "pdf_filename": result["pdf_filename"]
        }
    else:
        job_status[job_id] = {
            "status": "error",
            "message": result.get("error", "Unknown error")
        }


def parse_pitcher_entry(entry: str) -> tuple:
    """Parse a pitcher entry that may include team and opponent."""
    parts = [p.strip() for p in entry.split('|')]
    pitcher_name = parts[0].strip() if parts else ""
    team = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    opponent = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
    return pitcher_name, team, opponent


def generate_batch_pitcher_reports(
    pitcher_entries: List[str],
    default_team: str,
    season_start: str,
    use_next_series: bool,
    default_opponent: Optional[str],
    job_id: str
) -> None:
    """Generate pitcher reports for multiple players with individual settings"""
    total = len(pitcher_entries)
    completed = 0
    failed = 0
    pdfs = []
    errors = []
    
    for i, entry in enumerate(pitcher_entries):
        pitcher_name, team, opponent = parse_pitcher_entry(entry)
        
        if not pitcher_name:
            failed += 1
            errors.append(f"Entry {i+1}: Invalid pitcher name")
            continue
        
        player_team = team if team else default_team
        player_opponent = opponent if opponent else default_opponent
        
        status_msg = f"Generating report {i+1} of {total}: {pitcher_name}"
        job_status[job_id] = {
            "status": "processing",
            "message": status_msg,
            "total": total,
            "completed": completed,
            "failed": failed,
            "current": i + 1
        }
        
        result = generate_single_pitcher_report(
            pitcher_name, player_team, season_start, use_next_series, player_opponent
        )
        
        if result["success"]:
            completed += 1
            pdfs.append({
                "pitcher": pitcher_name,
                "pdf_path": result["pdf_path"],
                "pdf_filename": result["pdf_filename"]
            })
        else:
            failed += 1
            errors.append(f"{pitcher_name}: {result.get('error', 'Unknown error')}")
    
    job_status[job_id] = {
        "status": "completed" if failed == 0 else "partial",
        "message": f"Completed {completed} of {total} reports" + (f" ({failed} failed)" if failed > 0 else ""),
        "total": total,
        "completed": completed,
        "failed": failed,
        "pdfs": pdfs,
        "errors": errors
    }


def maybe_trigger_report(
    game: Dict[str, Any],
    team_abbr: Optional[str],
    player_name: str,
    season_start: str
) -> None:
    """Maybe trigger automatic report generation for a game"""
    opponent_abbr = (game.get("opponent_abbr") or "").upper()
    opponent_label = game.get("opponent")
    if not opponent_abbr:
        return
    
    game_dt = extract_game_datetime(game)
    if not game_dt:
        return
    
    now = datetime.now(timezone.utc)
    days_out = (game_dt.date() - now.date()).days
    if days_out < 0 or days_out > REPORT_LEAD_DAYS:
        return
    
    if report_exists_for_player(player_name, opponent_abbr, opponent_label):
        return
    
    key = "|".join([
        player_name.lower(),
        opponent_abbr,
        str(game.get("game_pk") or game.get("game_date_iso") or game_dt.date().isoformat())
    ])
    
    with _pending_report_lock:
        if key in _pending_report_keys:
            return
        _pending_report_keys.add(key)
    
    def _worker():
        try:
            filename = f"{sanitize_filename_component(player_name).replace(' ', '_')}_vs_{opponent_abbr}.pdf"
            generate_single_report(
                hitter_name=player_name,
                team=team_abbr or "AUTO",
                season_start=season_start,
                use_next_series=False,
                opponent_team=opponent_abbr,
                pdf_name=filename
            )
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Auto-generation failed for {player_name} vs {opponent_abbr}: {exc}")
        finally:
            with _pending_report_lock:
                _pending_report_keys.discard(key)
    
    thread = threading.Thread(target=_worker, name=f"report-auto-{opponent_abbr}-{game.get('game_pk')}", daemon=True)
    thread.start()


def get_job_status(job_id: str) -> Dict[str, Any]:
    """Get job status by ID"""
    if job_id not in job_status:
        return {"status": "not_found"}
    return job_status[job_id].copy()

