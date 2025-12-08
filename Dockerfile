FROM apache/airflow:2.10.0-python3.11

USER root

# Instalar dependencias del sistema necesarias para dbt-duckdb
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER airflow

# Instalar dbt-duckdb y otras dependencias
RUN pip install --no-cache-dir \
    dbt-duckdb==1.10.0 \
    duckdb==1.4.2 \
    pandas==2.3.3 \
    pyarrow==22.0.0