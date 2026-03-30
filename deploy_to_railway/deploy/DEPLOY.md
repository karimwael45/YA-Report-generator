# Deployment Guide — IGCSE Math Report Generator

## Deploy to Railway (Free, ~10 minutes)

### Step 1 — Create a GitHub repo

```bash
cd path/to/this/folder
git init
git add .
git commit -m "Initial deploy"
```

Go to https://github.com/new → create a **private** repo called `igcse-report-generator`

```bash
git remote add origin https://github.com/YOUR_USERNAME/igcse-report-generator.git
git branch -M main
git push -u origin main
```

---

### Step 2 — Deploy on Railway

1. Go to https://railway.app and sign up with GitHub (free)
2. Click **"New Project"** → **"Deploy from GitHub repo"**
3. Select `igcse-report-generator`
4. Railway auto-detects Python and deploys — takes ~2 minutes

---

### Step 3 — Set environment variables

In Railway dashboard → your project → **Variables** tab, add:

| Variable | Value | Notes |
|---|---|---|
| `SECRET_KEY` | any long random string | e.g. `xK9#mP2$qL8nR5vT` |
| `APP_USER` | `igcse` | login username |
| `APP_PASS` | choose a strong password | login password |
| `PORT` | (leave blank — Railway sets this automatically) | |

**Important:** Change `APP_PASS` to something strong. This protects your students' data.

---

### Step 4 — Get your URL

Railway gives you a URL like:
```
https://igcse-report-generator-production.up.railway.app
```

Share this with your team. They'll be prompted for the username/password you set.

---

## Environment Variables Reference

| Variable | Default (if not set) | Description |
|---|---|---|
| `SECRET_KEY` | `igcse-math-reports-v2-change-in-prod` | Flask session secret — always override this |
| `APP_USER` | `igcse` | HTTP Basic Auth username |
| `APP_PASS` | `math2025` | HTTP Basic Auth password — **always override** |
| `PORT` | `5050` | Set automatically by Railway |
| `FLASK_DEBUG` | `false` | Never set to `true` in production |

---

## Free Tier Limits (Railway)

- **500 hours/month** free (enough for ~16h/day usage)
- **1 GB RAM**, **1 vCPU**
- App sleeps after inactivity — first load after sleep takes ~5 seconds
- No credit card required for free tier

---

## Updating the App

```bash
# Make your changes locally, then:
git add .
git commit -m "Update: describe what changed"
git push
```

Railway auto-redeploys in ~1 minute.

---

## Alternative: Render.com (also free)

If Railway doesn't work for you:

1. Go to https://render.com → New → Web Service
2. Connect GitHub repo
3. Set:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
4. Add the same environment variables
5. Free tier at Render spins down after 15min inactivity (cold start ~30s)

---

## Running Locally (for development)

```bash
pip install -r requirements.txt
export APP_USER=igcse
export APP_PASS=yourpassword
python app.py
# Open http://127.0.0.1:5050
```

On Windows:
```cmd
set APP_USER=igcse
set APP_PASS=yourpassword
python app.py
```
