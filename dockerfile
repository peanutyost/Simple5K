FROM python:3.12 as base
LABEL maintainer="peanutyost"

ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1

# Create a user to avoid running containers as root in production
RUN addgroup --system web \
    && adduser --system --ingroup web web

USER web
# Create a directory for the source code and use it as base path
WORKDIR /home/web/code/
# Copy the python depencencies list for pip
COPY --chown=web:web ./requirements.txt requirements.txt

USER root
# Install python packages at system level
RUN pip install --no-cache-dir -r requirements.txt

# Copy the script that starts the production application server (gunicorn)
COPY --chown=web:web ./Simple5K/start-prod-server.sh /usr/local/bin/start-prod-server.sh
RUN chmod +x /usr/local/bin/start-prod-server.sh

USER web
# Copy the source code of our django app to the working directoy
COPY --chown=web:web . ./
# The production server starts by default when the container starts
CMD ["start-prod-server.sh"]