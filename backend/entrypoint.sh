#!/bin/sh

echo "Waiting for PostgreSQL to be ready..."

until pg_isready -h postgres -p 5432 -U postgres; do
  sleep 1
done

echo "PostgreSQL is available running admin creation script..."

# Debug: Test import manually
/app/bin/python -c "import off_key.scripts.create_admin" || echo "Import failed"

# Run the admin creation script
/app/bin/python -m off_key.scripts.create_admin || echo "Admin might already exist."

echo "Starting FastAPI server..."
uvicorn off_key.main:app --host 0.0.0.0 --port 8000
