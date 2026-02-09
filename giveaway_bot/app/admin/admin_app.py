import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from passlib.hash import bcrypt
from itsdangerous import URLSafeSerializer
from sqlalchemy import select
from ..db import Base, engine, SessionLocal
from ..models import Giveaway, PromoCode

app = FastAPI()

# Load .env reliably both locally and on server
BASE_DIR = Path(__file__).resolve().parents[2]  # .../giveaway_bot
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH if ENV_PATH.exists() else None)

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "admin" / "templates"))

ADMIN_LOGIN = os.getenv("ADMIN_LOGIN", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin12345")
SECRET = os.getenv("ADMIN_SECRET", "supersecret")
serializer = URLSafeSerializer(SECRET)

Base.metadata.create_all(bind=engine)

def is_authed(request: Request) -> bool:
    cookie = request.cookies.get("session", "")
    if not cookie:
        return False
    try:
        data = serializer.loads(cookie)
        return data.get("u") == ADMIN_LOGIN
    except Exception:
        return False

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=302)
    with SessionLocal() as db:
        giveaways = db.execute(select(Giveaway).order_by(Giveaway.id.desc())).scalars().all()
    return templates.TemplateResponse("dashboard.html", {"request": request, "giveaways": giveaways})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "err": ""})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    # простий логін (MVP)
    if username == ADMIN_LOGIN and password == ADMIN_PASSWORD:
        cookie = serializer.dumps({"u": username})
        resp = RedirectResponse("/", status_code=302)
        resp.set_cookie("session", cookie, httponly=True)
        return resp
    return templates.TemplateResponse("login.html", {"request": request, "err": "Невірний логін/пароль"})

@app.get("/giveaway/new", response_class=HTMLResponse)
def giveaway_new(request: Request):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("giveaway_form.html", {"request": request})

@app.post("/giveaway/new")
def giveaway_create(
        request: Request,
        title: str = Form(...),
        description: str = Form(""),
        winners_count: int = Form(1),
        channel_username: str = Form(""),
):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=302)
    with SessionLocal() as db:
        g = Giveaway(title=title, description=description, winners_count=winners_count, channel_username=channel_username, is_active=True)
        db.add(g)
        db.commit()
    return RedirectResponse("/", status_code=302)

@app.get("/codes/{giveaway_id}", response_class=HTMLResponse)
def codes_page(request: Request, giveaway_id: int):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=302)
    with SessionLocal() as db:
        codes = db.execute(select(PromoCode).where(PromoCode.giveaway_id==giveaway_id).order_by(PromoCode.id.desc())).scalars().all()
    return templates.TemplateResponse("codes.html", {"request": request, "codes": codes, "giveaway_id": giveaway_id})

@app.post("/codes/{giveaway_id}")
def codes_create(request: Request, giveaway_id: int, code: str = Form(...), max_uses: int = Form(1)):
    if not is_authed(request):
        return RedirectResponse("/login", status_code=302)
    with SessionLocal() as db:
        pc = PromoCode(giveaway_id=giveaway_id, code=code.strip(), max_uses=max_uses, uses=0, is_active=True)
        db.add(pc)
        db.commit()
    return RedirectResponse(f"/codes/{giveaway_id}", status_code=302)
