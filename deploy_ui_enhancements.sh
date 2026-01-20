#!/bin/bash

# UI Enhancements Deployment Script
# Express Truck Lube
# Version: 1.0

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║     UI Enhancements Deployment - Express Truck Lube          ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Step 1: Check if we're in the right directory
echo -e "${BLUE}[1/5]${NC} Checking working directory..."
if [ ! -f "manage.py" ]; then
    echo -e "${RED}Error: manage.py not found. Please run this script from the Django project root.${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} Django project found"
echo ""

# Step 2: Verify new files exist
echo -e "${BLUE}[2/5]${NC} Verifying new files..."
files=(
    "static/css/responsive_enhancements.css"
    "static/js/ui_enhancements.js"
)

missing_files=0
for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        echo -e "${GREEN}✓${NC} Found: $file"
    else
        echo -e "${RED}✗${NC} Missing: $file"
        missing_files=$((missing_files + 1))
    fi
done

if [ $missing_files -gt 0 ]; then
    echo -e "${RED}Error: $missing_files file(s) missing. Please ensure all files are in place.${NC}"
    exit 1
fi
echo ""

# Step 3: Collect static files
echo -e "${BLUE}[3/5]${NC} Collecting static files..."
python manage.py collectstatic --noinput --clear
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Static files collected successfully"
else
    echo -e "${RED}✗${NC} Failed to collect static files"
    exit 1
fi
echo ""

# Step 4: Check for template updates
echo -e "${BLUE}[4/5]${NC} Verifying template updates..."
template_count=$(grep -rl "responsive_enhancements.css" templates/public*.html templates/public/ 2>/dev/null | wc -l)
echo -e "${GREEN}✓${NC} Found $template_count templates with enhancements"
echo ""

# Step 5: Run development server (optional)
echo -e "${BLUE}[5/5]${NC} Deployment checks complete!"
echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                   DEPLOYMENT OPTIONS                       ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""
echo "Choose an option:"
echo "  1) Start development server"
echo "  2) Run tests"
echo "  3) Exit"
echo ""
read -p "Enter your choice (1-3): " choice

case $choice in
    1)
        echo ""
        echo -e "${GREEN}Starting development server...${NC}"
        echo "Visit: http://localhost:8000/"
        echo "Press Ctrl+C to stop"
        echo ""
        python manage.py runserver
        ;;
    2)
        echo ""
        echo -e "${YELLOW}Running tests...${NC}"
        python manage.py test
        ;;
    3)
        echo ""
        echo -e "${GREEN}Deployment preparation complete!${NC}"
        echo ""
        echo "Next steps:"
        echo "  1. Test locally: python manage.py runserver"
        echo "  2. Review: http://localhost:8000/"
        echo "  3. Read: TESTING_GUIDE.md"
        echo "  4. Deploy to production"
        echo ""
        ;;
    *)
        echo ""
        echo -e "${RED}Invalid choice${NC}"
        exit 1
        ;;
esac

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                     DOCUMENTATION                          ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""
echo "📚 Available documentation:"
echo "  • README_UI_ENHANCEMENTS.md   - Project overview"
echo "  • QUICK_REFERENCE.md          - Quick reference"
echo "  • TESTING_GUIDE.md            - Testing checklist"
echo "  • VISUAL_IMPROVEMENTS_GUIDE.md - Visual guide"
echo "  • FILES_UPDATED.txt           - Files summary"
echo ""
echo -e "${GREEN}✨ UI Enhancements are ready! ✨${NC}"
echo ""