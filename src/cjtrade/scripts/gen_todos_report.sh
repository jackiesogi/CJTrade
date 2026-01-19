PROJECT_ROOT="$(git rev-parse --show-toplevel)"
CURRENT_VERSION_OR_TAG=$(git describe --tags --abbrev=0)
if [ -z "$CURRENT_VERSION_OR_TAG" ]; then
    CURRENT_VERSION_OR_TAG=$(git rev-parse --short HEAD)
fi

echo "Generating TODOs report in $PROJECT_ROOT"

TODO_REPORT="$PROJECT_ROOT/todos_report_for_${CURRENT_VERSION_OR_TAG}.md"

# Find all TODO comments in the codebase
echo "# TODOs Report for version $CURRENT_VERSION_OR_TAG" > "$TODO_REPORT"

echo "## List of TODOs" >> "$TODO_REPORT"
echo "" >> "$TODO_REPORT"
git grep -n "TODO" -- '*.py' '*.sh' '*.md' | while read -r line; do
    FILE_PATH=$(echo "$line" | cut -d: -f1)
    LINE_NUMBER=$(echo "$line" | cut -d: -f2)
    TODO_TEXT=$(echo "$line" | cut -d: -f3-)
    echo "- **[$FILE_PATH]($FILE_PATH):$LINE_NUMBER**: $TODO_TEXT" >> "$TODO_REPORT"
done