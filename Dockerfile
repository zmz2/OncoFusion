FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY oncofusion ./oncofusion
RUN python -m pip install --no-cache-dir '.[graph]' && useradd --create-home --uid 10001 oncofusion && mkdir /app/runtime && chown oncofusion /app/runtime
USER oncofusion
EXPOSE 8000
ENTRYPOINT ["python", "-m", "oncofusion"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
