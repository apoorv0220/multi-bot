from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import main as legacy_main
from api.routers import admin, auth, chat, health, public, reindex
from core.settings import get_settings


load_dotenv()

settings = get_settings()

app = FastAPI(title="Multi-Tenant Chatbot API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)

app.add_event_handler("startup", legacy_main.startup_event)
app.middleware("http")(legacy_main.exception_handling_middleware)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(public.router)
app.include_router(admin.router)
app.include_router(reindex.router)
app.include_router(health.router)
