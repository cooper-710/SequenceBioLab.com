# Deploying SequenceBioLab to Render

This guide provides step-by-step instructions for deploying your Flask application to Render.

## Prerequisites

Before you begin, make sure you have:
1. ✅ A GitHub account
2. ✅ Your code pushed to a GitHub repository
3. ✅ All files committed (including `Procfile`, `requirements.txt`, `wsgi.py`)

## Quick Overview

Your app is **production-ready** with:
- ✅ Gunicorn WSGI server configured
- ✅ PostgreSQL database support
- ✅ Environment variable configuration
- ✅ Static file serving setup

**Estimated time**: 15-20 minutes

---

## Step 1: Prepare Your Code Repository

### 1.1 Verify Required Files

Make sure these files exist in your repository:
- ✅ `Procfile` - Contains the start command
- ✅ `requirements.txt` - Python dependencies
- ✅ `wsgi.py` - WSGI entry point
- ✅ `render.yaml` - Render configuration (optional but helpful)

All of these files should already be in your repository.

### 1.2 Generate a Secret Key

You'll need a secret key for Flask sessions. Run this command locally:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

**Copy the output** - you'll need it in Step 4.

Example output: `a1b2c3d4e5f6...` (64 characters)

### 1.3 Push to GitHub

Make sure all your changes are committed and pushed:

```bash
git add .
git commit -m "Prepare for Render deployment"
git push origin main
```

---

## Step 2: Create Render Account

