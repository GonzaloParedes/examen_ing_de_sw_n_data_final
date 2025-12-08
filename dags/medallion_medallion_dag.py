"""Airflow DAG that orchestrates the medallion pipeline."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pendulum
from airflow import DAG
from airflow.exceptions import AirflowException
from airflow.operators.python import PythonOperator

# Agregar el directorio base al path para poder importar módulos locales
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))


from include.transformations import clean_daily_transactions

# Definición de rutas (Paths)
RAW_DIR = BASE_DIR / "data/raw"
CLEAN_DIR = BASE_DIR / "data/clean"
QUALITY_DIR = BASE_DIR / "data/quality"
DBT_DIR = BASE_DIR / "dbt"
PROFILES_DIR = BASE_DIR / "profiles"
WAREHOUSE_PATH = BASE_DIR / "warehouse/medallion.duckdb"


def _build_env(ds_nodash: str) -> dict[str, str]:
    """Build environment variables needed by dbt commands."""
    env = os.environ.copy()
    env.update(
        {
            "DBT_PROFILES_DIR": str(PROFILES_DIR),
            "CLEAN_DIR": str(CLEAN_DIR),
            "DS_NODASH": ds_nodash,
            "DUCKDB_PATH": str(WAREHOUSE_PATH),
        }
    )
    return env


def _run_dbt_command(command: str, ds_nodash: str, quality: bool = False) -> None:
    """Ejecuta dbt. Si quality=True, guarda el reporte de data quality."""
    env = _build_env(ds_nodash)

    result = subprocess.run(
        ["dbt"] + command.split() + ["--project-dir", str(DBT_DIR)],
        cwd=DBT_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    print("STDOUT:", result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)

    # SOLO GOLD genera archivo de DQ
    if quality:
        QUALITY_DIR.mkdir(parents=True, exist_ok=True)

        status = "passed" if result.returncode == 0 else "failed"

        dq_report = {
            "ds_nodash": ds_nodash,
            "status": status,
            "command": command,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

        report_path = QUALITY_DIR / f"dq_results_{ds_nodash}.json"

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(dq_report, f, indent=2)

    if result.returncode != 0:
        raise AirflowException(f"dbt command failed: {result.stderr}")


# --- WRAPPERS PARA LOS TASKS ---


def run_bronze(**kwargs):
    """
    Wrapper para la limpieza.
    Airflow pasa 'execution_date' (pendulum datetime) en **kwargs.
    Tu helper espera 'execution_date' como objeto fecha.
    """
    execution_date = kwargs["execution_date"]
    clean_daily_transactions(
        execution_date=execution_date,  # Pasamos el objeto fecha directo
        raw_dir=RAW_DIR,  # Pasamos el Path definido arriba
        clean_dir=CLEAN_DIR,  # Pasamos el Path definido arriba
    )


def run_silver(**kwargs):
    """Ejecuta modelos silver."""
    ds_nodash = kwargs['ds_nodash']

    _run_dbt_command("run --select tag:silver", ds_nodash)


def run_gold(**kwargs):
    """Ejecuta modelos gold y genera reporte de data quality."""
    ds_nodash = kwargs['ds_nodash']
    _run_dbt_command("test --select tag:gold", ds_nodash, quality=True)


def build_dag() -> DAG:
    """Construct the medallion pipeline DAG."""
    with DAG(
        description="Bronze/Silver/Gold medallion demo",
        dag_id="medallion_pipeline",
        schedule="0 6 * * *",
        start_date=pendulum.datetime(2025, 12, 1, tz="UTC"),
        catchup=True,
        max_active_runs=1,
    ) as medallion_dag:

        # 1. BRONZE: Limpieza con Pandas (Usando tu helper)
        bronze_task = PythonOperator(
            task_id="bronze_layer",
            python_callable=run_bronze,
            # No necesitamos op_kwargs para ds_nodash aqui,
            # porque run_bronze usa 'execution_date' del contexto automático
        )

        # 2. SILVER: dbt run (Tag Silver)
        silver_task = PythonOperator(
            task_id="silver_layer",
            python_callable=run_silver,
            op_kwargs={"ds_nodash": "{{ ds_nodash }}"},
        )

        # 3. GOLD: dbt run (Tag Gold)
        gold_task = PythonOperator(
            task_id="gold_layer",
            python_callable=run_gold,
            op_kwargs={"ds_nodash": "{{ ds_nodash }}"},
        )

        # Dependencias
        bronze_task >> silver_task >> gold_task

    return medallion_dag


dag = build_dag()
