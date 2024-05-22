#!/bin/sh
python manage.py migrate
python manage.py collectstatic --noinput
gunicorn Simple5K.wsgi --bind 0.0.0.0:8000 --timeout 60 --workers=8 --threads=2 --error-logfile "-" --access-logfile "-" --capture-output --log-level debug