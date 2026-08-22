from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, salary, account, cron

app = FastAPI(
    title="PocketMunim Core Engine",
    description="Ishita Financial Intelligence System - Zero-Trust Backend",
    version="2.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(salary.router)
app.include_router(account.router)
app.include_router(cron.router)

@app.get("/")
def health():
    return {
        "status": "ONLINE",
        "system": "Ishita Financial Intelligence System",
        "protocol": "IFIS-ZERO-TRUST-V2"
    }