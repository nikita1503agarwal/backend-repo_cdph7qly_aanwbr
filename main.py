import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

from database import create_document, get_documents, db
from schemas import IssueReport

app = FastAPI(title="Electrician Troubleshooter API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Electrician Troubleshooter API is running"}

@app.get("/api/hello")
def hello():
    return {"message": "Hello from the Electrician API!"}

# Simple rule-based troubleshooting engine
class TroubleshootRequest(BaseModel):
    equipment_type: str
    symptom: str
    readings: Optional[Dict[str, Any]] = None  # e.g., {"voltage": 120, "breaker_tripped": true}

class TroubleshootStep(BaseModel):
    title: str
    detail: str

class TroubleshootResponse(BaseModel):
    probable_causes: List[str]
    safety_notes: List[str]
    steps: List[TroubleshootStep]
    next_actions: List[str]


COMMON_SAFETY = [
    "De-energize and lockout/tagout when possible before opening equipment.",
    "Use a properly rated meter and verify it on a known source before and after testing.",
    "Wear appropriate PPE for the available fault current and arc flash boundaries.",
]

# Very lightweight rule set to bootstrap the app
RULES = {
    ("outlet", "no power"): {
        "causes": ["Tripped breaker", "Tripped GFCI upstream", "Loose neutral or hot"],
        "steps": [
            ("Check panel", "Verify the branch breaker is not tripped; reset if safe."),
            ("Test GFCIs", "Locate and reset any GFCI receptacles upstream in bathrooms, kitchen, garage, exterior."),
            ("Voltage test", "Measure hot-to-neutral and hot-to-ground at the receptacle; expect ~120V."),
            ("Inspect terminations", "If safe, check receptacle backstabs vs. screw terminals; tighten as needed."),
        ],
        "next": ["Document findings and load on circuit", "Consider replacing worn receptacle"],
    },
    ("light", "flickering"): {
        "causes": ["Loose lamp", "Failed lamp/driver", "Loose neutral", "Dimmer incompatibility"],
        "steps": [
            ("Secure lamp", "Reseat or replace lamp/fixture module."),
            ("Check dimmer", "Confirm fixture is compatible with installed dimmer; try bypassing dimmer."),
            ("Wiggle test", "With power off, tighten wire nuts and terminal screws in fixture box."),
        ],
        "next": ["Check voltage stability under load", "Consider upgrading dimmer/driver"],
    },
    ("breaker", "trips immediately"): {
        "causes": ["Hard short to ground/neutral", "Faulty breaker"],
        "steps": [
            ("Isolate loads", "Disconnect downstream loads and retry; if still trips, inspect homerun"),
            ("Megger/continuity", "With power off, test insulation resistance hot-to-neutral and hot-to-ground"),
        ],
        "next": ["Replace breaker after fault cleared if nuisance persists"],
    },
}

@app.post("/api/troubleshoot", response_model=TroubleshootResponse)
def troubleshoot(req: TroubleshootRequest):
    key = (req.equipment_type.strip().lower(), req.symptom.strip().lower())
    rule = RULES.get(key)
    if not rule:
        # generic response
        steps = [
            TroubleshootStep(title="Verify power", detail="Confirm source voltage and upstream overcurrent device status."),
            TroubleshootStep(title="Inspect connections", detail="De-energize and check all terminations for tightness and damage."),
            TroubleshootStep(title="Measure under load", detail="Compare open-circuit vs under-load readings to detect drops."),
        ]
        return TroubleshootResponse(
            probable_causes=["Insufficient data"],
            safety_notes=COMMON_SAFETY,
            steps=steps,
            next_actions=["Provide more details or select a closer symptom"],
        )

    steps = [TroubleshootStep(title=t, detail=d) for t, d in rule["steps"]]
    return TroubleshootResponse(
        probable_causes=rule["causes"],
        safety_notes=COMMON_SAFETY,
        steps=steps,
        next_actions=rule["next"],
    )

# Issue reports endpoints (persist to MongoDB)
@app.post("/api/issues")
def create_issue(issue: IssueReport):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    _id = create_document("issuereport", issue)
    return {"id": _id, "message": "Issue report saved"}

@app.get("/api/issues")
def list_issues(q: Optional[str] = None, limit: int = 50):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    flt = {}
    if q:
        # simple text search on notes, symptom, location
        flt = {"$or": [
            {"notes": {"$regex": q, "$options": "i"}},
            {"symptom": {"$regex": q, "$options": "i"}},
            {"location": {"$regex": q, "$options": "i"}},
        ]}
    docs = get_documents("issuereport", flt, limit)
    # Convert ObjectId to str
    for d in docs:
        if "_id" in d:
            d["id"] = str(d.pop("_id"))
    return {"items": docs}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Connected & Working"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = os.getenv("DATABASE_NAME") or "❌ Not Set"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    return response

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
