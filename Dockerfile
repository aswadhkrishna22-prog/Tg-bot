FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/app/data
RUN if ! getent group 1000 >/dev/null; then groupadd --gid 1000 appgroup; fi && if ! getent passwd 1000 >/dev/null; then useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin appuser; fi && mkdir -p /app/data && chown -R 1000:1000 /app && find /app -type d -exec chmod u+rwx {} + && find /app -type f \( -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' \) -exec chmod u+rw {} +
ENV HOME=/tmp
ENV PYTHONDONTWRITEBYTECODE=1
USER 1000:1000
CMD ["sh", "-lc", "cd /app && python -u server1.py"]
