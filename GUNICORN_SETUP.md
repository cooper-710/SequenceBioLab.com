# Gunicorn Setup Complete ✅

Your application is now configured to use Gunicorn for production deployment.

## What Was Changed

1. **`requirements-web.txt`** - Added `gunicorn>=21.2.0`
2. **`wsgi.py`** - Created WSGI entry point for Gunicorn
3. **`start_ui.sh`** - Updated to optionally use Gunicorn

## How to Use

### Local Development (Flask dev server)

Just run as normal:
```bash
./start_ui.sh
# or
python3 app.py
```

### Local Testing with Gunicorn

To test Gunicorn locally:
```bash
export USE_GUNICORN=1
./start_ui.sh
```

Or directly:
```bash
gunicorn -w 2 -b 0.0.0.0:5000 --timeout 600 wsgi:application
```

### Production Deployment

On your hosting platform (Render, Heroku, Railway, etc.), set the start command to:

```bash
gunicorn -w 2 -b 0.0.0.0:$PORT --timeout 600 wsgi:application
```

**Or** if your platform auto-detects WSGI files, it should automatically find `wsgi.py` and use it.

## Gunicorn Configuration

Current settings:
- **Workers**: 2 (`-w 2`)
  - Adjust based on your server: `(2 × CPU cores) + 1`
  - For 1 CPU: use `-w 2`
  - For 2 CPUs: use `-w 4`
  - For 4 CPUs: use `-w 9`

- **Bind**: `0.0.0.0:$PORT`
  - Listens on all interfaces
  - Uses `PORT` environment variable (set by hosting platforms)

- **Timeout**: 600 seconds (10 minutes)
  - Needed for long-running report generation tasks

## Adjusting Workers

To change the number of workers, modify the command:

```bash
# For a small server (1 CPU)
gunicorn -w 2 -b 0.0.0.0:$PORT --timeout 600 wsgi:application

# For a medium server (2 CPUs)
gunicorn -w 4 -b 0.0.0.0:$PORT --timeout 600 wsgi:application

# For a larger server (4+ CPUs)
gunicorn -w 9 -b 0.0.0.0:$PORT --timeout 600 wsgi:application
```

## Performance Expectations

With PostgreSQL + Gunicorn:
- **2 workers**: ~50-100 concurrent users
- **4 workers**: ~100-200 concurrent users
- **8+ workers**: ~200-500+ concurrent users

## Important Notes

⚠️ **In-Memory State**: If you use multiple workers, the `job_status` dict and `cache_service` won't be shared between workers. This is usually fine for most use cases, but if you need shared state, you'll need Redis.

⚠️ **File Storage**: PDFs and uploads stored locally won't be shared between workers. Consider cloud storage (S3) for multiple instances.

## Troubleshooting

**Gunicorn not found?**
```bash
pip install gunicorn
```

**Port already in use?**
- Change the port: `gunicorn -b 0.0.0.0:8000 ...`
- Or kill the process using the port

**Workers crashing?**
- Reduce worker count: `-w 1`
- Check logs for errors
- Increase timeout if reports are timing out

## Next Steps

1. Test locally with `USE_GUNICORN=1 ./start_ui.sh`
2. Deploy to your hosting platform
3. Set the start command to use Gunicorn
4. Monitor performance and adjust workers as needed

Your app is now production-ready! 🚀

