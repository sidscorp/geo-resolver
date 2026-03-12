import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .dependencies import close_resolver
from .routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    close_resolver()


app = FastAPI(title="GeoResolver API", lifespan=lifespan)

_default_origins = ["http://localhost:5173"]
_origins_env = os.environ.get("GEO_RESOLVER_CORS_ORIGINS")
origins = [o.strip() for o in _origins_env.split(",") if o.strip()] if _origins_env else _default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
