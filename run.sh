#!/usr/bin/env bash
# Development runner for Ring

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/build/resources"

mkdir -p "$BUILD_DIR"

# Find blueprint-compiler (try multiple methods)
BLUEPRINT_COMPILER=""
for candidate in "$(command -v blueprint-compiler 2>/dev/null)" \
                 "/usr/bin/blueprint-compiler" \
                 "$(python3 -c 'import shutil; p=shutil.which(\"blueprint-compiler\"); print(p or \"\")' 2>/dev/null)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
        BLUEPRINT_COMPILER="$candidate"
        break
    fi
done

if [ -n "$BLUEPRINT_COMPILER" ]; then
    echo "Compiling blueprints with: $BLUEPRINT_COMPILER"

    "$BLUEPRINT_COMPILER" compile \
      "$SCRIPT_DIR/src/resources/window.blp" \
      --output "$BUILD_DIR/window.ui" 2>&1 || echo "Warning: window.blp compilation failed"
else
    echo "Warning: blueprint-compiler not found. Using existing UI files if present."
    if [ ! -f "$BUILD_DIR/window.ui" ]; then
        echo "Error: window.ui not found. Run 'build-blueprints.sh' first."
        exit 1
    fi
fi

# Run the application
export PYTHONPATH="$SCRIPT_DIR/src:$PYTHONPATH"
exec python3 "$SCRIPT_DIR/src/main.py" "$@"