1. Go to [render.com](https://render.com)
2. Click **"Get Started for Free"** or **"Sign Up"**
3. Sign up with your GitHub account (recommended) or email
4. Verify your email if required

---

## Step 3: Create PostgreSQL Database

### 3.1 Create Database Service

1. In your Render dashboard, click the **"New +"** button (top right)
2. Select **"PostgreSQL"** from the dropdown

### 3.2 Configure Database

Fill in the form:

- **Name**: `sequencebiolab-db` (or any name you prefer)
- **Database**: `sequencebiolab` (or leave default)
- **User**: `sequencebiolab_user` (or leave default)
- **Region**: Choose the region closest to you (e.g., `Oregon (US West)` for US)
- **PostgreSQL Version**: Leave default (latest)
- **Plan**: 
  - **Free**: For testing (90 days, then $7/month)
  - **Starter**: $7/month (recommended for production)

### 3.3 Create and Copy Connection String

1. Click **"Create Database"**
2. Wait 1-2 minutes for the database to be created
3. Once created, click on your database service
4. Find the **"Connections"** section
5. Copy the **"Internal Database URL"** - it looks like:
   ```
   postgresql://sequencebiolab_user:password@dpg-xxxxx-a/sequencebiolab
   ```
   
   ⚠️ **Important**: Copy the **Internal Database URL**, not the External one (for security)

**Save this URL** - you'll need it in the next step.

---

## Step 4: Create Web Service

### 4.1 Create New Web Service

1. In your Render dashboard, click **"New +"** button
2. Select **"Web Service"**

### 4.2 Connect Repository

1. Click **"Connect account"** if you haven't connected GitHub yet
2. Authorize Render to access your repositories
3. Find and select your repository from the list
4. Click **"Connect"**

### 4.3 Configure Service Settings

Fill in the configuration form:

#### Basic Settings

- **Name**: `sequencebiolab` (or your preferred name)
- **Region**: Same region as your database (recommended)
- **Branch**: `main` (or your default branch)
- **Root Directory**: Leave empty (unless your app is in a subdirectory)
- **Runtime**: `Python 3`
- **Build Command**: 
  ```
  pip install -r requirements.txt
  ```
- **Start Command**: 
  ```
  gunicorn -w 2 -b 0.0.0.0:$PORT --timeout 600 wsgi:application
  ```
- **Plan**: 
  - **Free**: Spins down after 15 min inactivity (good for testing)
  - **Starter ($7/month)**: Always on (recommended for production)

#### Environment Variables

Click **"Advanced"** to expand environment variables, then add:

1. **DATABASE_URL**
   - Key: `DATABASE_URL`
   - Value: Paste the Internal Database URL you copied in Step 3.3
   - Click **"Add"**

2. **SECRET_KEY**
   - Key: `SECRET_KEY`
   - Value: Paste the secret key you generated in Step 1.2
   - Click **"Add"**

3. **FLASK_ENV**
   - Key: `FLASK_ENV`
   - Value: `production`
   - Click **"Add"**

4. **DEFAULT_ADMIN_PASSWORD** (Optional but recommended)
   - Key: `DEFAULT_ADMIN_PASSWORD`
   - Value: Choose a strong password (not the default `1234`)
   - Click **"Add"**

5. **CONTACT_EMAIL** (Optional)
   - Key: `CONTACT_EMAIL`
   - Value: Your email address
   - Click **"Add"**

### 4.4 Create Service

1. Review all settings
2. Click **"Create Web Service"** at the bottom
3. Render will start building your application (this takes 5-10 minutes)

---

## Step 5: Monitor Deployment

### 5.1 Watch the Build Logs

1. You'll see the build logs in real-time
2. Look for:
   - ✅ "Installing dependencies..."
   - ✅ "Build successful"
   - ✅ "Starting service..."

### 5.2 Common Build Issues

If the build fails, check:

- **Dependencies error**: Make sure `requirements.txt` has all packages
- **Python version**: Render uses Python 3.11 by default (you can specify in `runtime.txt`)
- **Build command**: Should be `pip install -r requirements.txt`

### 5.3 Wait for Deployment

- First deployment: 5-10 minutes
- Subsequent deployments: 2-5 minutes

You'll see a green checkmark when deployment is successful.

---

## Step 6: Verify Deployment

### 6.1 Access Your App

1. Once deployed, you'll see your app URL at the top (e.g., `https://sequencebiolab.onrender.com`)
2. Click the URL or copy it
3. Your app should load in the browser

### 6.2 Test Basic Functionality

1. **Homepage loads**: You should see your app's homepage
2. **Static files**: Check that CSS/images load correctly
3. **Database connection**: Try creating a user or logging in
4. **Admin access**: 
   - Default email: `admin@sequencebiolab.com`
   - Default password: `1234` (or what you set in `DEFAULT_ADMIN_PASSWORD`)

### 6.3 Check Logs

1. In Render dashboard, go to your web service
2. Click the **"Logs"** tab
3. Look for any errors (red text)
4. Common things to check:
   - Database connection successful
   - No import errors
   - Server started on correct port

---

## Step 7: Post-Deployment Configuration

### 7.1 Change Default Admin Password

⚠️ **Security**: Change the default admin password immediately!

1. Log in to your app with default credentials
2. Go to user settings/profile
3. Change the password to something secure

Or set `DEFAULT_ADMIN_PASSWORD` environment variable before first deployment.

### 7.2 Configure Custom Domain (Optional)

1. In your web service settings, go to **"Settings"** tab
2. Scroll to **"Custom Domains"**
3. Click **"Add Custom Domain"**
4. Enter your domain (e.g., `app.yourdomain.com`)
5. Follow Render's instructions to add DNS records
6. Render will automatically provision SSL certificate

### 7.3 Set Up Auto-Deploy

Auto-deploy is enabled by default. Every push to your `main` branch will trigger a new deployment.

To disable or change branch:
1. Go to **"Settings"** tab
2. Scroll to **"Auto-Deploy"**
3. Toggle or change branch as needed

---

## Important Notes

### File Storage Limitation

⚠️ **Critical**: Render's file system is **ephemeral** - files are deleted when the service restarts.

**What this means:**
- Generated PDFs in `build/pdf/` will be lost on restart
- User uploads in `static/uploads/` will be lost
- Cache files will be lost

**Solutions:**
1. **For now**: App will work, but files won't persist
2. **For production**: Consider migrating to:
   - AWS S3
   - Cloudinary
   - Render Disk (paid feature)

### Free Tier Limitations

- **Web Service**: Spins down after 15 minutes of inactivity (takes ~30 seconds to wake up)
- **Database**: Free for 90 days, then $7/month
- **Bandwidth**: Limited on free tier

**Recommendation**: Use Starter plan ($7/month) for production to avoid spin-down delays.

---

## Environment Variables Reference

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@host:5432/db` |
| `SECRET_KEY` | Flask session secret (64 char hex) | Generated with Python secrets module |
| `FLASK_ENV` | Environment mode | `production` |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DEFAULT_ADMIN_EMAIL` | Admin user email | `admin@sequencebiolab.com` |
| `DEFAULT_ADMIN_PASSWORD` | Admin password | `1234` (⚠️ change this!) |
| `CONTACT_EMAIL` | Contact email | `cooperrobinson@sequencebiolab.com` |
| `USE_MOCK_SCHEDULE` | Use mock MLB schedule | `0` (use real data) |
| `PORT` | Server port | Auto-set by Render |

### How to Update Environment Variables

1. Go to your web service in Render dashboard
2. Click **"Environment"** tab
3. Click **"Add Environment Variable"**
4. Enter key and value
5. Click **"Save Changes"**
6. Service will automatically redeploy

---

## Troubleshooting

### App Won't Start

**Symptoms**: Build succeeds but service shows "Unhealthy" or crashes

**Solutions**:
1. Check **Logs** tab for error messages
2. Verify `DATABASE_URL` is correct (Internal URL, not External)
3. Ensure `SECRET_KEY` is set
4. Check that `wsgi.py` exists and is correct
5. Verify start command: `gunicorn -w 2 -b 0.0.0.0:$PORT --timeout 600 wsgi:application`

### Database Connection Errors

**Symptoms**: Errors about "could not connect to server" or "connection refused"

**Solutions**:
1. Verify `DATABASE_URL` uses the **Internal Database URL** (not External)
2. Ensure database service is running (check database dashboard)
3. Check that database and web service are in the same region
4. Verify `psycopg2-binary` is in `requirements.txt`
5. Test connection locally: `python3 test_postgres_connection.py`

### Static Files Not Loading

**Symptoms**: CSS/images missing, broken layout

**Solutions**:
1. Verify `static/` directory is in your repository
2. Check file paths in templates (should be `/static/...`)
3. Clear browser cache
4. Check Render logs for 404 errors on static files

### Build Fails

**Symptoms**: Build shows red X, deployment doesn't complete

**Solutions**:
1. Check build logs for specific error
2. Verify `requirements.txt` has all dependencies
3. Ensure Python version is compatible (check `runtime.txt`)
4. Check for syntax errors in your code
5. Verify all files are committed to git

### Timeout Errors

**Symptoms**: Requests timeout, especially for report generation

**Solutions**:
1. Increase timeout in start command: `--timeout 1200` (20 minutes)
2. Check if reports are taking too long to generate
3. Consider background job processing (Celery, RQ)
4. Optimize database queries

### Service Spins Down (Free Tier)

**Symptoms**: First request after inactivity takes 30+ seconds

**Solutions**:
1. This is normal for free tier
2. Upgrade to Starter plan ($7/month) for always-on
3. Use a service like UptimeRobot to ping your app every 5 minutes (keeps it awake)

---

## Monitoring & Maintenance

### View Logs

1. Go to your web service
2. Click **"Logs"** tab
3. View real-time logs
4. Use search to filter logs

### Monitor Performance

1. Go to **"Metrics"** tab
2. View:
   - CPU usage
   - Memory usage
   - Request rate
   - Response times

### Set Up Alerts

1. Go to **"Alerts"** tab
2. Configure email alerts for:
   - Service down
   - High error rate
   - Resource limits

### Database Backups

Render automatically backs up PostgreSQL databases:
- **Free tier**: Manual backups only
- **Paid tiers**: Automatic daily backups

To create manual backup:
1. Go to your database service
2. Click **"Backups"** tab
3. Click **"Create Backup"**

---

## Security Checklist

Before going live, verify:

- [ ] `SECRET_KEY` is set and random (64 characters)
- [ ] `FLASK_ENV=production` is set
- [ ] `DEFAULT_ADMIN_PASSWORD` is changed from default
- [ ] Database uses Internal URL (not External)
- [ ] HTTPS/SSL is enabled (automatic on Render)
- [ ] No sensitive data in git repository
- [ ] Environment variables are set in Render (not hardcoded)
- [ ] File uploads are validated (already in your app)
- [ ] CSRF protection enabled (already in your app)

---

## Cost Estimate

### Free Tier (Testing)
- Web Service: **Free** (spins down after inactivity)
- PostgreSQL: **Free** (90 days, then $7/month)
- **Total**: Free for 90 days, then $7/month

### Starter Plan (Production Recommended)
- Web Service: **$7/month** (always on)
- PostgreSQL: **$7/month** (always on)
- **Total**: **$14/month**

### Scaling Up
- More resources: $25-100/month depending on needs
- Render Disk (persistent storage): $0.25/GB/month

---

## Next Steps

After successful deployment:

1. ✅ Test all functionality
2. ✅ Change default admin password
3. ✅ Set up monitoring/alerts
4. ✅ Configure custom domain (optional)
5. ✅ Set up database backups
6. ✅ Plan for file storage migration (S3, etc.)
7. ✅ Share your app URL with users!

---

## Getting Help

### Render Support
- Documentation: [render.com/docs](https://render.com/docs)
- Community: [community.render.com](https://community.render.com)
- Support: Available in dashboard

### Application Issues
- Check application logs in Render dashboard
- Test locally with production environment variables
- Review error messages in logs

---

## Quick Reference

### Render Dashboard URLs
- Dashboard: [dashboard.render.com](https://dashboard.render.com)
- Your Services: Dashboard → Services
- Logs: Service → Logs tab
- Environment: Service → Environment tab
- Settings: Service → Settings tab

### Important Commands
```bash
# Generate secret key
python3 -c "import secrets; print(secrets.token_hex(32))"

# Test database connection locally
export DATABASE_URL="your-database-url"
python3 test_postgres_connection.py

# Check local requirements
pip install -r requirements.txt
```

---

**Congratulations!** Your app should now be live on Render! 🚀

If you encounter any issues, refer to the Troubleshooting section above or check Render's documentation.
