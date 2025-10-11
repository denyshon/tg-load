import asyncio
import os

from tg_load.tg_load import setup
from tg_load.globals import env

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, status

from telegram import Update
from telegram.ext import Application, ContextTypes


@asynccontextmanager
async def lifespan(_: FastAPI):
    global application
    
    application = await setup()
    await application.start()
    yield
    await application.stop()
    await application.shutdown()

app = FastAPI(lifespan=lifespan)

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.post("/webhook")
async def telegram_webhook(request: Request):
    if env("WEBHOOK_SECRET_TOKEN", default = None):
        secret = request.headers.get("x-telegram-bot-api-secret-token")
        if secret != WEBHOOK_SECRET_TOKEN:
            return Response(status_code=status.HTTP_401_UNAUTHORIZED)
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
