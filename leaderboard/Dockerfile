# Sandbox image for running student code: python leaderboard/runner.py inside it.
# Build once on the server:  docker build -t adc-leaderboard leaderboard/
FROM python:3.12-slim
RUN pip install --no-cache-dir numpy opencv-python-headless \
 && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
