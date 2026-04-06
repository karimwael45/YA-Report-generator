# Running YA Report Generator Locally

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the Application
```bash
python app.py
```

The app will:
- Start on http://127.0.0.1:5050
- Automatically open your browser
- No authentication required locally

### 3. Access the App
Open your browser and go to:
```
http://127.0.0.1:5050
```

## Troubleshooting

### Port Already in Use
If port 5050 is busy, edit `app.py` line 850:
```python
app.run(host='127.0.0.1', port=5051, debug=False, use_reloader=False)
```

### Missing Dependencies
```bash
pip install flask reportlab gunicorn
```

### Test Routes
Visit http://127.0.0.1:5050/debug/routes to see all available routes

## Features
- ✅ Upload CSV files (student data, grades, attendance)
- ✅ Generate full reports
- ✅ Generate quiz/mock reports
- ✅ Download single PDFs
- ✅ Download batch ZIPs
- ✅ WhatsApp sharing
