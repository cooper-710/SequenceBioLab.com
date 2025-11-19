"""
Report routes
"""
import os
import threading
from pathlib import Path
from flask import Blueprint, request, jsonify, send_file, redirect, url_for, flash
from datetime import datetime
from app.config import Config
from app.utils.helpers import clean_str, parse_bool
from app.middleware.auth import login_required
from app.services.report_service import (
    generate_report_background,
    generate_pitcher_report_background,
    parse_player_entry,
    parse_pitcher_entry,
    generate_batch_reports,
    generate_batch_pitcher_reports,
    job_status
)

bp = Blueprint('reports', __name__)


@bp.route('/generate', methods=['POST'])
def generate():
    """Start report generation (supports single or batch)"""
    try:
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 400
        
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "Invalid JSON in request"}), 400
        
        # Support both old 'hitter_name' and new 'hitter_names' for backward compatibility
        hitter_names_raw = data.get('hitter_names') or data.get('hitter_name')
        hitter_names_str = (hitter_names_raw or '').strip()
        
        if not hitter_names_str:
            return jsonify({"error": "Player name(s) are required"}), 400
        
        # Parse entries - split by newlines or commas
        # Each entry can be just a name or "Name | Team | Opponent"
        entries = [entry.strip() for entry in hitter_names_str.replace(',', '\n').split('\n') if entry.strip()]
        
        if not entries:
            return jsonify({"error": "Please enter at least one player name"}), 400
        
        # Generate a unique job ID
        import uuid
        job_id = str(uuid.uuid4())
        
        # Get default parameters (used if not specified per-player)
        settings = Config.get_settings()
        report_defaults = settings.get("reports", {})

        default_team = clean_str(data.get('team')) or clean_str(report_defaults.get('default_team')) or 'AUTO'
        season_start = clean_str(data.get('season_start')) or clean_str(report_defaults.get('default_season_start')) or '2025-03-20'
        use_next_series = parse_bool(data.get('use_next_series'), report_defaults.get('use_next_series', False))
        opponent_team_raw = data.get('opponent_team')
        default_opponent = clean_str(opponent_team_raw) or clean_str(report_defaults.get('default_opponent')) or None
        
        # Determine if this is a batch or single report
        is_batch = len(entries) > 1
        
        if is_batch:
            # Initialize batch job status
            job_status[job_id] = {
                "status": "queued",
                "message": f"Queued batch of {len(entries)} players...",
                "total": len(entries),
                "completed": 0,
                "failed": 0,
                "pdfs": [],
                "errors": []
            }
            
            # Start background thread for batch processing
            thread = threading.Thread(
                target=generate_batch_reports,
                args=(entries, default_team, season_start, use_next_series, default_opponent, job_id)
            )
        else:
            # Single report (backward compatible)
            # Parse the entry in case it has team/opponent specified
            hitter_name, team, opponent = parse_player_entry(entries[0])
            if not hitter_name:
                return jsonify({"error": "Invalid player name format"}), 400
            
            player_team = team if team else default_team
            player_opponent = opponent if opponent else default_opponent
            
            job_status[job_id] = {"status": "queued", "message": "Queued for processing..."}
            
            # Start background thread
            thread = threading.Thread(
                target=generate_report_background,
                args=(hitter_name, player_team, season_start, use_next_series, player_opponent, job_id)
            )
        
        thread.daemon = True
        thread.start()
        
        return jsonify({
            "job_id": job_id,
            "is_batch": is_batch,
            "total": len(entries) if is_batch else 1
        })
    except Exception as e:
        import traceback
        error_msg = str(e)
        traceback.print_exc()
        return jsonify({"error": f"Server error: {error_msg}"}), 500


