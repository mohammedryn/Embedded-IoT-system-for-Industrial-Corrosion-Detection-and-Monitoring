#!/bin/bash
# Copy-paste this entire script block into your Raspberry Pi terminal
# It sets everything up in one go

PI_USER=${1:-$USER}

echo "🔧 Setting up Quick Analyze for Gemini Vision..."
echo ""
echo "REQUIRED: You need your Gemini API key first"
echo "Get it from: https://ai.google.dev"
echo ""
echo "Your key will look like: AIzaSy... (about 40 characters)"
echo ""
read -p "Paste your Gemini API key here: " GEMINI_KEY

if [ -z "$GEMINI_KEY" ]; then
    echo "❌ No API key provided. Exiting."
    exit 1
fi

# Check if in corrosion directory
if [ ! -f "requirements.in" ]; then
    echo "❌ Not in corrosion directory. Run from: ~/corrosion"
    exit 1
fi

# Update and install
echo "📦 Installing Python packages..."
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.in > /dev/null 2>&1

# Add to bashrc
echo ""
echo "🔑 Adding API key to ~/.bashrc..."
if grep -q "GOOGLE_API_KEY" ~/.bashrc; then
    echo "   API key already in ~/.bashrc"
else
    echo "export GOOGLE_API_KEY='${GEMINI_KEY}'" >> ~/.bashrc
    echo "   ✓ Added to ~/.bashrc"
fi

# Source bashrc
export GOOGLE_API_KEY="${GEMINI_KEY}"
source ~/.bashrc

# Test Python import
echo ""
echo "🧪 Testing Gemini client..."
python3 << 'EOF'
try:
    from vision.gemini_client import GeminiVisionClient
    import os
    key = os.getenv("GOOGLE_API_KEY")
    if key:
        print("   ✓ Gemini client ready")
        print(f"   ✓ API key loaded (length: {len(key)})")
    else:
        print("   ❌ API key not found in environment")
        exit(1)
except Exception as e:
    print(f"   ❌ Import failed: {e}")
    exit(1)
EOF

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Setup complete!"
    echo ""
    echo "Next steps:"
    echo "  1. Make sure camera is enabled:"
    echo "     rpicam-hello --list-cameras"
    echo "     rpicam-hello -t 0"
    echo ""
    echo "  2. Test the analysis:"
    echo "     python vision/quick_analyze.py"
    echo ""
    echo "  3. Analyze an existing image:"
    echo "     python vision/quick_analyze.py --file your_image.jpg"
    echo ""
else
    echo ""
    echo "❌ Setup failed. Check error messages above."
    exit 1
fi
