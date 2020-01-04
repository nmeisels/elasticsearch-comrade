FROM python:3.8.1-alpine@sha256:8412de90c7717917752ecb7f244087d4c7187622ac61051fdf4da95f8503e9cc
WORKDIR /app
COPY setup.py MANIFEST.in server/Pipfile* ./
RUN apk add --no-cache gcc libc-dev make libffi-dev libressl-dev && \
    mkdir /app/comrade && \
    pip install pipenv && \
    pipenv install -e . --skip-lock && \
    apk del gcc make libc-dev libffi-dev libressl-dev && \
    rm -rf ~/.cache /var/cache && \
    find /usr/local/lib/python3.7/ -type d -name __pycache__ | xargs rm -rf && \
    find /root/.local/ -type d -name __pycache__ | xargs rm -rf
COPY server/ /app/comrade/
EXPOSE 8000
CMD pipenv run comrade