@bp.route('/generate-pitcher', methods=['POST'])
def generate_pitcher():
    """Start pitcher report generation (supports single or batch)"""
    try:
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 400
        
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "Invalid JSON in request"}), 400
        
        # Get pitcher names
        pitcher_names_raw = data.get('pitcher_names') or data.get('pitcher_name')
        pitcher_names_str = (pitcher_names_raw or '').strip()
        
        if not pitcher_names_str:
            return jsonify({"error": "Pitcher name(s) are required"}), 400
        
        # Parse entries - split by newlines or commas
        # Each entry can be just a name or "Name | Team | Opponent"
        entries = [entry.strip() for entry in pitcher_names_str.replace(',', '\n').split('\n') if entry.strip()]
        
        if not entries:
            return jsonify({"error": "Please enter at least one pitcher name"}), 400
        
        # Generate a unique job ID
        import uuid
        job_id = str(uuid.uuid4())
        
        # Get default parameters (used if not specified per-player)
        settings = Config.get_settings()
        report_defaults = settings.get("reports", {})

        default_team = clean_str(data.get('team')) or clean_str(report_defaults.get('default_pitcher_team')) or clean_str(report_defaults.get('default_team')) or 'AUTO'
        season_start = clean_str(data.get('season_start')) or clean_str(report_defaults.get('default_season_start')) or '2025-03-20'
        use_next_series = parse_bool(data.get('use_next_series'), report_defaults.get('use_next_series', False))
        opponent_team_raw = data.get('opponent_team')
        default_opponent = clean_str(opponent_team_raw) or clean_str(report_defaults.get('default_opponent')) or None
        
        # Determine if this is a batch or single report
        is_batch = len(entries) > 1
        
        if is_batch:
            # Initialize batch job status
            job_status[job_id] = {
                "status": "queued",
                "message": f"Queued batch of {len(entries)} pitchers...",
                "total": len(entries),
                "completed": 0,
                "failed": 0,
                "pdfs": [],
                "errors": []
            }
            
            # Start background thread for batch processing
            thread = threading.Thread(
                target=generate_batch_pitcher_reports,
                args=(entries, default_team, season_start, use_next_series, default_opponent, job_id)
            )
        else:
            # Single report
            # Parse the entry in case it has team/opponent specified
            pitcher_name, team, opponent = parse_pitcher_entry(entries[0])
            if not pitcher_name:
                return jsonify({"error": "Invalid pitcher name format"}), 400
            
            player_team = team if team else default_team
            player_opponent = opponent if opponent else default_opponent
            
            job_status[job_id] = {"status": "queued", "message": "Queued for processing..."}
            
            # Start background thread
            thread = threading.Thread(
                target=generate_pitcher_report_background,
                args=(pitcher_name, player_team, season_start, use_next_series, player_opponent, job_id)
            )
        
        thread.daemon = True
        thread.start()
        
        return jsonify({
            "job_id": job_id,
            "is_batch": is_batch,
            "total": len(entries) if is_batch else 1
        })
    except Exception as e:
        import traceback
        error_msg = str(e)
        traceback.print_exc()
        return jsonify({"error": f"Error generating pitcher report: {error_msg}"}), 500


@bp.route('/status/<job_id>')
def status(job_id):
    """Check the status of a job"""
    if job_id not in job_status:
        return jsonify({"error": "Job not found"}), 404
    
    status_info = job_status[job_id].copy()
    
    # Clean up old completed/error jobs (keep last 10)
    if status_info.get("status") in ["completed", "error"]:
        completed_jobs = [jid for jid, info in job_status.items() 
                         if info.get("status") in ["completed", "error"]]
        if len(completed_jobs) > 10:
            oldest = completed_jobs[0]
            if oldest != job_id:
                del job_status[oldest]
    
    return jsonify(status_info)


@bp.route('/download/<job_id>')
def download(job_id):
    """Download the generated PDF (for single reports)"""
    if job_id not in job_status:
        return jsonify({"error": "Job not found"}), 404
    
    status_info = job_status[job_id]
    
    if status_info.get("status") != "completed":
        return jsonify({"error": "Report not ready yet"}), 400
    
    pdf_path = status_info.get("pdf_path")
    if not pdf_path or not Path(pdf_path).exists():
        return jsonify({"error": "PDF file not found"}), 404
    
    return send_file(
        pdf_path,
        as_attachment=True,
        download_name=status_info.get("pdf_filename", "report.pdf")
    )


@bp.route('/download/<job_id>/<int:pdf_index>')
def download_batch_pdf(job_id, pdf_index):
    """Download a specific PDF from a batch"""
    if job_id not in job_status:
        return jsonify({"error": "Job not found"}), 404
    
    status_info = job_status[job_id]
    
    if status_info.get("status") != "completed":
        return jsonify({"error": "Batch not ready yet"}), 400
    
    pdfs = status_info.get("pdfs", [])
    if pdf_index < 0 or pdf_index >= len(pdfs):
        return jsonify({"error": "Invalid PDF index"}), 404
    
    pdf_info = pdfs[pdf_index]
    pdf_path = pdf_info.get("path")
    
    if not pdf_path or not Path(pdf_path).exists():
        return jsonify({"error": "PDF file not found"}), 404
    
    return send_file(
        pdf_path,
        as_attachment=True,
        download_name=pdf_info.get("filename", "report.pdf")
    )


@bp.route('/reports/files/<path:filename>')
@login_required
def download_report_file(filename):
    """Provide direct download access for generated reports."""
    safe_name = os.path.basename(filename)
    pdf_path = Config.PDF_OUTPUT_DIR / safe_name
    if not pdf_path.exists() or not pdf_path.is_file():
        flash("Report not found.", "error")
        # Redirect to gameday route
        return redirect(url_for('pages.gameday'))
    return send_file(pdf_path, as_attachment=True, download_name=safe_name)


@bp.route('/reports')
def list_reports():
    """List all available reports"""
    pdf_files = sorted(Config.PDF_OUTPUT_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    reports = [
        {
            "name": pdf.name,
            "size": pdf.stat().st_size,
            "created": datetime.fromtimestamp(pdf.stat().st_mtime).isoformat()
        }
        for pdf in pdf_files[:20]  # Last 20 reports
    ]
    return jsonify({"reports": reports})
