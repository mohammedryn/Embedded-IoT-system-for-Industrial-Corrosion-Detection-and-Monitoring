# Quick Analyze Setup - Raspberry Pi

## Step 1: Get Your Gemini API Key

1. Go to https://ai.google.dev (Google AI Studio)
2. Click **"Get API Key"**
3. Create a new project or use existing
4. Copy your API key (looks like: `AIzaSy...`)

## Step 2: Install Dependencies on Pi

```bash
# Update pip
pip install --upgrade pip==25.0.1

# Install hash-locked requirements
pip install --require-hashes -r requirements.lock
```

## Step 3: Set Up API Key for Your Session

Copy and paste ONE of these into your Pi terminal:

### Option A: Single Command (temporary, expires when terminal closes)
```bash
export GOOGLE_API_KEY='paste-your-key-here'
```

### Option B: Permanent (added to shell startup)
```bash
echo "export GOOGLE_API_KEY='paste-your-key-here'" >> ~/.bashrc
source ~/.bashrc
```

## Step 4: Test Your Camera (if on Raspberry Pi)

```bash
# Detect camera(s)
rpicam-hello --list-cameras

# Open camera preview/test (Ctrl+C to stop)
rpicam-hello -t 0

# Or if that doesn't work:
raspistill -o test.jpg
```

If neither works:
```bash
sudo raspi-config nonint do_camera 0  # Enable camera
sudo reboot
```

## Step 5: Run Analysis

### Simple - Capture & Analyze Now
```bash
python vision/quick_analyze.py
```

### Analyze Existing Image
```bash
python vision/quick_analyze.py --file my_image.jpg
```

### Save Results as JSON
```bash
python vision/quick_analyze.py --output results.json
```

### See Full JSON Output
```bash
python vision/quick_analyze.py --verbose
```

## Step 6: What You'll Get

**Text output will show:**
```
GEMINI ANALYSIS RESULTS
==============================================================

📝 Summary:
   Surface shows moderate rust with pitting damage

🔧 Rust Coverage: MODERATE
   Surface: pitted

📊 Severity: ███████░░░ 7.2/10
   Confidence: 87%

🔎 Key Findings:
   • Active corrosion in multiple areas
   • Surface pitting pattern indicates accelerated deterioration
   • Light scale formation visible

💡 Recommendations:
   • Apply rust converter within 48 hours
   • Consider protective coating after treatment
   • Monitor pitting depth with ultrasonic thickness gauge
```

**Plus JSON file (if --output used):**
```json
{
  "text_summary": "Surface shows moderate rust with pitting...",
  "rust_coverage_estimate": "moderate",
  "surface_condition": "pitted",
  "severity_0_to_10": 7.2,
  "confidence_0_to_1": 0.87,
  "key_findings": [...],
  "recommendations": [...]
}
```

## Troubleshooting

### "GOOGLE_API_KEY not provided"
```bash
# Make sure you set the key first
export GOOGLE_API_KEY='your-actual-key'

# Verify it's set
echo $GOOGLE_API_KEY
```

### Camera Shows Black/No Image
```bash
# Check if camera is enabled
sudo raspi-config nonint get_camera
# Should return 0 if enabled

# Check camera connectivity
rpicam-hello --list-cameras
```

### Gemini Returns "Invalid API Key"
- Verify key is copied correctly
- Check key isn't shared in version control
- Create a new key in Google AI Studio

### "rpicam-still: command not found"
```bash
sudo apt update
sudo apt install -y rpicam-apps
```

### Image Analysis Fails / Timeout
- Check internet connection: `ping 8.8.8.8`
- Gemini API may be rate-limited - wait a few seconds
- Try with a smaller image file: `python vision/quick_analyze.py --file test.jpg`

## Run from Anywhere

You can make it runnable from any directory by adding alias:

```bash
echo "alias analyze='python ~/corrosion/vision/quick_analyze.py'" >> ~/.bashrc
source ~/.bashrc

# Then from anywhere:
analyze
analyze --file my_image.jpg
```

## Next Steps

Once working, you can:
- Integrate with a cron job to analyze periodically
- Add to a web dashboard
- Stream results to a database
- Set up alerts on severity thresholds

Questions? Check your camera setup first with `rpicam-hello --list-cameras`
