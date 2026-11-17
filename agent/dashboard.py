"""Serve Phase 7 evaluation reports and the built React dashboard."""
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Celeste offline experiments")
DIST = Path(__file__).resolve().parents[1] / "dashboard" / "dist"


def evaluation_path():
    return Path(os.environ.get("CELESTE_EVALUATION_REPORT", "logs/phase7-evaluation.json"))


@app.get("/api/evaluation")
def evaluation():
    path = evaluation_path()
    if not path.is_file():
        raise HTTPException(404, "Generate the evaluation report with python -m agent.evaluate.")
    return FileResponse(path, media_type="application/json")


@app.get("/api/evaluation/download")
def download():
    path = evaluation_path()
    if not path.is_file():
        raise HTTPException(404, "Evaluation report is unavailable.")
    return FileResponse(path, media_type="application/json", filename=path.name)


@app.get("/api/recordings")
def recordings():
    path = Path("data/recordings")
    return [json.loads(line) for file in sorted(path.glob("*.jsonl"))
            for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]


@app.get("/api/status")
def status():
    return {"mode": "offline", "live_connected": False, "token_usage": None,
            "api_cost": None, "screenshot": None}


if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="dashboard")
else:
    @app.get("/")
    def build_required():
        raise HTTPException(503, "Build the interface with npm --prefix dashboard run build.")
