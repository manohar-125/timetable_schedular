"""
FastAPI application for the Timetable Scheduler Web UI
"""

import os
import sys
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, HTTPException, Body
from fastapi.encoders import jsonable_encoder
from fastapi.responses import (
    StreamingResponse,
    HTMLResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles

# =========================================================
# PROJECT IMPORT PATH
# =========================================================

project_root = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

sys.path.insert(0, project_root)

# =========================================================
# ENGINE IMPORTS
# =========================================================

from timetable_scheduler.engine import generate_from_ui_state

from timetable_scheduler.engine.export import (
    export_to_csv,
    export_to_html,
    export_to_pdf,
    export_to_json,
)

# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI(title="Timetable Scheduler")

# =========================================================
# STATIC FILES
# =========================================================

static_dir = Path(__file__).parent / "static"

app.mount(
    "/static",
    StaticFiles(directory=str(static_dir)),
    name="static",
)

# =========================================================
# GLOBAL STATE
# =========================================================

current_state = {
    "ui_state": None,
    "engine_result": None,
    "timestamp": None,
}

# =========================================================
# GENERATE TIMETABLE
# =========================================================

@app.post("/api/generate")
async def generate_from_ui(payload: dict = Body(...)):
    """
    Generate timetable from UI payload.
    """

    try:

        result = generate_from_ui_state(payload)

        current_state["ui_state"] = payload
        current_state["engine_result"] = result
        current_state["timestamp"] = datetime.now().isoformat()

        return jsonable_encoder(result)

    except Exception as e:

        raise HTTPException(
            status_code=400,
            detail=str(e),
        )

# =========================================================
# CSV EXPORT
# =========================================================

@app.get("/api/export/csv")
async def export_csv():
    """
    Export timetable as CSV.
    """

    try:

        result = current_state.get("engine_result")

        if not result:
            raise HTTPException(
                status_code=400,
                detail="No timetable generated yet.",
            )

        if not result.success:
            raise HTTPException(
                status_code=400,
                detail="Current timetable is invalid.",
            )

        csv_content = export_to_csv(result)

        filename = (
            f"timetable_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )

        return StreamingResponse(
            iter([csv_content]),
            media_type="text/csv",
            headers={
                "Content-Disposition":
                f"attachment; filename={filename}"
            },
        )

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


# =========================================================
# BACKWARD COMPATIBILITY CSV
# =========================================================

@app.get("/api/export/engine/csv")
async def export_engine_csv():
    """
    Old CSV route compatibility.
    """
    return await export_csv()

# =========================================================
# HTML EXPORT
# =========================================================

@app.get("/api/export/html")
async def export_html():
    """
    Export printable university-style HTML timetable.
    """

    try:

        result = current_state.get("engine_result")

        if not result:
            raise HTTPException(
                status_code=400,
                detail="No timetable generated yet.",
            )

        if not result.success:
            raise HTTPException(
                status_code=400,
                detail="Current timetable is invalid.",
            )

        html_content = export_to_html(result)

        filename = (
            f"timetable_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        )

        return HTMLResponse(
            content=html_content,
            headers={
                "Content-Disposition":
                f"inline; filename={filename}"
            },
        )

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )

# =========================================================
# REAL PDF EXPORT
# =========================================================

@app.get("/api/export/pdf")
async def export_pdf():
    """
    Export timetable as REAL PDF.
    """

    try:

        result = current_state.get("engine_result")

        if not result:
            raise HTTPException(
                status_code=400,
                detail="No timetable generated yet.",
            )

        if not result.success:
            raise HTTPException(
                status_code=400,
                detail="Current timetable is invalid.",
            )

        pdf_bytes = export_to_pdf(result)

        filename = (
            f"timetable_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        )

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition":
                f"attachment; filename={filename}"
            },
        )

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )

# =========================================================
# BACKWARD COMPATIBILITY PDF
# =========================================================

@app.get("/api/export/engine/pdf")
async def export_engine_pdf():
    """
    Old PDF route compatibility.
    """
    return await export_pdf()

# =========================================================
# JSON EXPORT
# =========================================================

@app.get("/api/export/json")
async def export_json():
    """
    Export timetable as JSON.
    """

    try:

        result = current_state.get("engine_result")

        if not result:
            raise HTTPException(
                status_code=400,
                detail="No timetable generated yet.",
            )

        return export_to_json(result)

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )

# =========================================================
# HOME PAGE
# =========================================================

@app.get("/", response_class=HTMLResponse)
async def get_home():
    """
    Serve main HTML page.
    """

    template_path = (
        Path(__file__).parent / "index.html"
    )

    with open(
        template_path,
        "r",
        encoding="utf-8",
    ) as f:

        return f.read()

@app.get("/index.html", response_class=HTMLResponse)
async def get_home_index():
    """
    Compatibility route.
    """

    return await get_home()

# =========================================================
# RESET
# =========================================================

@app.post("/api/reset")
async def reset():
    """
    Reset application state.
    """

    current_state["ui_state"] = None
    current_state["engine_result"] = None
    current_state["timestamp"] = None

    return {
        "success": True,
        "message": "Application reset",
    }

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
    )