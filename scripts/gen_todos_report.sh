PROJECT_ROOT="$(git rev-parse --show-toplevel)"
CURRENT_VERSION_OR_TAG="$(git describe --tags --abbrev=0)"
if [ -z "$CURRENT_VERSION_OR_TAG" ]; then
    CURRENT_VERSION_OR_TAG="$(git rev-parse --short HEAD)"
fi

REPORT="$PROJECT_ROOT/todos_report_for_${CURRENT_VERSION_OR_TAG}.md"

# Find all 2-do comments in the codebase
echo "# TO-DOs Report for version $CURRENT_VERSION_OR_TAG" > "$REPORT"

echo "## List of TO-DOs" >> "$REPORT"
echo "" >> "$REPORT"
git grep -n "TODO" -- '*.py' '*.sh' '*.md' | while read -r line; do
    FILE_PATH=$(echo "$line" | cut -d: -f1)
    LINE_NUMBER=$(echo "$line" | cut -d: -f2)
    TEXT=$(echo "$line" | cut -d: -f3-)
    echo "- **[$FILE_PATH]($FILE_PATH):$LINE_NUMBER**: $TEXT" >> "$REPORT"
done

echo "Generated 2-do report in $REPORT"