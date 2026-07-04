import os
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Form, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from passlib.context import CryptContext
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Text,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# =========================
# CONFIG
# =========================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/telemetry.db")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")

# =========================
# DB
# =========================
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"],
    deprecated="auto"
)

# =========================
# MODELS
# =========================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(80), unique=True, index=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, index=True, nullable=False)

    product_name = Column(String(120), nullable=False)
    product_serial = Column(String(120), unique=True, index=True, nullable=False)

    # Se vincula con el ESP32 que envía telemetría
    device_id = Column(String(120), unique=True, index=True, nullable=False)

    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )


class Telemetry(Base):
    __tablename__ = "telemetry"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(120), index=True, nullable=False)
    temperature = Column(Float, nullable=False)
    humidity = Column(Float, nullable=False)
    battery = Column(Integer, nullable=True)
    status = Column(String(50), nullable=True)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    raw_json = Column(Text, nullable=True)


Base.metadata.create_all(bind=engine)

# =========================
# APP
# =========================
app = FastAPI(title="IoT ColdChain Dashboard")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Esto es lo que faltaba
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    same_site="lax",
    https_only=False
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def render_index(request: Request, context: dict, status_code: int = 200):
    ctx = {"request": request, **context}
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=ctx,
        status_code=status_code,
    )


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def current_username(request: Request) -> Optional[str]:
    return request.session.get("user")


def require_user(request: Request) -> str:
    user = current_username(request)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    return user


def serialize_product(row: Product) -> dict:
    return {
        "id": row.id,
        "owner_id": row.owner_id,
        "product_name": row.product_name,
        "product_serial": row.product_serial,
        "device_id": row.device_id,
        "created_at": row.created_at.isoformat(),
    }


def serialize_telemetry(row: Telemetry) -> dict:
    return {
        "id": row.id,
        "device_id": row.device_id,
        "temperature": row.temperature,
        "humidity": row.humidity,
        "battery": row.battery,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
    }


def get_latest(db: Session, device_id: Optional[str] = None):
    q = db.query(Telemetry)
    if device_id:
        q = q.filter(Telemetry.device_id == device_id)
    return q.order_by(Telemetry.id.desc()).first()


def get_history(db: Session, device_id: Optional[str] = None, limit: int = 100):
    q = db.query(Telemetry)
    if device_id:
        q = q.filter(Telemetry.device_id == device_id)
    rows = q.order_by(Telemetry.id.desc()).limit(limit).all()
    return list(reversed(rows))


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    product_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    username = current_username(request)

    if not username:
        return render_index(
            request,
            {
                "user": None,
                "products": [],
                "selected_product": None,
                "latest": None,
                "history": [],
                "error": None,
                "success": None,
            },
        )

    user = db.query(User).filter(User.username == username).first()
    if not user:
        request.session.clear()
        return render_index(
            request,
            {
                "user": None,
                "products": [],
                "selected_product": None,
                "latest": None,
                "history": [],
                "error": "Sesión inválida. Vuelve a iniciar sesión.",
                "success": None,
            },
            status_code=401,
        )

    products = (
        db.query(Product)
        .filter(Product.owner_id == user.id)
        .order_by(Product.id.desc())
        .all()
    )

    selected_product = None
    if product_id is not None:
        selected_product = next((p for p in products if p.id == product_id), None)
    if selected_product is None and products:
        selected_product = products[0]

    latest = None
    history = []
    if selected_product is not None:
        latest_row = get_latest(db, selected_product.device_id)
        if latest_row:
            latest = serialize_telemetry(latest_row)
        history_rows = get_history(db, selected_product.device_id, limit=100)
        history = [serialize_telemetry(r) for r in history_rows]

    return render_index(
        request,
        {
            "user": username,
            "products": [serialize_product(p) for p in products],
            "selected_product": serialize_product(selected_product) if selected_product else None,
            "latest": latest,
            "history": history,
            "error": None,
            "success": None,
        },
    )


