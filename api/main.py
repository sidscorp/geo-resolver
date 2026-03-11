from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router

app = FastAPI(title="GeoResolver API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://georesolver.snambiar.com",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
