#!/bin/bash

# Check for argument
if [ "$#" -ne 1 ]; then
  echo "Usage: $0 path/to/file.yml"
  exit 1
fi

FILE="$1"

# Check that the file exists
if [ ! -f "$FILE" ]; then
  echo "Error: '$FILE' not found."
  exit 1
fi

# Detect platform to use correct sed syntax
if [[ "$OSTYPE" == "darwin"* ]]; then
  # macOS (requires empty string after -i for in-place edit without backup)
  sed -i '' 's/node\.role == worker/node.role == manager/g' "$FILE"
else
  # Linux and others (GNU sed)
  sed -i 's/node\.role == worker/node.role == manager/g' "$FILE"
fi

echo "Replacement done in '$FILE'."
