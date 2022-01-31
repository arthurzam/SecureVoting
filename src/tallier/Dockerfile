FROM python:slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN python -m pip install websockets asyncpg

WORKDIR /app/
# COPY *.py /app/

# RUN adduser -u 5678 --disabled-password --gecos "" appuser && chown -R appuser /app
# USER appuser

# CMD ["python", "tallier.py", "1"]

ENTRYPOINT ["python", "main.py"]
# ENTRYPOINT ["python", "mpc_manager.py"]
