#!/usr/bin/env bash
set -e
if [ -t 1 ] && [ -n "${TERM:-}" ]; then
    clear
fi

# Canonical venv for koru autonomous + README is .venv (not venv).
if [ -x ".venv/bin/pip" ]; then
    VENV=".venv"
elif [ -x "venv/bin/pip" ]; then
    VENV="venv"
else
    VENV=".venv"
fi
PIP="$VENV/bin/pip"

if [ ! -f "$PIP" ]; then
    echo "Creating virtual environment at $VENV..."
    python3 -m venv "$VENV"
fi
echo "Using Python env: $VENV"

$PIP install regix --upgrade --quiet
#$PIP install pyqual --upgrade --quiet
$PIP install prefact --upgrade --quiet
$PIP install vallm --upgrade --quiet
$PIP install redup --upgrade --quiet
$PIP install glon --upgrade --quiet
$PIP install code2logic --upgrade --quiet
$PIP install code2llm --upgrade --quiet
#$VENV/bin/code2llm ./ -f toon,evolution,code2logic,project-yaml -o ./project --no-chunk
$VENV/bin/code2llm ./ -f all -o ./project --no-chunk --exclude '*.md'
#$VENV/bin/code2llm report --format all       # → all views

$VENV/bin/prefact -a -e "examples/**"


$PIP install doql --upgrade --quiet
$VENV/bin/doql adopt . --format less --output app.doql.less --force

# Disabled: sumd (as of 0.3.60) reads project/*.toon.yaml as input for
# SUMD.md/SUMR.md, but also has a side effect of regenerating map.toon.yaml
# itself with a much smaller, simplified version — silently clobbering
# code2llm's canonical map (271KB+/500+ modules down to ~40KB/10 functions)
# a few seconds after code2llm wrote it. Upstream fix (sumd should skip a
# map.toon.yaml owned by code2llm) is tracked but not yet effective in the
# published version — re-enable once verified fixed on PyPI.
#$PIP install sumd --upgrade --quiet
#$VENV/bin/sumd .
#$VENV/bin/sumr .



if [ -x "./tree.sh" ]; then
    bash ./tree.sh
elif command -v tree >/dev/null 2>&1; then
    tree -L 2
else
    echo "Skipping tree snapshot: ./tree.sh not found and 'tree' is not installed."
fi