@app.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    username = username.strip().lower()

    if len(username) < 3 or len(password) < 6:
        return render_index(
            request,
            {
                "user": None,
                "products": [],
                "selected_product": None,
                "latest": None,
                "history": [],
                "error": "Usuario mínimo 3 caracteres y contraseña mínimo 6.",
                "success": None,
            },
            status_code=400,
        )

    existing = db.query(User).filter(User.username == username).first()
    if existing:
        return render_index(
            request,
            {
                "user": None,
                "products": [],
                "selected_product": None,
                "latest": None,
                "history": [],
                "error": "Ese usuario ya existe.",
                "success": None,
            },
            status_code=400,
        )

    user = User(
        username=username,
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()

    request.session["user"] = username
    return RedirectResponse("/", status_code=303)


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    username = username.strip().lower()
    user = db.query(User).filter(User.username == username).first()

    if not user or not verify_password(password, user.password_hash):
        return render_index(
            request,
            {
                "user": None,
                "products": [],
                "selected_product": None,
                "latest": None,
                "history": [],
                "error": "Credenciales inválidas.",
                "success": None,
            },
            status_code=401,
        )

    request.session["user"] = username
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.post("/products/new")
def create_product(
    request: Request,
    product_name: str = Form(...),
    product_serial: str = Form(...),
    device_id: str = Form(...),
    db: Session = Depends(get_db),
):
    username = require_user(request)

    user = db.query(User).filter(User.username == username).first()
    if not user:
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    product_name = product_name.strip()
    product_serial = product_serial.strip()
    device_id = device_id.strip()

    if not product_name or not product_serial or not device_id:
        return render_index(
            request,
            {
                "user": username,
                "products": [
                    serialize_product(p)
                    for p in db.query(Product).filter(Product.owner_id == user.id).all()
                ],
                "selected_product": None,
                "latest": None,
                "history": [],
                "error": "Todos los campos del producto son obligatorios.",
                "success": None,
            },
            status_code=400,
        )

    duplicate_serial = db.query(Product).filter(Product.product_serial == product_serial).first()
    if duplicate_serial:
        return render_index(
            request,
            {
                "user": username,
                "products": [
                    serialize_product(p)
                    for p in db.query(Product).filter(Product.owner_id == user.id).all()
                ],
                "selected_product": None,
                "latest": None,
                "history": [],
                "error": "Ese serial ya está registrado.",
                "success": None,
            },
            status_code=400,
        )

    duplicate_device = db.query(Product).filter(Product.device_id == device_id).first()
    if duplicate_device:
        return render_index(
            request,
            {
                "user": username,
                "products": [
                    serialize_product(p)
                    for p in db.query(Product).filter(Product.owner_id == user.id).all()
                ],
                "selected_product": None,
                "latest": None,
                "history": [],
                "error": "Ese device_id ya está asociado a otro producto.",
                "success": None,
            },
            status_code=400,
        )

    product = Product(
        owner_id=user.id,
        product_name=product_name,
        product_serial=product_serial,
        device_id=device_id,
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    return RedirectResponse(f"/?product_id={product.id}", status_code=303)


@app.get("/api/latest")
def api_latest(device_id: Optional[str] = None, db: Session = Depends(get_db)):
    row = get_latest(db, device_id=device_id)
    if not row:
        return {
            "device_id": None,
            "temperature": None,
            "humidity": None,
            "battery": None,
            "status": None,
            "created_at": None,
        }
    return serialize_telemetry(row)


@app.get("/api/history")
def api_history(device_id: Optional[str] = None, limit: int = 100, db: Session = Depends(get_db)):
    rows = get_history(db, device_id=device_id, limit=limit)
    return [serialize_telemetry(r) for r in rows]


@app.post("/telemetry")
async def receive_telemetry(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido")

    device_id = str(data.get("device_id", "unknown"))
    temperature = data.get("temperature", None)
    humidity = data.get("humidity", None)

    if temperature is None or humidity is None:
        raise HTTPException(status_code=400, detail="temperature y humidity son obligatorios")

    battery = data.get("battery")
    status = data.get("status")
    raw_json = json.dumps(data, ensure_ascii=False)

    row = Telemetry(
        device_id=device_id,
        temperature=float(temperature),
        humidity=float(humidity),
        battery=int(battery) if battery is not None else None,
        status=str(status) if status is not None else None,
        raw_json=raw_json,
    )

    db.add(row)
    db.commit()
    db.refresh(row)

    print("\n==================================================")
    print("PAQUETE RECIBIDO")
    print("==================================================")
    print(raw_json)
    print("==================================================")

    return JSONResponse(
        {
            "ok": True,
            "message": "Telemetry received",
            "id": row.id,
            "created_at": row.created_at.isoformat(),
        }
    )