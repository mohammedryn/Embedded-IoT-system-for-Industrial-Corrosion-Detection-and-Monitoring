#!/bin/bash
# Unified fusion analyzer - captures image + generates sensor data + analyzes both with Gemini

cd ~/Embedded-IoT-system-for-Industrial-Corrosion-Detection-and-Monitoring
source .venv/bin/activate

# Set your Gemini API key (replace with your actual key)
export GOOGLE_API_KEY='YOUR_GEMINI_KEY_HERE'
export GEMINI_MODEL_ID='gemini-3-flash-preview'
export GEMINI_FALLBACK_MODEL_ID='gemini-3.1-pro-preview'

# Run fusion analyzer
python -m edge.quick_fusion_analyze --output data/sessions/c07/fusion-analysis.json --verbose

# Show results
echo ""
echo "Results saved to data/sessions/c07/fusion-analysis.json"
cat data/sessions/c07/fusion-analysis.json
