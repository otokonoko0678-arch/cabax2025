"""
Cabax - キャバクラ管理システム バックエンド（完全版）
FastAPI + SQLAlchemy + JWT認証
すべての機能に対応
"""

from fastapi import FastAPI, Depends, HTTPException, status, Request, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta
import jwt
import bcrypt
import os
import secrets
import string
from pathlib import Path

# 設定
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is required")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./cabax.db")

# PostgreSQLの場合はpostgresql://をpostgresql+psycopg2://に変換
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+psycopg2" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

# DBリセットフラグ（環境変数で制御）
RESET_DB = os.getenv("RESET_DB", "false").lower() == "true"

# SQLiteの場合、DBファイルを削除してリセット
if RESET_DB and "sqlite" in DATABASE_URL:
    db_path = DATABASE_URL.replace("sqlite:///", "")
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"🗑️ DB削除: {db_path}")

# データベース設定
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ========================
# データベースモデル
# ========================

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Table(Base):
    __tablename__ = "tables"
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True, index=True)
    name = Column(String, index=True)
    status = Column(String, default="available")
    is_vip = Column(Boolean, default=False)
    sessions = relationship("SessionModel", back_populates="table")

class StaffAttendance(Base):
    """スタッフの出勤記録"""
    __tablename__ = "staff_attendances"
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True, index=True)
    staff_id = Column(Integer, ForeignKey("staff.id"))
    date = Column(String)  # YYYY-MM-DD
    clock_in = Column(String)  # HH:MM
    clock_out = Column(String, nullable=True)  # HH:MM
    hours_worked = Column(Float, default=0)  # 勤務時間（時間単位）
    daily_wage = Column(Integer, default=0)  # その日の給与（計算済み）
    created_at = Column(DateTime, default=datetime.utcnow)

class Cast(Base):
    # 源氏名を使用
    __tablename__ = "casts"
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True, index=True)
    stage_name = Column(String, index=True)
    rank = Column(String, default="regular")
    salary_type = Column(String, default="hourly")  # hourly or monthly
    payment_type = Column(String, default="monthly")  # daily（日払い） or monthly（月払い）
    referrer_name = Column(String, nullable=True)  # 紹介者名（手入力）
    referral_bonus = Column(Integer, default=0)  # 紹介料（円/月）
    hourly_rate = Column(Integer)
    monthly_salary = Column(Integer, default=0)  # 月給（月給制の場合）
    drink_back_rate = Column(Integer, default=10)  # ドリンクバック率(%)
    companion_back = Column(Integer, default=3000)  # 同伴バック（円）
    nomination_back = Column(Integer, default=1000)  # 指名バック（円）
    sales_back_rate = Column(Integer, default=0)  # 売上バック率（%）
    sales = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    sessions = relationship("SessionModel", back_populates="cast")
    attendances = relationship("Attendance", back_populates="cast")

class MenuItem(Base):
    __tablename__ = "menu_items"
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True, index=True)
    name = Column(String, index=True)
    category = Column(String, index=True)
    price = Column(Integer)
    cost = Column(Integer, default=0)  # 原価
    description = Column(Text, nullable=True)
    image_url = Column(String, nullable=True)
    stock = Column(Integer, nullable=True)
    premium = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    orders = relationship("Order", back_populates="menu_item")

class SessionModel(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True, index=True)
    table_id = Column(Integer, ForeignKey("tables.id"))
    cast_id = Column(Integer, ForeignKey("casts.id"))
    guests = Column(Integer)
    catch_staff = Column(String, nullable=True)
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    current_total = Column(Integer, default=0)
    has_companion = Column(Boolean, default=False)
    companion_name = Column(String, nullable=True)
    extension_count = Column(Integer, default=0)
    nomination_type = Column(String, nullable=True)
    nomination_fee = Column(Integer, default=0)
    shimei_casts = Column(String, nullable=True)  # 指名キャスト名（カンマ区切り）
    tax_rate = Column(Integer, default=20)  # TAX/サービス料率（%）
    status = Column(String, default="active")
    # 精算ロック
    is_settling = Column(Boolean, default=False)
    settling_by = Column(String, nullable=True)
    settling_at = Column(DateTime, nullable=True)
    
    table = relationship("Table", back_populates="sessions")
    cast = relationship("Cast", back_populates="sessions")
    orders = relationship("Order", back_populates="session")

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"))
    menu_item_id = Column(Integer, ForeignKey("menu_items.id"), nullable=True)
    item_name = Column(String, nullable=True)  # カスタム商品名（カクテル（カシスオレンジ）など）
    quantity = Column(Integer)
    price = Column(Integer)
    is_drink_back = Column(Boolean, default=False)
    is_served = Column(Boolean, default=False)
    cast_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    session = relationship("SessionModel", back_populates="orders")
    menu_item = relationship("MenuItem", back_populates="orders")

class Attendance(Base):
    __tablename__ = "attendances"
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True, index=True)
    cast_id = Column(Integer, ForeignKey("casts.id"))
    date = Column(String, index=True)
    clock_in = Column(String)
    clock_out = Column(String, nullable=True)
    status = Column(String, default="working")
    cast = relationship("Cast", back_populates="attendances")

class Shift(Base):
    __tablename__ = "shifts"
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True, index=True)
    cast_id = Column(Integer, ForeignKey("casts.id"))
    date = Column(String, index=True)
    start_time = Column(String)
    end_time = Column(String)

class Staff(Base):
    __tablename__ = "staff"
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True, index=True)
    name = Column(String, index=True)
    role = Column(String)  # waiter, kitchen, manager, catch, driver, other
    salary_type = Column(String, default="hourly")  # hourly, daily, monthly
    salary_amount = Column(Integer, default=1000)  # 時給/日給/月給の金額
    phone = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Store(Base):
    """店舗・ライセンス管理"""
    __tablename__ = "stores"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)  # 店舗名
    license_key = Column(String, unique=True, index=True)  # ライセンスキー
    username = Column(String, unique=True, index=True, nullable=True)  # ログインユーザー名
    hashed_password = Column(String, nullable=True)  # ハッシュ化パスワード
    manager_pin = Column(String, nullable=True)  # 経営者PIN
    staff_pin = Column(String, nullable=True)  # スタッフPIN
    expires_at = Column(DateTime)  # 有効期限
    status = Column(String, default="active")  # active, expired, suspended
    plan = Column(String, default="standard")  # standard, premium
    monthly_fee = Column(Integer, default=30000)  # 月額料金
    owner_name = Column(String, nullable=True)  # オーナー名
    phone = Column(String, nullable=True)  # 電話番号
    email = Column(String, nullable=True)  # メール
    address = Column(String, nullable=True)  # 住所
    notes = Column(Text, nullable=True)  # メモ
    # 営業時間設定（営業日の区切り）- 旧形式（時間単位）
    business_start_hour = Column(Integer, default=18)  # 営業開始時間（0-23）
    business_end_hour = Column(Integer, default=6)    # 営業終了時間（0-23、翌日）
    # 営業時間設定（15分刻み・分単位）
    business_start_minutes = Column(Integer, default=1080)  # 営業開始（分）デフォルト18:00=1080
    business_end_minutes = Column(Integer, default=360)     # 営業終了（分）デフォルト6:00=360
    csv_export_enabled = Column(Boolean, default=False)  # CSVエクスポート機能のオン/オフ
    created_at = Column(DateTime, default=datetime.utcnow)

class ErrorLog(Base):
    """エラーログ"""
    __tablename__ = "error_logs"
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True, index=True)
    error_type = Column(String)  # js_error, api_error, unhandled_rejection
    message = Column(Text)  # エラーメッセージ
    stack = Column(Text, nullable=True)  # スタックトレース
    url = Column(String, nullable=True)  # 発生したページURL
    user_agent = Column(String, nullable=True)  # ブラウザ情報
    extra_info = Column(Text, nullable=True)  # 追加情報（JSON）
    created_at = Column(DateTime, default=datetime.utcnow)

class Expense(Base):
    """経費管理"""
    __tablename__ = "expenses"
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True, index=True)
    category = Column(String, index=True)  # liquor, food, rent, utilities, external_labor, advertising, supplies, telecom, other
    description = Column(String)  # 摘要
    amount = Column(Integer)  # 金額（円）
    date = Column(String, index=True)  # YYYY-MM-DD
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# ========================
# Pydanticモデル
# ========================

class LoginRequest(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class CastCreate(BaseModel):
    stage_name: str
    rank: str
    salary_type: str = "hourly"
    payment_type: str = "monthly"  # daily or monthly
    referrer_name: Optional[str] = None  # 紹介者名
    referral_bonus: int = 0  # 紹介料
    hourly_rate: int = 0
    monthly_salary: int = 0
    drink_back_rate: int = 10
    companion_back: int = 3000
    nomination_back: int = 1000
    sales_back_rate: int = 0

class CastUpdate(BaseModel):
    stage_name: Optional[str] = None
    rank: Optional[str] = None
    salary_type: Optional[str] = None
    payment_type: Optional[str] = None  # daily or monthly
    referrer_name: Optional[str] = None  # 紹介者名
    referral_bonus: Optional[int] = None  # 紹介料
    hourly_rate: Optional[int] = None
    monthly_salary: Optional[int] = None
    drink_back_rate: Optional[int] = None
    companion_back: Optional[int] = None
    nomination_back: Optional[int] = None
    sales_back_rate: Optional[int] = None

class CastResponse(BaseModel):
    id: int
    stage_name: str
    rank: str
    salary_type: str
    payment_type: str = "monthly"  # daily or monthly
    referrer_name: Optional[str] = None  # 紹介者名
    referral_bonus: int = 0  # 紹介料
    hourly_rate: int
    monthly_salary: int
    drink_back_rate: int
    companion_back: int
    nomination_back: int
    sales_back_rate: int
    sales: int
    class Config:
        from_attributes = True

class MenuItemCreate(BaseModel):
    name: str
    category: str
    price: int
    cost: Optional[int] = 0  # 原価
    description: Optional[str] = None
    image_url: Optional[str] = None
    stock: Optional[int] = None
    premium: Optional[bool] = False

class MenuItemUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    price: Optional[int] = None
    cost: Optional[int] = None  # 原価
    description: Optional[str] = None
    image_url: Optional[str] = None
    stock: Optional[int] = None
    premium: Optional[bool] = None

class MenuItemResponse(BaseModel):
    id: int
    name: str
    category: str
    price: int
    cost: Optional[int] = 0  # 原価
    description: Optional[str]
    image_url: Optional[str]
    stock: Optional[int]
    premium: Optional[bool] = False
    class Config:
        from_attributes = True

class TableCreate(BaseModel):
    name: str
    is_vip: bool = False

class TableResponse(BaseModel):
    id: int
    name: str
    status: str
    is_vip: bool
    class Config:
        from_attributes = True

class SessionCreate(BaseModel):
    table_id: int
    cast_id: int
    guests: int
    catch_staff: Optional[str] = None
    has_companion: bool = False
    companion_name: Optional[str] = None
    nomination_type: Optional[str] = None
    nomination_fee: int = 0
    shimei_casts: Optional[str] = None  # 指名キャスト名（カンマ区切り）
    tax_rate: int = 20  # TAX/サービス料率（%）
    store_id: Optional[int] = None  # 店舗ID

class SessionResponse(BaseModel):
    id: int
    table_id: int
    cast_id: Optional[int] = None
    guests: int
    catch_staff: Optional[str]
    start_time: datetime
    end_time: Optional[datetime]
    current_total: int
    tax_rate: int = 20
    status: str
    store_id: Optional[int] = None
    # 精算ロック
    is_settling: bool = False
    settling_by: Optional[str] = None
    settling_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class OrderCreate(BaseModel):
    session_id: int
    menu_item_id: int
    quantity: int
    is_drink_back: bool = False
    cast_name: Optional[str] = None
    item_name: Optional[str] = None  # カスタム商品名（カクテル（カシスオレンジ）など）
    custom_price: Optional[int] = None  # カスタム価格（キャストドリンクのサイズ別など）

class AttendanceCreate(BaseModel):
    cast_id: int
    date: str
    clock_in: str

class AttendanceClockOut(BaseModel):
    clock_out: str

class ShiftCreate(BaseModel):
    cast_id: int
    date: str
    start_time: str
    end_time: str

class StaffCreate(BaseModel):
    name: str
    role: str
    salary_type: str = "hourly"  # hourly, daily, monthly
    salary_amount: int = 1000
    phone: Optional[str] = None

class StaffUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    salary_type: Optional[str] = None
    salary_amount: Optional[int] = None
    phone: Optional[str] = None

class StaffAttendanceCreate(BaseModel):
    staff_id: int
    date: str
    clock_in: str

class StaffAttendanceClockOut(BaseModel):
    clock_out: str
    hours_worked: Optional[float] = None
    daily_wage: Optional[int] = None

class StaffResponse(BaseModel):
    id: int
    name: str
    role: str
    salary_type: str = "hourly"
    salary_amount: int = 1000
    phone: Optional[str]
    is_active: bool
    class Config:
        from_attributes = True

class StaffAttendanceResponse(BaseModel):
    id: int
    staff_id: int
    date: str
    clock_in: str
    clock_out: Optional[str]
    hours_worked: float = 0
    daily_wage: int = 0
    class Config:
        from_attributes = True

# 店舗・ライセンス管理用
class StoreCreate(BaseModel):
    name: str
    username: Optional[str] = None  # ログインユーザー名
    password: Optional[str] = None  # パスワード（平文で受け取りハッシュ化）
    owner_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    plan: str = "standard"
    monthly_fee: int = 30000
    notes: Optional[str] = None

class StoreUpdate(BaseModel):
    name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None  # 新しいパスワード（設定する場合）
    manager_pin: Optional[str] = None  # 経営者PIN
    staff_pin: Optional[str] = None  # スタッフPIN
    owner_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    plan: Optional[str] = None
    monthly_fee: Optional[int] = None
    status: Optional[str] = None
    notes: Optional[str] = None

class StoreResponse(BaseModel):
    id: int
    name: str
    license_key: str
    username: Optional[str]
    expires_at: datetime
    status: str
    plan: str
    monthly_fee: int
    owner_name: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    address: Optional[str]
    notes: Optional[str]
    created_at: datetime
    days_remaining: Optional[int] = None
    class Config:
        from_attributes = True

# 経費管理用
EXPENSE_CATEGORIES = {
    "liquor": "仕入れ（酒類）",
    "food": "仕入れ（食材）",
    "rent": "家賃",
    "utilities": "光熱費",
    "external_labor": "人件費（外部）",
    "advertising": "広告宣伝費",
    "supplies": "消耗品",
    "telecom": "通信費",
    "other": "その他",
}

class ExpenseCreate(BaseModel):
    category: str
    description: str
    amount: int
    date: str  # YYYY-MM-DD

class ExpenseUpdate(BaseModel):
    category: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[int] = None
    date: Optional[str] = None

class ExpenseResponse(BaseModel):
    id: int
    store_id: Optional[int]
    category: str
    category_label: Optional[str] = None
    description: str
    amount: int
    date: str
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True

# ========================
# 認証
# ========================

security = HTTPBearer()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_bytes = plain_password.encode('utf-8')[:72]
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)

def get_password_hash(password: str) -> str:
    password_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode('utf-8')

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return payload  # store_id, role等を含むペイロード全体を返す
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """認証トークンからユーザー名を返す（後方互換）"""
    payload = verify_token(credentials)
    return payload.get("sub")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_store_id_from_token(payload: dict = Depends(verify_token)) -> Optional[int]:
    """JWTトークンからstore_idを取得（偽装不可）"""
    store_id = payload.get("store_id")
    if store_id is not None:
        return int(store_id)
    return None

def get_store_id(request: Request) -> Optional[int]:
    """ヘッダーからstore_idを取得（認証不要エンドポイント用）"""
    x_store_id = request.headers.get("x-store-id") or request.headers.get("X-Store-Id") or request.headers.get("X-STORE-ID")
    if x_store_id:
        try:
            return int(x_store_id)
        except ValueError:
            return None
    return None

# ========================
# FastAPI アプリケーション
# ========================

app = FastAPI(title="Cabax API", version="2.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    
    # === マイグレーション: 新しいカラムを追加 ===
    from sqlalchemy import text, inspect
    
    try:
        # castsテーブルのカラムを確認
        inspector = inspect(engine)
        cast_columns = [col['name'] for col in inspector.get_columns('casts')]
        
        # payment_type カラムを追加
        if 'payment_type' not in cast_columns:
            db.execute(text("ALTER TABLE casts ADD COLUMN payment_type VARCHAR DEFAULT 'monthly'"))
            db.commit()
            print("✅ マイグレーション: casts.payment_type カラム追加")
        
        # referrer_name カラムを追加（紹介者名）
        if 'referrer_name' not in cast_columns:
            db.execute(text("ALTER TABLE casts ADD COLUMN referrer_name VARCHAR"))
            db.commit()
            print("✅ マイグレーション: casts.referrer_name カラム追加")
        
        # referral_bonus カラムを追加
        if 'referral_bonus' not in cast_columns:
            db.execute(text("ALTER TABLE casts ADD COLUMN referral_bonus INTEGER DEFAULT 0"))
            db.commit()
            print("✅ マイグレーション: casts.referral_bonus カラム追加")

        # stores テーブルに csv_export_enabled カラムを追加
        store_columns = [col['name'] for col in inspector.get_columns('stores')]
        if 'csv_export_enabled' not in store_columns:
            db.execute(text("ALTER TABLE stores ADD COLUMN csv_export_enabled BOOLEAN DEFAULT FALSE"))
            db.commit()
            print("✅ マイグレーション: stores.csv_export_enabled カラム追加")

    except Exception as e:
        print(f"⚠️ マイグレーションエラー（無視可能）: {e}")
        db.rollback()
    
    # デフォルトユーザー
    existing_user = db.query(User).filter(User.username == "admin").first()
    if not existing_user:
        hashed_password = get_password_hash("cabax2024")
        default_user = User(username="admin", hashed_password=hashed_password)
        db.add(default_user)
        db.commit()
        print("✅ デフォルトユーザー作成: admin / cabax2024")
    
    # テーブル
    if db.query(Table).count() == 0:
        tables = [
            Table(name="1", status="available"),
            Table(name="2", status="available"),
            Table(name="3", status="available", is_vip=True),
            Table(name="4", status="available"),
            Table(name="5", status="available"),
            Table(name="6", status="available"),
        ]
        db.add_all(tables)
        db.commit()
        print("✅ テーブル作成完了")
    
    # メニュー
    if db.query(MenuItem).count() == 0:
        menu_items = [
            # === ドリンク（お客様用・セット込み） ===
            MenuItem(name="レモンサワー", price=0, category="drink", description="お客様用"),
            MenuItem(name="コークハイ", price=0, category="drink", description="お客様用"),
            MenuItem(name="ジンジャーハイ", price=0, category="drink", description="お客様用"),
            MenuItem(name="ビール", price=0, category="drink", description="beer"),
            MenuItem(name="カクテル", price=0, category="drink", description="cocktail"),
            MenuItem(name="ソフトドリンク", price=0, category="drink", description="soft"),
            MenuItem(name="ショット", price=2000, category="drink", description="shot"),
            MenuItem(name="グラスワイン", price=2000, category="drink", description="glasswine"),
            
            # === キャスト・スタッフドリンク（バック記録用） ===
            MenuItem(name="麦焼酎", price=1000, category="castdrink", description="shochu"),
            MenuItem(name="ウイスキー", price=1000, category="castdrink", description="whisky"),
            
            # === 卓セット ===
            MenuItem(name="アイスセット", price=0, category="tableset", description="グラス・アイスペール・氷"),
            MenuItem(name="アイス（追加）", price=0, category="tableset", description="氷の追加"),
            MenuItem(name="グラス（追加）", price=0, category="tableset", description="グラスの追加"),
            MenuItem(name="ウーロン茶ピッチャー", price=0, category="tableset", description="割り物"),
            MenuItem(name="緑茶ピッチャー", price=0, category="tableset", description="割り物"),
            MenuItem(name="炭酸水", price=0, category="tableset", description="割り物"),
            MenuItem(name="紅茶ピッチャー", price=0, category="tableset", description="割り物"),
            MenuItem(name="ジャスミン茶ピッチャー", price=0, category="tableset", description="割り物"),
            MenuItem(name="コーヒーピッチャー", price=0, category="tableset", description="割り物"),
            MenuItem(name="ミネラルウォーター", price=0, category="tableset", description="割り物"),
            
            # === シャンパン ===
            MenuItem(name="アルマンド ブリニャック ブリュット", price=120000, category="champagne", description="ゴールドボトル", premium=True),
            MenuItem(name="アルマンド ロゼ", price=150000, category="champagne", description="ピンクの輝き", premium=True),
            MenuItem(name="クリュッグ グランキュヴェ", price=50000, category="champagne", description="シャンパンの帝王", premium=True),
            MenuItem(name="ドン ペリニヨン", price=45000, category="champagne", description="最高峰のシャンパン", premium=True),
            MenuItem(name="ドン ペリニヨン ロゼ", price=70000, category="champagne", description="希少なロゼ", premium=True),
            MenuItem(name="ベル エポック", price=35000, category="champagne", description="美しいボトル", premium=True),
            MenuItem(name="サロン", price=80000, category="champagne", description="幻のシャンパン", premium=True),
            MenuItem(name="ヴーヴ クリコ イエローラベル", price=18000, category="champagne", description="定番シャンパン"),
            MenuItem(name="モエ エ シャンドン", price=15000, category="champagne", description="世界で愛される"),
            MenuItem(name="ローラン ペリエ", price=20000, category="champagne", description="エレガントな味わい"),
            
            # === ワイン（ボトル） ===
            MenuItem(name="赤ワイン（ボトル）", price=8000, category="wine", description="フルボディ"),
            MenuItem(name="白ワイン（ボトル）", price=8000, category="wine", description="辛口"),
            
            # === ボトル ===
            MenuItem(name="黒霧島 ボトル", price=5000, category="bottle", description="芋焼酎の定番"),
            MenuItem(name="いいちこ ボトル", price=4500, category="bottle", description="麦焼酎"),
            MenuItem(name="ジャックダニエル ボトル", price=12000, category="bottle", description="テネシーウイスキー"),
            MenuItem(name="山崎 ボトル", price=35000, category="bottle", description="ジャパニーズウイスキー", premium=True),
            
            # === フード ===
            MenuItem(name="フルーツ盛り合わせ", price=3000, category="food", description="季節のフルーツ"),
            MenuItem(name="チョコレート", price=1500, category="food", description="ベルギー産"),
            MenuItem(name="ナッツ盛り合わせ", price=1000, category="food", description="ミックスナッツ"),
            MenuItem(name="チーズ盛り合わせ", price=2000, category="food", description="厳選チーズ"),
            MenuItem(name="枝豆", price=500, category="food", description="定番おつまみ"),
            MenuItem(name="唐揚げ", price=800, category="food", description="自家製"),
        ]
        db.add_all(menu_items)
        db.commit()
        print("✅ メニュー作成完了")
    
    # キャスト
    if db.query(Cast).count() == 0:
        casts = [
            Cast(stage_name="あいり", rank="レギュラー", salary_type="hourly", hourly_rate=3000, drink_back_rate=10, companion_back=3000, nomination_back=1000, sales_back_rate=0),
            Cast(stage_name="みゆ", rank="レギュラー", salary_type="hourly", hourly_rate=3000, drink_back_rate=10, companion_back=3000, nomination_back=1000, sales_back_rate=0),
            Cast(stage_name="れな", rank="エース", salary_type="hourly", hourly_rate=4000, drink_back_rate=15, companion_back=4000, nomination_back=1500, sales_back_rate=3),
            Cast(stage_name="かな", rank="エース", salary_type="hourly", hourly_rate=4000, drink_back_rate=15, companion_back=4000, nomination_back=1500, sales_back_rate=3),
            Cast(stage_name="りお", rank="ナンバー", salary_type="monthly", hourly_rate=0, monthly_salary=500000, drink_back_rate=20, companion_back=5000, nomination_back=2000, sales_back_rate=5),
        ]
        db.add_all(casts)
        db.commit()
        print("✅ キャスト作成完了")
    
    # スタッフ
    if db.query(Staff).count() == 0:
        staff_members = [
            Staff(name="田中", role="manager", salary_type="monthly", salary_amount=300000),
            Staff(name="山田", role="waiter", salary_type="hourly", salary_amount=1200),
            Staff(name="佐藤", role="waiter", salary_type="hourly", salary_amount=1200),
            Staff(name="鈴木", role="kitchen", salary_type="daily", salary_amount=10000),
            Staff(name="高橋", role="catch", salary_type="hourly", salary_amount=1000),
        ]
        db.add_all(staff_members)
        db.commit()
        print("✅ スタッフ作成完了")
    
    db.close()

# ========================
# APIエンドポイント
# ========================

# 認証
@app.post("/api/auth/login", response_model=Token)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    # まず店舗テーブルで認証を試みる
    store = db.query(Store).filter(Store.username == request.username).first()

    if store:
        
        # ステータスチェック
        if store.status == "suspended":
            raise HTTPException(status_code=403, detail="このアカウントは停止されています")
        if store.expires_at and store.expires_at < datetime.utcnow():
            raise HTTPException(status_code=403, detail="ライセンスの有効期限が切れています")
        
        # PIN認証（経営者PIN or スタッフPIN）
        role = None
        if store.manager_pin and verify_password(request.password, store.manager_pin):
            role = "manager"
        elif store.staff_pin and verify_password(request.password, store.staff_pin):
            role = "staff"
        # 従来のパスワード認証（後方互換性）
        elif store.hashed_password and verify_password(request.password, store.hashed_password):
            role = "manager"  # パスワード認証は経営者扱い
        
        if role:
            access_token = create_access_token(data={
                "sub": request.username, 
                "store_id": store.id, 
                "store_name": store.name,
                "role": role
            })
            return {
                "access_token": access_token, 
                "token_type": "bearer",
                "store_id": store.id,
                "store_name": store.name,
                "role": role
            }
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="PINまたはパスワードが正しくありません")
    
    # 従来のUserテーブルで認証（後方互換性 - store_id=null）
    user = db.query(User).filter(User.username == request.username).first()
    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="ユーザー名またはパスワードが正しくありません")
    access_token = create_access_token(data={"sub": user.username, "role": "manager"})
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "store_id": None,
        "store_name": None,
        "role": "manager"
    }

# キャスト管理
@app.get("/api/casts", response_model=List[CastResponse])
def get_casts(db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    query = db.query(Cast)
    if store_id:
        query = query.filter(Cast.store_id == store_id)
    return query.all()

@app.post("/api/casts", response_model=CastResponse)
def create_cast(cast: CastCreate, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    db_cast = Cast(**cast.dict(), store_id=store_id)
    db.add(db_cast)
    db.commit()
    db.refresh(db_cast)
    return db_cast

@app.put("/api/casts/{cast_id}", response_model=CastResponse)
def update_cast(cast_id: int, cast: CastUpdate, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    query = db.query(Cast).filter(Cast.id == cast_id)
    if store_id:
        query = query.filter(Cast.store_id == store_id)
    db_cast = query.first()
    if not db_cast:
        raise HTTPException(status_code=404, detail="Cast not found")
    for key, value in cast.dict(exclude_unset=True).items():
        setattr(db_cast, key, value)
    db.commit()
    db.refresh(db_cast)
    return db_cast

@app.delete("/api/casts/{cast_id}")
def delete_cast(cast_id: int, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    query = db.query(Cast).filter(Cast.id == cast_id)
    if store_id:
        query = query.filter(Cast.store_id == store_id)
    db_cast = query.first()
    if not db_cast:
        raise HTTPException(status_code=404, detail="Cast not found")
    db.delete(db_cast)
    db.commit()
    return {"message": "Cast deleted"}

# スタッフ管理
@app.get("/api/staff", response_model=List[StaffResponse])
def get_staff(db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    query = db.query(Staff).filter(Staff.is_active == True)
    if store_id:
        query = query.filter(Staff.store_id == store_id)
    return query.all()

@app.post("/api/staff", response_model=StaffResponse)
def create_staff(staff: StaffCreate, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    db_staff = Staff(**staff.dict(), store_id=store_id)
    db.add(db_staff)
    db.commit()
    db.refresh(db_staff)
    return db_staff

@app.put("/api/staff/{staff_id}", response_model=StaffResponse)
def update_staff(staff_id: int, staff: StaffUpdate, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    query = db.query(Staff).filter(Staff.id == staff_id)
    if store_id:
        query = query.filter(Staff.store_id == store_id)
    db_staff = query.first()
    if not db_staff:
        raise HTTPException(status_code=404, detail="Staff not found")
    for key, value in staff.dict(exclude_unset=True).items():
        setattr(db_staff, key, value)
    db.commit()
    db.refresh(db_staff)
    return db_staff

@app.delete("/api/staff/{staff_id}")
def delete_staff(staff_id: int, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    query = db.query(Staff).filter(Staff.id == staff_id)
    if store_id:
        query = query.filter(Staff.store_id == store_id)
    db_staff = query.first()
    if not db_staff:
        raise HTTPException(status_code=404, detail="Staff not found")
    db_staff.is_active = False  # 論理削除
    db.commit()
    return {"message": "Staff deleted"}

# スタッフ勤怠管理
@app.get("/api/staff-attendance")
def get_staff_attendance(date: Optional[str] = None, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    """スタッフ勤怠一覧を取得"""
    query = db.query(StaffAttendance)
    if date:
        query = query.filter(StaffAttendance.date == date)
    if store_id:
        query = query.filter(StaffAttendance.store_id == store_id)
    attendances = query.all()
    
    # スタッフ情報を付加
    result = []
    for att in attendances:
        staff = db.query(Staff).filter(Staff.id == att.staff_id).first()
        result.append({
            "id": att.id,
            "staff_id": att.staff_id,
            "staff_name": staff.name if staff else "不明",
            "role": staff.role if staff else "",
            "salary_type": staff.salary_type if staff else "hourly",
            "salary_amount": staff.salary_amount if staff else 0,
            "date": att.date,
            "clock_in": att.clock_in,
            "clock_out": att.clock_out,
            "hours_worked": att.hours_worked,
            "daily_wage": att.daily_wage
        })
    return result

@app.post("/api/staff-attendance")
def create_staff_attendance(data: StaffAttendanceCreate, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    """スタッフ出勤記録を作成"""
    # 既に同日の出勤があるかチェック
    existing = db.query(StaffAttendance).filter(
        StaffAttendance.staff_id == data.staff_id,
        StaffAttendance.date == data.date
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already clocked in today")
    
    attendance = StaffAttendance(
        store_id=store_id,
        staff_id=data.staff_id,
        date=data.date,
        clock_in=data.clock_in
    )
    db.add(attendance)
    db.commit()
    db.refresh(attendance)
    return attendance

@app.put("/api/staff-attendance/{attendance_id}/clock-out")
def staff_clock_out(attendance_id: int, data: StaffAttendanceClockOut, db: Session = Depends(get_db), _auth: dict = Depends(verify_token)):
    """スタッフ退勤処理"""
    attendance = db.query(StaffAttendance).filter(StaffAttendance.id == attendance_id).first()
    if not attendance:
        raise HTTPException(status_code=404, detail="Attendance not found")
    
    # スタッフ情報を取得
    staff = db.query(Staff).filter(Staff.id == attendance.staff_id).first()
    
    attendance.clock_out = data.clock_out
    
    # 勤務時間を計算
    if attendance.clock_in and data.clock_out:
        try:
            clock_in_parts = attendance.clock_in.split(":")
            clock_out_parts = data.clock_out.split(":")
            in_minutes = int(clock_in_parts[0]) * 60 + int(clock_in_parts[1])
            out_minutes = int(clock_out_parts[0]) * 60 + int(clock_out_parts[1])
            
            # 日をまたぐ場合
            if out_minutes < in_minutes:
                out_minutes += 24 * 60
            
            hours_worked = (out_minutes - in_minutes) / 60
            attendance.hours_worked = round(hours_worked, 2)
            
            # 日給を計算
            if staff:
                if staff.salary_type == "hourly":
                    attendance.daily_wage = int(staff.salary_amount * hours_worked)
                elif staff.salary_type == "daily":
                    attendance.daily_wage = staff.salary_amount
                elif staff.salary_type == "monthly":
                    # 月給の場合、1日あたり = 月給 / 25日
                    attendance.daily_wage = int(staff.salary_amount / 25)
        except:
            pass
    
    db.commit()
    db.refresh(attendance)
    return attendance

@app.get("/api/staff-attendance/today-total")
def get_today_staff_cost(db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    """今日のスタッフ人件費合計を取得"""
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    
    query = db.query(StaffAttendance).filter(StaffAttendance.date == today)
    if store_id:
        query = query.filter(StaffAttendance.store_id == store_id)
    attendances = query.all()
    total_cost = sum(att.daily_wage or 0 for att in attendances)
    
    return {
        "date": today,
        "total_staff_cost": total_cost,
        "staff_count": len(attendances)
    }

# 店舗設定API
class StoreSettingsResponse(BaseModel):
    id: int
    name: str
    business_start_hour: int = 18
    business_end_hour: int = 6
    class Config:
        from_attributes = True

class StoreSettingsUpdate(BaseModel):
    business_start_hour: Optional[int] = None
    business_end_hour: Optional[int] = None
    business_start_minutes: Optional[int] = None
    business_end_minutes: Optional[int] = None
    manager_pin: Optional[str] = None
    staff_pin: Optional[str] = None
    csv_export_enabled: Optional[bool] = None

@app.get("/api/store/settings")
def get_store_settings(db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    """店舗設定を取得"""
    if not store_id:
        return {
            "business_start_hour": 18, 
            "business_end_hour": 6,
            "business_start_minutes": 1080,
            "business_end_minutes": 360
        }
    
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        return {
            "business_start_hour": 18, 
            "business_end_hour": 6,
            "business_start_minutes": 1080,
            "business_end_minutes": 360
        }
    
    return {
        "id": store.id,
        "name": store.name,
        "business_start_hour": store.business_start_hour or 18,
        "business_end_hour": store.business_end_hour or 6,
        "business_start_minutes": store.business_start_minutes if store.business_start_minutes is not None else (store.business_start_hour or 18) * 60,
        "business_end_minutes": store.business_end_minutes if store.business_end_minutes is not None else (store.business_end_hour or 6) * 60,
        "has_manager_pin": bool(store.manager_pin),
        "has_staff_pin": bool(store.staff_pin),
        "csv_export_enabled": bool(store.csv_export_enabled)
    }

@app.put("/api/store/settings")
def update_store_settings(settings: StoreSettingsUpdate, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    """店舗設定を更新"""
    if not store_id:
        raise HTTPException(status_code=400, detail="Store ID required")
    
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # 旧形式（時間単位）
    if settings.business_start_hour is not None:
        store.business_start_hour = settings.business_start_hour
    if settings.business_end_hour is not None:
        store.business_end_hour = settings.business_end_hour
    
    # 新形式（分単位・15分刻み）
    if settings.business_start_minutes is not None:
        store.business_start_minutes = settings.business_start_minutes
        # 時間単位も同期
        store.business_start_hour = settings.business_start_minutes // 60
    if settings.business_end_minutes is not None:
        store.business_end_minutes = settings.business_end_minutes
        # 時間単位も同期
        store.business_end_hour = settings.business_end_minutes // 60
    
    # PIN設定（ハッシュ化して保存）
    if settings.manager_pin is not None:
        store.manager_pin = get_password_hash(settings.manager_pin) if settings.manager_pin else None
    if settings.staff_pin is not None:
        store.staff_pin = get_password_hash(settings.staff_pin) if settings.staff_pin else None

    # CSVエクスポート設定
    if settings.csv_export_enabled is not None:
        store.csv_export_enabled = settings.csv_export_enabled

    db.commit()
    return {
        "message": "設定を更新しました",
        "business_start_hour": store.business_start_hour,
        "business_end_hour": store.business_end_hour,
        "business_start_minutes": store.business_start_minutes,
        "business_end_minutes": store.business_end_minutes,
        "has_manager_pin": bool(store.manager_pin),
        "has_staff_pin": bool(store.staff_pin),
        "csv_export_enabled": bool(store.csv_export_enabled)
    }

# メニュー管理
@app.get("/api/menu", response_model=List[MenuItemResponse])
def get_menu(db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    query = db.query(MenuItem)
    if store_id:
        query = query.filter(MenuItem.store_id == store_id)
    return query.all()

@app.post("/api/menu", response_model=MenuItemResponse)
def create_menu_item(item: MenuItemCreate, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    db_item = MenuItem(**item.dict(), store_id=store_id)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

@app.put("/api/menu/{item_id}", response_model=MenuItemResponse)
def update_menu_item(item_id: int, item: MenuItemUpdate, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    query = db.query(MenuItem).filter(MenuItem.id == item_id)
    if store_id:
        query = query.filter(MenuItem.store_id == store_id)
    db_item = query.first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    for key, value in item.dict(exclude_unset=True).items():
        setattr(db_item, key, value)
    db.commit()
    db.refresh(db_item)
    return db_item

@app.delete("/api/menu/{item_id}")
def delete_menu_item(item_id: int, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    query = db.query(MenuItem).filter(MenuItem.id == item_id)
    if store_id:
        query = query.filter(MenuItem.store_id == store_id)
    db_item = query.first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    db.delete(db_item)
    db.commit()
    return {"message": "Menu item deleted"}

# テーブル管理
@app.get("/api/tables", response_model=List[TableResponse])
def get_tables(db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    query = db.query(Table)
    if store_id:
        query = query.filter(Table.store_id == store_id)
    return query.all()

@app.post("/api/tables", response_model=TableResponse)
def create_table(table: TableCreate, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    # 同名テーブルチェック（同一店舗内）
    query = db.query(Table).filter(Table.name == table.name)
    if store_id:
        query = query.filter(Table.store_id == store_id)
    existing = query.first()
    if existing:
        raise HTTPException(status_code=400, detail="同じ名前のテーブルが既に存在します")
    
    db_table = Table(name=table.name, is_vip=table.is_vip, status="available", store_id=store_id)
    db.add(db_table)
    db.commit()
    db.refresh(db_table)
    return db_table

@app.put("/api/tables/{table_id}", response_model=TableResponse)
def update_table(table_id: int, table: TableCreate, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    query = db.query(Table).filter(Table.id == table_id)
    if store_id:
        query = query.filter(Table.store_id == store_id)
    db_table = query.first()
    if not db_table:
        raise HTTPException(status_code=404, detail="テーブルが見つかりません")
    
    # 同名テーブルチェック（自分以外、同一店舗内）
    name_query = db.query(Table).filter(Table.name == table.name, Table.id != table_id)
    if store_id:
        name_query = name_query.filter(Table.store_id == store_id)
    existing = name_query.first()
    if existing:
        raise HTTPException(status_code=400, detail="同じ名前のテーブルが既に存在します")
    
    db_table.name = table.name
    db_table.is_vip = table.is_vip
    db.commit()
    db.refresh(db_table)
    return db_table

@app.delete("/api/tables/{table_id}")
def delete_table(table_id: int, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    query = db.query(Table).filter(Table.id == table_id)
    if store_id:
        query = query.filter(Table.store_id == store_id)
    db_table = query.first()
    if not db_table:
        raise HTTPException(status_code=404, detail="テーブルが見つかりません")
    
    # 使用中のテーブルは削除不可
    if db_table.status == "occupied":
        raise HTTPException(status_code=400, detail="使用中のテーブルは削除できません")
    
    # アクティブなセッションがあるか確認
    active_session = db.query(SessionModel).filter(
        SessionModel.table_id == table_id,
        SessionModel.status == "active"
    ).first()
    if active_session:
        raise HTTPException(status_code=400, detail="アクティブなセッションがあるテーブルは削除できません")
    
    db.delete(db_table)
    db.commit()
    return {"message": "テーブルを削除しました"}

# セッション管理
@app.post("/api/sessions", response_model=SessionResponse)
def create_session(session: SessionCreate, db: Session = Depends(get_db), _auth: dict = Depends(verify_token)):
    # ボディからstore_idを取得
    store_id = session.store_id
    
    session_data = session.dict()
    
    # PostgreSQL対応: cast_id=0の場合はNoneに（外部キー制約対策）
    if session_data.get('cast_id') == 0:
        session_data['cast_id'] = None
    
    db_session = SessionModel(**session_data)
    db.add(db_session)
    table = db.query(Table).filter(Table.id == session.table_id).first()
    if table:
        table.status = "occupied"
    db.commit()
    db.refresh(db_session)
    return db_session

@app.get("/api/sessions/active", response_model=List[SessionResponse])
def get_active_sessions(db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    query = db.query(SessionModel).filter(SessionModel.status == "active")
    if store_id:
        query = query.filter(SessionModel.store_id == store_id)
    return query.all()

@app.get("/api/sessions/{session_id}/orders")
def get_session_orders(session_id: int, db: Session = Depends(get_db), _auth: dict = Depends(verify_token)):
    """特定セッションの注文を取得"""
    orders = db.query(Order).filter(Order.session_id == session_id).all()
    result = []
    for order in orders:
        menu_item = db.query(MenuItem).filter(MenuItem.id == order.menu_item_id).first() if order.menu_item_id else None
        # 保存されたitem_nameを優先、なければmenu_item.name、それもなければcast_nameか"料金"
        item_name = order.item_name or (menu_item.name if menu_item else None) or order.cast_name or "料金"
        result.append({
            "id": order.id,
            "session_id": order.session_id,
            "menu_item_id": order.menu_item_id,
            "item_name": item_name,
            "quantity": order.quantity,
            "price": order.price,
            "is_drink_back": order.is_drink_back,
            "cast_name": order.cast_name if menu_item else None,
            "is_served": order.is_served,
            "created_at": order.created_at.isoformat() if order.created_at else None
        })
    return result

@app.post("/api/sessions/{session_id}/call-staff")
def call_staff(session_id: int, db: Session = Depends(get_db), _auth: dict = Depends(verify_token)):
    """スタッフ呼び出し"""
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    # 実際のシステムでは通知を送るなどの処理を行う
    print(f"🔔 スタッフ呼び出し: セッション {session_id}")
    return {"message": "Staff called", "session_id": session_id}

@app.post("/api/sessions/{session_id}/extend")
def extend_session(session_id: int, db: Session = Depends(get_db), _auth: dict = Depends(verify_token)):
    """セッションを延長"""
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # 延長回数を増やす
    session.extension_count = (session.extension_count or 0) + 1
    
    # 場内指名料を自動追加（既存の場内指名を探す）
    nomination_orders = db.query(Order).filter(
        Order.session_id == session_id,
        Order.cast_name.like("場内指名料%")
    ).all()
    
    added_nominations = []
    for nom_order in nomination_orders:
        # 同じ指名を延長分として追加（重複チェック：延長回数と同じ数だけ追加されるべき）
        # 既に追加された指名の数をカウント
        existing_count = db.query(Order).filter(
            Order.session_id == session_id,
            Order.cast_name == nom_order.cast_name
        ).count()
        
        # 延長回数+1（最初の1回含む）より少なければ追加
        if existing_count < (session.extension_count + 1):
            new_order = Order(
                session_id=session_id,
                store_id=session.store_id,
                menu_item_id=None,
                quantity=1,
                price=nom_order.price,
                is_drink_back=False,
                is_served=True,
                cast_name=nom_order.cast_name
            )
            db.add(new_order)
            session.current_total = (session.current_total or 0) + nom_order.price
            added_nominations.append(nom_order.cast_name)
    
    db.commit()
    db.refresh(session)
    
    return {
        "message": "Session extended",
        "extension_count": session.extension_count,
        "added_nominations": added_nominations
    }

# 精算ロック
class SettlingRequest(BaseModel):
    staff_name: str

@app.post("/api/sessions/{session_id}/settling/start")
def start_settling(session_id: int, req: SettlingRequest, db: Session = Depends(get_db), _auth: dict = Depends(verify_token)):
    """精算ロック開始"""
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # 既にロック中で180秒以内なら拒否
    if session.is_settling and session.settling_at:
        elapsed = (datetime.utcnow() - session.settling_at).total_seconds()
        if elapsed < 180:
            raise HTTPException(
                status_code=409, 
                detail=f"{session.settling_by}さんが精算中です（残り{180 - int(elapsed)}秒）"
            )
    
    # ロック設定
    session.is_settling = True
    session.settling_by = req.staff_name
    session.settling_at = datetime.utcnow()
    db.commit()
    
    return {"message": "精算ロック開始", "settling_by": req.staff_name}

@app.post("/api/sessions/{session_id}/settling/cancel")
def cancel_settling(session_id: int, db: Session = Depends(get_db), _auth: dict = Depends(verify_token)):
    """精算ロック解除"""
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session.is_settling = False
    session.settling_by = None
    session.settling_at = None
    db.commit()
    
    return {"message": "精算ロック解除"}

@app.post("/api/sessions/{session_id}/settling/force-cancel")
def force_cancel_settling(session_id: int, db: Session = Depends(get_db), _auth: dict = Depends(verify_token)):
    """精算ロック強制解除（管理者用）"""
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session.is_settling = False
    session.settling_by = None
    session.settling_at = None
    db.commit()
    
    return {"message": "精算ロック強制解除完了"}

@app.put("/api/sessions/{session_id}/checkout")
def checkout_session(session_id: int, db: Session = Depends(get_db), _auth: dict = Depends(verify_token)):
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.status = "completed"
    session.end_time = datetime.utcnow()
    # 精算ロック解除
    session.is_settling = False
    session.settling_by = None
    session.settling_at = None
    if session.table:
        session.table.status = "available"
    db.commit()
    return {"message": "Session checked out"}

@app.post("/api/sessions/{session_id}/add-charge")
def add_charge_to_session(session_id: int, charge: dict, db: Session = Depends(get_db), _auth: dict = Depends(verify_token)):
    """セッションに料金を追加（セット料金、指名料等）"""
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    item_name = charge.get("item_name", "料金")
    price = charge.get("price", 0)
    quantity = charge.get("quantity", 1)
    
    # 注文として記録（menu_item_idはNone）
    db_order = Order(
        session_id=session_id,
        store_id=session.store_id,
        menu_item_id=None,
        quantity=quantity,
        price=price,
        is_drink_back=False,
        is_served=True,  # 料金系は即提供済み
        cast_name=item_name  # item_nameをcast_nameに一時保存
    )
    db.add(db_order)
    
    # セッション合計を更新
    session.current_total = (session.current_total or 0) + (price * quantity)
    
    db.commit()
    db.refresh(db_order)
    
    return {
        "message": "Charge added",
        "order_id": db_order.id,
        "item_name": item_name,
        "price": price,
        "quantity": quantity,
        "session_total": session.current_total
    }

# 注文管理
@app.get("/api/orders")
def get_orders(db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    """全注文を取得（テーブル名、メニュー名付き）- JOIN最適化版"""
    from sqlalchemy.orm import joinedload
    from sqlalchemy import outerjoin
    
    # JOINで一括取得（N+1問題解消）
    query = db.query(
        Order,
        SessionModel.table_id,
        Table.name.label('table_name'),
        MenuItem.name.label('menu_name')
    ).outerjoin(
        SessionModel, Order.session_id == SessionModel.id
    ).outerjoin(
        Table, SessionModel.table_id == Table.id
    ).outerjoin(
        MenuItem, Order.menu_item_id == MenuItem.id
    )
    
    # store_idでフィルタ
    if store_id:
        query = query.filter(SessionModel.store_id == store_id)
    
    result = []
    for order, table_id, table_name, menu_name in query.all():
        # DBに保存されたitem_nameを優先、なければmenu_name、それもなければcast_nameか"料金"
        item_name = order.item_name or menu_name or order.cast_name or "料金"
        
        result.append({
            "id": order.id,
            "session_id": order.session_id,
            "table_id": table_id,
            "table_name": table_name or "?",
            "menu_item_id": order.menu_item_id,
            "item_name": item_name,
            "quantity": order.quantity,
            "price": order.price,
            "is_drink_back": order.is_drink_back,
            "cast_name": order.cast_name if order.menu_item_id else None,
            "is_served": order.is_served,
            "created_at": order.created_at.isoformat() if order.created_at else None
        })
    return result

@app.post("/api/orders")
def create_order(order: OrderCreate, db: Session = Depends(get_db), _auth: dict = Depends(verify_token)):
    menu_item = db.query(MenuItem).filter(MenuItem.id == order.menu_item_id).first()
    if not menu_item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    
    # カスタム商品名があればそれを使う、なければメニューの名前
    final_item_name = order.item_name if order.item_name else menu_item.name
    
    # カスタム価格があればそれを使う、なければメニューの価格
    final_price = order.custom_price if order.custom_price is not None else menu_item.price
    
    db_order = Order(
        session_id=order.session_id,
        menu_item_id=order.menu_item_id,
        item_name=final_item_name,
        quantity=order.quantity,
        price=final_price,
        is_drink_back=order.is_drink_back,
        cast_name=order.cast_name
    )
    db.add(db_order)
    session = db.query(SessionModel).filter(SessionModel.id == order.session_id).first()
    if session:
        session.current_total += final_price * order.quantity
    db.commit()
    db.refresh(db_order)
    return db_order

@app.put("/api/orders/{order_id}/serve")
def mark_order_served(order_id: int, db: Session = Depends(get_db), _auth: dict = Depends(verify_token)):
    """注文を提供済みにする"""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    order.is_served = True
    db.commit()
    return {"message": "Order marked as served", "id": order_id}

@app.put("/api/sessions/{session_id}/orders/{order_id}/status")
def update_order_status(session_id: int, order_id: int, status_data: dict, db: Session = Depends(get_db), _auth: dict = Depends(verify_token)):
    """注文のステータスを更新（提供済み/未提供）"""
    order = db.query(Order).filter(Order.id == order_id, Order.session_id == session_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    is_served = status_data.get("is_served", False)
    order.is_served = is_served
    db.commit()
    
    return {
        "message": "Order status updated",
        "order_id": order_id,
        "is_served": is_served
    }

# 勤怠管理
@app.post("/api/attendance/clock-in")
def clock_in(attendance: AttendanceCreate, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    attendance_data = attendance.dict()
    attendance_data['store_id'] = store_id
    db_attendance = Attendance(**attendance_data, status="working")
    db.add(db_attendance)
    db.commit()
    db.refresh(db_attendance)
    return db_attendance

@app.put("/api/attendance/{attendance_id}/clock-out")
def clock_out(attendance_id: int, data: AttendanceClockOut, db: Session = Depends(get_db), _auth: dict = Depends(verify_token)):
    attendance = db.query(Attendance).filter(Attendance.id == attendance_id).first()
    if not attendance:
        raise HTTPException(status_code=404, detail="Attendance not found")
    attendance.clock_out = data.clock_out
    attendance.status = "completed"
    db.commit()
    return attendance

@app.get("/api/attendance")
def get_attendance(date: Optional[str] = None, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    query = db.query(Attendance)
    if date:
        query = query.filter(Attendance.date == date)
    if store_id:
        query = query.filter(Attendance.store_id == store_id)
    return query.all()

# シフト管理
@app.post("/api/shifts")
def create_shift(shift: ShiftCreate, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    shift_data = shift.dict()
    shift_data['store_id'] = store_id
    db_shift = Shift(**shift_data)
    db.add(db_shift)
    db.commit()
    db.refresh(db_shift)
    return db_shift

@app.get("/api/shifts")
def get_shifts(date: Optional[str] = None, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    query = db.query(Shift)
    if date:
        query = query.filter(Shift.date == date)
    if store_id:
        query = query.filter(Shift.store_id == store_id)
    return query.all()

# 日報
@app.get("/api/daily-report")
def get_daily_report(date: Optional[str] = None, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    """日報データを取得（粗利計算含む）"""
    target_date = date or datetime.utcnow().strftime("%Y-%m-%d")
    
    # その日のセッション（店舗フィルタ）
    session_query = db.query(SessionModel).filter(
        SessionModel.start_time >= f"{target_date} 00:00:00",
        SessionModel.start_time <= f"{target_date} 23:59:59"
    )
    if store_id:
        session_query = session_query.filter(SessionModel.store_id == store_id)
    sessions = session_query.all()
    
    # 売上計算
    total_sales = 0
    total_guests = 0
    session_count = len(sessions)
    
    for session in sessions:
        total_sales += session.current_total or 0
        total_guests += session.guests or 0
    
    # その日の注文（セッション経由で店舗フィルタ）
    session_ids = [s.id for s in sessions]
    if session_ids:
        orders = db.query(Order).filter(
            Order.created_at >= f"{target_date} 00:00:00",
            Order.created_at <= f"{target_date} 23:59:59",
            Order.session_id.in_(session_ids)
        ).all()
    else:
        orders = []
    
    # 原価計算
    total_cost = 0
    for order in orders:
        if order.menu_item and order.menu_item.cost:
            total_cost += order.menu_item.cost * order.quantity
    
    # キャスト情報を取得（店舗フィルタ）
    cast_query = db.query(Cast)
    if store_id:
        cast_query = cast_query.filter(Cast.store_id == store_id)
    casts = cast_query.all()
    cast_dict = {c.stage_name: c for c in casts}
    
    # ===== キャストバック計算 =====
    # 1. 同伴バック
    companion_back_total = 0
    for session in sessions:
        if session.has_companion and session.companion_name:
            cast = cast_dict.get(session.companion_name)
            if cast:
                companion_back_total += cast.companion_back or 0
    
    # 2. 指名バック
    nomination_back_total = 0
    for session in sessions:
        if session.nomination_type and session.shimei_casts:
            cast_names = session.shimei_casts.split(',')
            for cast_name in cast_names:
                cast_name = cast_name.strip()
                cast = cast_dict.get(cast_name)
                if cast:
                    nomination_back_total += cast.nomination_back or 0
    
    # 3. ドリンクバック（ドリンク売上 × キャストのドリンクバック率）
    drink_back_total = 0
    for order in orders:
        if order.is_drink_back and order.cast_name:
            cast = cast_dict.get(order.cast_name)
            if cast:
                drink_back_rate = cast.drink_back_rate or 10
                drink_back_total += int(order.price * order.quantity * drink_back_rate / 100)
    
    # 4. 売上バック（キャストの売上 × 売上バック率）
    sales_back_total = 0
    cast_sales = {}  # キャストごとの売上を集計
    for session in sessions:
        if session.cast:
            cast_name = session.cast.stage_name
            if cast_name not in cast_sales:
                cast_sales[cast_name] = 0
            cast_sales[cast_name] += session.current_total or 0
    
    for cast_name, sales in cast_sales.items():
        cast = cast_dict.get(cast_name)
        if cast and cast.sales_back_rate:
            sales_back_total += int(sales * cast.sales_back_rate / 100)
    
    # キャストバック合計
    cast_payroll_total = companion_back_total + nomination_back_total + drink_back_total + sales_back_total
    
    # スタッフ人件費（店舗フィルタ）
    staff_att_query = db.query(StaffAttendance).filter(StaffAttendance.date == target_date)
    if store_id:
        staff_att_query = staff_att_query.filter(StaffAttendance.store_id == store_id)
    staff_attendances = staff_att_query.all()
    staff_cost_total = sum(att.daily_wage or 0 for att in staff_attendances)
    
    # 粗利 = 売上 - 原価 - キャストバック - スタッフ人件費
    gross_profit = total_sales - total_cost - cast_payroll_total - staff_cost_total
    
    # その日の勤怠（店舗フィルタ）
    att_query = db.query(Attendance).filter(Attendance.date == target_date)
    if store_id:
        att_query = att_query.filter(Attendance.store_id == store_id)
    attendances = att_query.all()
    
    return {
        "date": target_date,
        "session_count": session_count,
        "total_guests": total_guests,
        "total_sales": total_sales,
        "total_cost": total_cost,
        "cast_payroll": {
            "companion_back": companion_back_total,
            "nomination_back": nomination_back_total,
            "drink_back": drink_back_total,
            "sales_back": sales_back_total,
            "total": cast_payroll_total
        },
        "staff_cost": staff_cost_total,
        "gross_profit": gross_profit,
        "drink_back_total": drink_back_total,  # 後方互換性
        "order_count": len(orders),
        "attendance_count": len(attendances),
        "sessions": [
            {
                "id": s.id,
                "table_id": s.table_id,
                "cast_id": s.cast_id,
                "cast_name": s.cast.stage_name if s.cast else None,
                "guests": s.guests,
                "total": s.current_total,
                "has_companion": s.has_companion,
                "companion_name": s.companion_name,
                "nomination_type": s.nomination_type,
                "shimei_casts": s.shimei_casts,
                "status": s.status
            } for s in sessions
        ]
    }

@app.get("/api/daily-report/cast-ranking")
def get_cast_ranking(date: Optional[str] = None, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    """キャストランキングを取得"""
    target_date = date or datetime.utcnow().strftime("%Y-%m-%d")
    
    # まず店舗のセッションを取得
    session_query = db.query(SessionModel).filter(
        SessionModel.start_time >= f"{target_date} 00:00:00",
        SessionModel.start_time <= f"{target_date} 23:59:59"
    )
    if store_id:
        session_query = session_query.filter(SessionModel.store_id == store_id)
    session_ids = [s.id for s in session_query.all()]
    
    # その日のドリンクバック注文を集計（店舗フィルタ）
    if session_ids:
        orders = db.query(Order).filter(
            Order.created_at >= f"{target_date} 00:00:00",
            Order.created_at <= f"{target_date} 23:59:59",
            Order.is_drink_back == True,
            Order.session_id.in_(session_ids)
        ).all()
    else:
        orders = []
    
    # キャストごとに集計
    cast_totals = {}
    for order in orders:
        if order.cast_name:
            if order.cast_name not in cast_totals:
                cast_totals[order.cast_name] = {"drink_back": 0, "count": 0}
            cast_totals[order.cast_name]["drink_back"] += order.price * order.quantity
            cast_totals[order.cast_name]["count"] += order.quantity
    
    # ランキング形式に変換
    ranking = [
        {"cast_name": name, "drink_back": data["drink_back"], "count": data["count"]}
        for name, data in cast_totals.items()
    ]
    ranking.sort(key=lambda x: x["drink_back"], reverse=True)
    
    return {"date": target_date, "ranking": ranking}

# 月次レポート
@app.get("/api/monthly-report")
def get_monthly_report(year: Optional[int] = None, month: Optional[int] = None, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    """月次レポートデータを取得"""
    from calendar import monthrange
    
    now = datetime.utcnow()
    target_year = year or now.year
    target_month = month or now.month
    
    # 月の開始日と終了日
    start_date = f"{target_year}-{target_month:02d}-01"
    last_day = monthrange(target_year, target_month)[1]
    end_date = f"{target_year}-{target_month:02d}-{last_day}"
    
    # 月間のセッション（店舗フィルタ）
    session_query = db.query(SessionModel).filter(
        SessionModel.start_time >= f"{start_date} 00:00:00",
        SessionModel.start_time <= f"{end_date} 23:59:59"
    )
    if store_id:
        session_query = session_query.filter(SessionModel.store_id == store_id)
    sessions = session_query.all()
    
    # 売上計算
    total_sales = 0
    total_guests = 0
    session_count = len(sessions)
    companion_count = 0
    nomination_count = 0
    extension_count = 0
    
    for session in sessions:
        total_sales += session.current_total or 0
        total_guests += session.guests or 0
        if session.has_companion:
            companion_count += 1
        if session.nomination_type:
            nomination_count += 1
        extension_count += session.extension_count or 0
    
    # 月間の注文（店舗フィルタ）
    session_ids = [s.id for s in sessions]
    if session_ids:
        orders = db.query(Order).filter(
            Order.created_at >= f"{start_date} 00:00:00",
            Order.created_at <= f"{end_date} 23:59:59",
            Order.session_id.in_(session_ids)
        ).all()
    else:
        orders = []
    
    # 原価計算
    total_cost = 0
    for order in orders:
        if order.menu_item and order.menu_item.cost:
            total_cost += order.menu_item.cost * order.quantity
    
    # キャスト情報を取得（店舗フィルタ）
    cast_query = db.query(Cast)
    if store_id:
        cast_query = cast_query.filter(Cast.store_id == store_id)
    casts = cast_query.all()
    cast_dict = {c.stage_name: c for c in casts}
    
    # ===== キャストバック計算 =====
    companion_back_total = 0
    nomination_back_total = 0
    drink_back_total = 0
    sales_back_total = 0
    
    # 同伴バック
    for session in sessions:
        if session.has_companion and session.companion_name:
            cast = cast_dict.get(session.companion_name)
            if cast:
                companion_back_total += cast.companion_back or 0
    
    # 指名バック
    for session in sessions:
        if session.nomination_type and session.shimei_casts:
            cast_names = session.shimei_casts.split(',')
            for cast_name in cast_names:
                cast_name = cast_name.strip()
                cast = cast_dict.get(cast_name)
                if cast:
                    nomination_back_total += cast.nomination_back or 0
    
    # ドリンクバック
    for order in orders:
        if order.is_drink_back and order.cast_name:
            cast = cast_dict.get(order.cast_name)
            if cast:
                drink_back_rate = cast.drink_back_rate or 10
                drink_back_total += int(order.price * order.quantity * drink_back_rate / 100)
    
    # 売上バック
    cast_sales = {}
    for session in sessions:
        if session.cast:
            cast_name = session.cast.stage_name
            if cast_name not in cast_sales:
                cast_sales[cast_name] = 0
            cast_sales[cast_name] += session.current_total or 0
    
    for cast_name, sales in cast_sales.items():
        cast = cast_dict.get(cast_name)
        if cast and cast.sales_back_rate:
            sales_back_total += int(sales * cast.sales_back_rate / 100)
    
    cast_payroll_total = companion_back_total + nomination_back_total + drink_back_total + sales_back_total
    
    # スタッフ人件費（月間・店舗フィルタ）
    staff_att_query = db.query(StaffAttendance).filter(
        StaffAttendance.date >= start_date,
        StaffAttendance.date <= end_date
    )
    if store_id:
        staff_att_query = staff_att_query.filter(StaffAttendance.store_id == store_id)
    staff_attendances = staff_att_query.all()
    staff_cost_total = sum(att.daily_wage or 0 for att in staff_attendances)
    
    # 粗利
    gross_profit = total_sales - total_cost - cast_payroll_total - staff_cost_total
    
    # 日別売上データ（グラフ用）
    daily_sales = {}
    for day in range(1, last_day + 1):
        date_str = f"{target_year}-{target_month:02d}-{day:02d}"
        daily_sales[date_str] = 0
    
    for session in sessions:
        if session.start_time:
            date_str = session.start_time.strftime("%Y-%m-%d")
            if date_str in daily_sales:
                daily_sales[date_str] += session.current_total or 0
    
    # キャスト成績ランキング
    cast_stats = {}
    for session in sessions:
        if session.cast:
            cast_name = session.cast.stage_name
            if cast_name not in cast_stats:
                cast_stats[cast_name] = {
                    "name": cast_name,
                    "sales": 0,
                    "nominations": 0,
                    "companions": 0,
                    "drink_count": 0
                }
            cast_stats[cast_name]["sales"] += session.current_total or 0
            if session.nomination_type:
                cast_stats[cast_name]["nominations"] += 1
            if session.has_companion and session.companion_name == cast_name:
                cast_stats[cast_name]["companions"] += 1
    
    # ドリンクバック回数を集計
    for order in orders:
        if order.is_drink_back and order.cast_name and order.cast_name in cast_stats:
            cast_stats[order.cast_name]["drink_count"] += order.quantity
    
    cast_ranking = sorted(cast_stats.values(), key=lambda x: x["sales"], reverse=True)
    
    return {
        "year": target_year,
        "month": target_month,
        "period": f"{target_year}年{target_month}月",
        "session_count": session_count,
        "total_guests": total_guests,
        "total_sales": total_sales,
        "total_cost": total_cost,
        "companion_count": companion_count,
        "nomination_count": nomination_count,
        "extension_count": extension_count,
        "cast_payroll": {
            "companion_back": companion_back_total,
            "nomination_back": nomination_back_total,
            "drink_back": drink_back_total,
            "sales_back": sales_back_total,
            "total": cast_payroll_total
        },
        "staff_cost": staff_cost_total,
        "gross_profit": gross_profit,
        "gross_profit_rate": round(gross_profit / total_sales * 100, 1) if total_sales > 0 else 0,
        "avg_per_group": round(total_sales / session_count) if session_count > 0 else 0,
        "avg_per_person": round(total_sales / total_guests) if total_guests > 0 else 0,
        "daily_sales": [{"date": k, "sales": v} for k, v in sorted(daily_sales.items())],
        "cast_ranking": cast_ranking
    }

# キャスト給与計算
@app.get("/api/cast-payroll")
def get_cast_payroll(year: Optional[int] = None, month: Optional[int] = None, cast_id: Optional[int] = None, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    """キャスト給与明細を取得"""
    from calendar import monthrange
    
    now = datetime.utcnow()
    target_year = year or now.year
    target_month = month or now.month
    
    # 月の開始日と終了日
    start_date = f"{target_year}-{target_month:02d}-01"
    last_day = monthrange(target_year, target_month)[1]
    end_date = f"{target_year}-{target_month:02d}-{last_day}"
    
    # キャスト取得（店舗フィルタ）
    cast_query = db.query(Cast)
    if cast_id:
        cast_query = cast_query.filter(Cast.id == cast_id)
    if store_id:
        cast_query = cast_query.filter(Cast.store_id == store_id)
    casts = cast_query.all()
    
    payroll_list = []
    
    for cast in casts:
        # 出勤記録（店舗フィルタ）
        att_query = db.query(Attendance).filter(
            Attendance.cast_id == cast.id,
            Attendance.date >= start_date,
            Attendance.date <= end_date
        )
        if store_id:
            att_query = att_query.filter(Attendance.store_id == store_id)
        attendances = att_query.all()
        
        # 勤務時間計算
        total_hours = 0
        work_days = len(attendances)
        for att in attendances:
            if att.clock_in and att.clock_out:
                try:
                    clock_in = datetime.strptime(att.clock_in, "%H:%M")
                    clock_out = datetime.strptime(att.clock_out, "%H:%M")
                    # 深夜跨ぎ対応
                    if clock_out < clock_in:
                        clock_out = clock_out + timedelta(hours=24)
                    hours = (clock_out - clock_in).total_seconds() / 3600
                    total_hours += hours
                except:
                    pass
        
        # 基本給計算
        if cast.salary_type == "monthly":
            base_salary = cast.monthly_salary or 0
        else:
            base_salary = int((cast.hourly_rate or 0) * total_hours)
        
        # セッション取得（店舗フィルタ）
        session_query = db.query(SessionModel).filter(
            SessionModel.cast_id == cast.id,
            SessionModel.start_time >= f"{start_date} 00:00:00",
            SessionModel.start_time <= f"{end_date} 23:59:59"
        )
        if store_id:
            session_query = session_query.filter(SessionModel.store_id == store_id)
        sessions = session_query.all()
        
        # 同伴バック
        companion_count = 0
        companion_back = 0
        for session in sessions:
            if session.has_companion and session.companion_name == cast.stage_name:
                companion_count += 1
                companion_back += cast.companion_back or 0
        
        # 指名バック
        nomination_count = 0
        nomination_back = 0
        for session in sessions:
            if session.nomination_type:
                nomination_count += 1
                nomination_back += cast.nomination_back or 0
        
        # ドリンクバック（店舗のセッション経由でフィルタ）
        session_ids = [s.id for s in sessions]
        if session_ids:
            orders = db.query(Order).filter(
                Order.cast_name == cast.stage_name,
                Order.is_drink_back == True,
                Order.created_at >= f"{start_date} 00:00:00",
                Order.created_at <= f"{end_date} 23:59:59",
                Order.session_id.in_(session_ids)
            ).all()
        else:
            orders = []
        
        drink_sales = sum(o.price * o.quantity for o in orders)
        drink_back = int(drink_sales * (cast.drink_back_rate or 10) / 100)
        drink_count = sum(o.quantity for o in orders)
        
        # 売上バック
        total_sales = sum(s.current_total or 0 for s in sessions)
        sales_back = int(total_sales * (cast.sales_back_rate or 0) / 100)
        
        # 合計（紹介料は後で計算）
        total_payroll = base_salary + companion_back + nomination_back + drink_back + sales_back
        
        payroll_list.append({
            "cast_id": cast.id,
            "cast_name": cast.stage_name,
            "rank": cast.rank,
            "salary_type": cast.salary_type or "hourly",
            "period": f"{target_year}年{target_month}月",
            "work_days": work_days,
            "total_hours": round(total_hours, 1),
            "hourly_rate": cast.hourly_rate or 0,
            "monthly_salary": cast.monthly_salary or 0,
            "base_salary": base_salary,
            "companion_count": companion_count,
            "companion_back": companion_back,
            "nomination_count": nomination_count,
            "nomination_back": nomination_back,
            "drink_count": drink_count,
            "drink_sales": drink_sales,
            "drink_back": drink_back,
            "total_sales": total_sales,
            "sales_back": sales_back,
            "total_payroll": total_payroll
        })
    
    return {
        "year": target_year,
        "month": target_month,
        "period": f"{target_year}年{target_month}月",
        "payroll_list": payroll_list
    }

# 日払い給与計算（本日分）
@app.get("/api/daily-payroll")
def get_daily_payroll(date: Optional[str] = None, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    """日払いキャストの本日の給与を計算"""
    
    # 日付指定がなければ今日
    if date:
        target_date = date
    else:
        now = datetime.utcnow()
        target_date = now.strftime("%Y-%m-%d")
    
    # 日払いキャストのみ取得（店舗フィルタ）
    cast_query = db.query(Cast).filter(Cast.payment_type == "daily")
    if store_id:
        cast_query = cast_query.filter(Cast.store_id == store_id)
    daily_casts = cast_query.all()
    
    payroll_list = []
    total_daily_payroll = 0
    
    for cast in daily_casts:
        # 出勤記録
        att_query = db.query(Attendance).filter(
            Attendance.cast_id == cast.id,
            Attendance.date == target_date
        )
        if store_id:
            att_query = att_query.filter(Attendance.store_id == store_id)
        attendance = att_query.first()
        
        if not attendance:
            # 出勤していない場合はスキップ
            continue
        
        # 勤務時間計算
        work_hours = 0
        if attendance.clock_in and attendance.clock_out:
            try:
                clock_in = datetime.strptime(attendance.clock_in, "%H:%M")
                clock_out = datetime.strptime(attendance.clock_out, "%H:%M")
                # 深夜跨ぎ対応
                if clock_out < clock_in:
                    clock_out = clock_out + timedelta(hours=24)
                work_hours = (clock_out - clock_in).total_seconds() / 3600
            except:
                pass
        elif attendance.clock_in:
            # まだ退勤していない場合、現在時刻までで計算
            try:
                clock_in = datetime.strptime(attendance.clock_in, "%H:%M")
                now_time = datetime.utcnow()
                clock_out = datetime.strptime(now_time.strftime("%H:%M"), "%H:%M")
                if clock_out < clock_in:
                    clock_out = clock_out + timedelta(hours=24)
                work_hours = (clock_out - clock_in).total_seconds() / 3600
            except:
                pass
        
        # 基本給計算（時給 × 勤務時間）
        base_salary = int((cast.hourly_rate or 0) * work_hours)
        
        # セッション取得（その日の担当卓）
        session_query = db.query(SessionModel).filter(
            SessionModel.cast_id == cast.id,
            SessionModel.start_time >= f"{target_date} 00:00:00",
            SessionModel.start_time <= f"{target_date} 23:59:59"
        )
        if store_id:
            session_query = session_query.filter(SessionModel.store_id == store_id)
        sessions = session_query.all()
        
        # 同伴バック
        companion_count = 0
        companion_back = 0
        for session in sessions:
            if session.has_companion and session.companion_name == cast.stage_name:
                companion_count += 1
                companion_back += cast.companion_back or 0
        
        # 指名バック
        nomination_count = 0
        nomination_back = 0
        for session in sessions:
            if session.nomination_type:
                nomination_count += 1
                nomination_back += cast.nomination_back or 0
        
        # ドリンクバック
        session_ids = [s.id for s in sessions]
        if session_ids:
            orders = db.query(Order).filter(
                Order.cast_name == cast.stage_name,
                Order.is_drink_back == True,
                Order.created_at >= f"{target_date} 00:00:00",
                Order.created_at <= f"{target_date} 23:59:59",
                Order.session_id.in_(session_ids)
            ).all()
        else:
            # セッション経由じゃないドリンクバックも取得
            orders = db.query(Order).filter(
                Order.cast_name == cast.stage_name,
                Order.is_drink_back == True,
                Order.created_at >= f"{target_date} 00:00:00",
                Order.created_at <= f"{target_date} 23:59:59"
            ).all()
        
        drink_sales = sum(o.price * o.quantity for o in orders)
        drink_back = int(drink_sales * (cast.drink_back_rate or 10) / 100)
        drink_count = sum(o.quantity for o in orders)
        
        # 売上バック
        total_sales = sum(s.current_total or 0 for s in sessions)
        sales_back = int(total_sales * (cast.sales_back_rate or 0) / 100)
        
        # 合計
        total_payroll = base_salary + companion_back + nomination_back + drink_back + sales_back
        total_daily_payroll += total_payroll
        
        payroll_list.append({
            "cast_id": cast.id,
            "cast_name": cast.stage_name,
            "rank": cast.rank,
            "date": target_date,
            "clock_in": attendance.clock_in,
            "clock_out": attendance.clock_out,
            "work_hours": round(work_hours, 1),
            "hourly_rate": cast.hourly_rate or 0,
            "base_salary": base_salary,
            "companion_count": companion_count,
            "companion_back": companion_back,
            "nomination_count": nomination_count,
            "nomination_back": nomination_back,
            "drink_count": drink_count,
            "drink_sales": drink_sales,
            "drink_back": drink_back,
            "total_sales": total_sales,
            "sales_back": sales_back,
            "total_payroll": total_payroll
        })
    
    return {
        "date": target_date,
        "daily_cast_count": len(payroll_list),
        "total_daily_payroll": total_daily_payroll,
        "payroll_list": payroll_list
    }

# 紹介料管理API
@app.get("/api/referral-bonus")
def get_referral_bonus(year: Optional[int] = None, month: Optional[int] = None, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    """紹介者別の紹介料を集計"""
    from calendar import monthrange
    
    now = datetime.utcnow()
    target_year = year or now.year
    target_month = month or now.month
    
    # 月の開始日と終了日
    start_date = f"{target_year}-{target_month:02d}-01"
    last_day = monthrange(target_year, target_month)[1]
    end_date = f"{target_year}-{target_month:02d}-{last_day}"
    
    # 紹介者名があるキャストを取得
    cast_query = db.query(Cast).filter(Cast.referrer_name != None, Cast.referrer_name != "")
    if store_id:
        cast_query = cast_query.filter(Cast.store_id == store_id)
    casts_with_referrer = cast_query.all()
    
    # 紹介者別に集計
    referrer_data = {}
    
    for cast in casts_with_referrer:
        referrer = cast.referrer_name
        if not referrer:
            continue
            
        # その月に出勤しているか確認
        att_query = db.query(Attendance).filter(
            Attendance.cast_id == cast.id,
            Attendance.date >= start_date,
            Attendance.date <= end_date
        )
        if store_id:
            att_query = att_query.filter(Attendance.store_id == store_id)
        
        has_attendance = att_query.first() is not None
        
        if referrer not in referrer_data:
            referrer_data[referrer] = {
                "referrer_name": referrer,
                "casts": [],
                "total_bonus": 0,
                "active_bonus": 0  # 出勤ありのキャストの紹介料のみ
            }
        
        cast_info = {
            "cast_id": cast.id,
            "cast_name": cast.stage_name,
            "referral_bonus": cast.referral_bonus or 0,
            "has_attendance": has_attendance
        }
        
        referrer_data[referrer]["casts"].append(cast_info)
        referrer_data[referrer]["total_bonus"] += cast.referral_bonus or 0
        
        if has_attendance:
            referrer_data[referrer]["active_bonus"] += cast.referral_bonus or 0
    
    # リストに変換してソート
    referrer_list = sorted(referrer_data.values(), key=lambda x: x["active_bonus"], reverse=True)
    
    # 全体の合計
    total_referral_bonus = sum(r["active_bonus"] for r in referrer_list)
    
    return {
        "year": target_year,
        "month": target_month,
        "period": f"{target_year}年{target_month}月",
        "total_referral_bonus": total_referral_bonus,
        "referrer_count": len(referrer_list),
        "referrer_list": referrer_list
    }

# ========================
# 経費管理API
# ========================

@app.get("/api/expenses")
def get_expenses(
    year: Optional[int] = None,
    month: Optional[int] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    store_id: Optional[int] = Depends(get_store_id_from_token)
):
    """経費一覧取得（月別・カテゴリ別フィルタ対応）"""
    query = db.query(Expense)
    if store_id:
        query = query.filter(Expense.store_id == store_id)
    if year and month:
        start_date = f"{year}-{month:02d}-01"
        if month == 12:
            end_date = f"{year + 1}-01-01"
        else:
            end_date = f"{year}-{month + 1:02d}-01"
        query = query.filter(Expense.date >= start_date, Expense.date < end_date)
    if category:
        query = query.filter(Expense.category == category)
    expenses = query.order_by(Expense.date.desc()).all()

    result = []
    for e in expenses:
        result.append({
            "id": e.id,
            "store_id": e.store_id,
            "category": e.category,
            "category_label": EXPENSE_CATEGORIES.get(e.category, e.category),
            "description": e.description,
            "amount": e.amount,
            "date": e.date,
            "created_at": e.created_at.isoformat() if e.created_at else None
        })
    return result

@app.post("/api/expenses")
def create_expense(
    expense: ExpenseCreate,
    db: Session = Depends(get_db),
    store_id: Optional[int] = Depends(get_store_id_from_token)
):
    """経費を登録"""
    if expense.category not in EXPENSE_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category: {expense.category}")
    db_expense = Expense(
        store_id=store_id,
        category=expense.category,
        description=expense.description,
        amount=expense.amount,
        date=expense.date
    )
    db.add(db_expense)
    db.commit()
    db.refresh(db_expense)
    return {
        "id": db_expense.id,
        "category": db_expense.category,
        "category_label": EXPENSE_CATEGORIES.get(db_expense.category, ""),
        "description": db_expense.description,
        "amount": db_expense.amount,
        "date": db_expense.date
    }

@app.put("/api/expenses/{expense_id}")
def update_expense(
    expense_id: int,
    expense: ExpenseUpdate,
    db: Session = Depends(get_db),
    store_id: Optional[int] = Depends(get_store_id_from_token)
):
    """経費を更新"""
    query = db.query(Expense).filter(Expense.id == expense_id)
    if store_id:
        query = query.filter(Expense.store_id == store_id)
    db_expense = query.first()
    if not db_expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    update_data = expense.dict(exclude_unset=True)
    if 'category' in update_data and update_data['category'] not in EXPENSE_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category: {update_data['category']}")
    for key, value in update_data.items():
        setattr(db_expense, key, value)
    db.commit()
    db.refresh(db_expense)
    return {"message": "更新しました", "id": db_expense.id}

@app.delete("/api/expenses/{expense_id}")
def delete_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    store_id: Optional[int] = Depends(get_store_id_from_token)
):
    """経費を削除"""
    query = db.query(Expense).filter(Expense.id == expense_id)
    if store_id:
        query = query.filter(Expense.store_id == store_id)
    db_expense = query.first()
    if not db_expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    db.delete(db_expense)
    db.commit()
    return {"message": "削除しました"}

@app.get("/api/expenses/summary")
def get_expense_summary(
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: Session = Depends(get_db),
    store_id: Optional[int] = Depends(get_store_id_from_token)
):
    """経費のカテゴリ別集計"""
    now = datetime.utcnow()
    target_year = year or now.year
    target_month = month or now.month
    start_date = f"{target_year}-{target_month:02d}-01"
    if target_month == 12:
        end_date = f"{target_year + 1}-01-01"
    else:
        end_date = f"{target_year}-{target_month + 1:02d}-01"

    query = db.query(Expense).filter(Expense.date >= start_date, Expense.date < end_date)
    if store_id:
        query = query.filter(Expense.store_id == store_id)
    expenses = query.all()

    by_category = {}
    total = 0
    for e in expenses:
        label = EXPENSE_CATEGORIES.get(e.category, e.category)
        if e.category not in by_category:
            by_category[e.category] = {"category": e.category, "label": label, "total": 0, "count": 0}
        by_category[e.category]["total"] += e.amount
        by_category[e.category]["count"] += 1
        total += e.amount

    return {
        "year": target_year,
        "month": target_month,
        "total": total,
        "by_category": list(by_category.values())
    }

@app.get("/api/expense-categories")
def get_expense_categories(_auth: dict = Depends(verify_token)):
    """経費カテゴリ一覧"""
    return [{"value": k, "label": v} for k, v in EXPENSE_CATEGORIES.items()]

# ========================
# CSVエクスポートAPI
# ========================

from fastapi.responses import StreamingResponse
import csv
import io

@app.get("/api/export/sales")
def export_sales_csv(
    year: int, month: int,
    db: Session = Depends(get_db),
    store_id: Optional[int] = Depends(get_store_id_from_token)
):
    """売上データCSVエクスポート"""
    # CSVエクスポート権限チェック
    if store_id:
        store = db.query(Store).filter(Store.id == store_id).first()
        if store and not store.csv_export_enabled:
            raise HTTPException(status_code=403, detail="CSVエクスポートが無効です。店舗設定で有効にしてください。")

    from calendar import monthrange
    last_day = monthrange(year, month)[1]
    start_date = f"{year}-{month:02d}-01"
    end_date = f"{year}-{month:02d}-{last_day}"

    session_query = db.query(SessionModel).filter(
        SessionModel.start_time >= f"{start_date} 00:00:00",
        SessionModel.start_time <= f"{end_date} 23:59:59",
        SessionModel.status == "completed"
    )
    if store_id:
        session_query = session_query.filter(SessionModel.store_id == store_id)
    sessions = session_query.all()

    output = io.StringIO()
    output.write('\ufeff')  # BOM for Excel
    writer = csv.writer(output)
    writer.writerow(["日付", "テーブル", "来店人数", "担当キャスト", "小計", "TAX率(%)", "合計", "指名種別", "同伴"])

    for s in sessions:
        table = db.query(Table).filter(Table.id == s.table_id).first()
        cast = db.query(Cast).filter(Cast.id == s.cast_id).first() if s.cast_id else None
        tax_amount = int((s.current_total or 0) * (s.tax_rate or 20) / 100)
        total = (s.current_total or 0) + tax_amount
        writer.writerow([
            s.start_time.strftime("%Y-%m-%d %H:%M") if s.start_time else "",
            table.name if table else "",
            s.guests or 0,
            cast.stage_name if cast else "",
            s.current_total or 0,
            s.tax_rate or 20,
            total,
            s.nomination_type or "",
            "あり" if s.has_companion else ""
        ])

    output.seek(0)
    filename = f"sales_{year}{month:02d}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/api/export/payroll")
def export_payroll_csv(
    year: int, month: int,
    db: Session = Depends(get_db),
    store_id: Optional[int] = Depends(get_store_id_from_token)
):
    """キャスト給与CSVエクスポート"""
    if store_id:
        store = db.query(Store).filter(Store.id == store_id).first()
        if store and not store.csv_export_enabled:
            raise HTTPException(status_code=403, detail="CSVエクスポートが無効です。")

    from calendar import monthrange
    last_day = monthrange(year, month)[1]
    start_date = f"{year}-{month:02d}-01"
    end_date = f"{year}-{month:02d}-{last_day}"

    cast_query = db.query(Cast)
    if store_id:
        cast_query = cast_query.filter(Cast.store_id == store_id)
    casts = cast_query.all()

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(["キャスト名", "ランク", "給与形態", "出勤日数", "勤務時間", "基本給", "同伴バック", "指名バック", "ドリンクバック", "売上バック", "合計"])

    for cast in casts:
        att_query = db.query(Attendance).filter(
            Attendance.cast_id == cast.id,
            Attendance.date >= start_date,
            Attendance.date <= end_date
        )
        if store_id:
            att_query = att_query.filter(Attendance.store_id == store_id)
        attendances = att_query.all()

        total_hours = 0
        for att in attendances:
            if att.clock_in and att.clock_out:
                try:
                    ci = datetime.strptime(att.clock_in, "%H:%M")
                    co = datetime.strptime(att.clock_out, "%H:%M")
                    if co < ci:
                        co = co + timedelta(hours=24)
                    total_hours += (co - ci).total_seconds() / 3600
                except ValueError:
                    pass

        base_salary = cast.monthly_salary or 0 if cast.salary_type == "monthly" else int((cast.hourly_rate or 0) * total_hours)

        session_query = db.query(SessionModel).filter(
            SessionModel.cast_id == cast.id,
            SessionModel.start_time >= f"{start_date} 00:00:00",
            SessionModel.start_time <= f"{end_date} 23:59:59"
        )
        if store_id:
            session_query = session_query.filter(SessionModel.store_id == store_id)
        sessions = session_query.all()

        companion_back = sum((cast.companion_back or 0) for s in sessions if s.has_companion and s.companion_name == cast.stage_name)
        nomination_back = sum((cast.nomination_back or 0) for s in sessions if s.nomination_type)

        session_ids = [s.id for s in sessions]
        drink_back = 0
        if session_ids:
            orders = db.query(Order).filter(
                Order.cast_name == cast.stage_name,
                Order.is_drink_back == True,
                Order.session_id.in_(session_ids)
            ).all()
            drink_sales = sum(o.price * o.quantity for o in orders)
            drink_back = int(drink_sales * (cast.drink_back_rate or 10) / 100)

        total_sales = sum(s.current_total or 0 for s in sessions)
        sales_back = int(total_sales * (cast.sales_back_rate or 0) / 100)
        total_pay = base_salary + companion_back + nomination_back + drink_back + sales_back

        writer.writerow([
            cast.stage_name, cast.rank, cast.salary_type,
            len(attendances), round(total_hours, 1),
            base_salary, companion_back, nomination_back, drink_back, sales_back, total_pay
        ])

    output.seek(0)
    filename = f"payroll_{year}{month:02d}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/api/export/attendance")
def export_attendance_csv(
    year: int, month: int,
    db: Session = Depends(get_db),
    store_id: Optional[int] = Depends(get_store_id_from_token)
):
    """勤怠データCSVエクスポート"""
    if store_id:
        store = db.query(Store).filter(Store.id == store_id).first()
        if store and not store.csv_export_enabled:
            raise HTTPException(status_code=403, detail="CSVエクスポートが無効です。")

    from calendar import monthrange
    last_day = monthrange(year, month)[1]
    start_date = f"{year}-{month:02d}-01"
    end_date = f"{year}-{month:02d}-{last_day}"

    # キャスト勤怠
    att_query = db.query(Attendance).filter(Attendance.date >= start_date, Attendance.date <= end_date)
    if store_id:
        att_query = att_query.filter(Attendance.store_id == store_id)

    # スタッフ勤怠
    staff_att_query = db.query(StaffAttendance).filter(StaffAttendance.date >= start_date, StaffAttendance.date <= end_date)
    if store_id:
        staff_att_query = staff_att_query.filter(StaffAttendance.store_id == store_id)

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(["種別", "名前", "日付", "出勤", "退勤", "勤務時間", "日給"])

    for att in att_query.order_by(Attendance.date).all():
        cast = db.query(Cast).filter(Cast.id == att.cast_id).first()
        hours = ""
        if att.clock_in and att.clock_out:
            try:
                ci = datetime.strptime(att.clock_in, "%H:%M")
                co = datetime.strptime(att.clock_out, "%H:%M")
                if co < ci:
                    co = co + timedelta(hours=24)
                hours = round((co - ci).total_seconds() / 3600, 1)
            except ValueError:
                pass
        writer.writerow(["キャスト", cast.stage_name if cast else "?", att.date, att.clock_in, att.clock_out or "", hours, ""])

    for att in staff_att_query.order_by(StaffAttendance.date).all():
        staff = db.query(Staff).filter(Staff.id == att.staff_id).first()
        writer.writerow(["スタッフ", staff.name if staff else "?", att.date, att.clock_in, att.clock_out or "", att.hours_worked or "", att.daily_wage or ""])

    output.seek(0)
    filename = f"attendance_{year}{month:02d}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/api/export/expenses")
def export_expenses_csv(
    year: int, month: int,
    db: Session = Depends(get_db),
    store_id: Optional[int] = Depends(get_store_id_from_token)
):
    """経費データCSVエクスポート"""
    if store_id:
        store = db.query(Store).filter(Store.id == store_id).first()
        if store and not store.csv_export_enabled:
            raise HTTPException(status_code=403, detail="CSVエクスポートが無効です。")

    start_date = f"{year}-{month:02d}-01"
    if month == 12:
        end_date = f"{year + 1}-01-01"
    else:
        end_date = f"{year}-{month + 1:02d}-01"

    query = db.query(Expense).filter(Expense.date >= start_date, Expense.date < end_date)
    if store_id:
        query = query.filter(Expense.store_id == store_id)

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(["日付", "カテゴリ", "摘要", "金額"])

    for e in query.order_by(Expense.date).all():
        writer.writerow([e.date, EXPENSE_CATEGORIES.get(e.category, e.category), e.description, e.amount])

    output.seek(0)
    filename = f"expenses_{year}{month:02d}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# ========================
# エラーログAPI
# ========================

class ErrorLogCreate(BaseModel):
    error_type: str
    message: str
    stack: Optional[str] = None
    url: Optional[str] = None
    user_agent: Optional[str] = None
    extra_info: Optional[str] = None

@app.post("/api/error-logs")
def create_error_log(error: ErrorLogCreate, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    """フロントエンドからのエラーを記録"""
    db_error = ErrorLog(
        store_id=store_id,
        error_type=error.error_type,
        message=error.message[:1000] if error.message else "",  # 最大1000文字
        stack=error.stack[:5000] if error.stack else None,  # 最大5000文字
        url=error.url,
        user_agent=error.user_agent[:500] if error.user_agent else None,
        extra_info=error.extra_info
    )
    db.add(db_error)
    db.commit()
    db.refresh(db_error)
    return {"id": db_error.id, "message": "Error logged"}

@app.get("/api/error-logs")
def get_error_logs(limit: int = 100, db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    """エラーログ一覧取得"""
    query = db.query(ErrorLog)
    if store_id:
        query = query.filter(ErrorLog.store_id == store_id)
    errors = query.order_by(ErrorLog.created_at.desc()).limit(limit).all()
    
    return [{
        "id": e.id,
        "error_type": e.error_type,
        "message": e.message,
        "stack": e.stack,
        "url": e.url,
        "user_agent": e.user_agent,
        "extra_info": e.extra_info,
        "created_at": e.created_at.isoformat() if e.created_at else None
    } for e in errors]

@app.delete("/api/error-logs/{error_id}")
def delete_error_log(error_id: int, db: Session = Depends(get_db), _auth: dict = Depends(verify_token)):
    """エラーログ削除"""
    error = db.query(ErrorLog).filter(ErrorLog.id == error_id).first()
    if not error:
        raise HTTPException(status_code=404, detail="Error log not found")
    db.delete(error)
    db.commit()
    return {"message": "Error log deleted"}

@app.delete("/api/error-logs")
def delete_all_error_logs(db: Session = Depends(get_db), store_id: Optional[int] = Depends(get_store_id_from_token)):
    """全エラーログ削除"""
    query = db.query(ErrorLog)
    if store_id:
        query = query.filter(ErrorLog.store_id == store_id)
    count = query.delete()
    db.commit()
    return {"message": f"{count} error logs deleted"}

# ヘルスチェック


# ========================
# 静的ファイル配信（フロントエンド）
# ========================

# 静的ファイルディレクトリ
STATIC_DIR = Path(__file__).parent / "static"

# 静的ファイルをマウント
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_home():
    """トップページ（注文画面）"""
    file_path = STATIC_DIR / "order.html"
    if file_path.exists():
        return FileResponse(file_path)
    return HTMLResponse("<h1>Cabax</h1><p><a href='/admin'>管理画面</a> | <a href='/order'>注文画面</a></p>")

@app.get("/order", response_class=HTMLResponse)
async def serve_order():
    """注文画面"""
    file_path = STATIC_DIR / "order.html"
    if file_path.exists():
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="Order page not found")

@app.get("/admin", response_class=HTMLResponse)
async def serve_admin():
    """管理画面"""
    file_path = STATIC_DIR / "admin.html"
    if file_path.exists():
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="Admin page not found")

@app.get("/super-admin", response_class=HTMLResponse)
async def serve_super_admin():
    """スーパー管理画面"""
    file_path = STATIC_DIR / "super-admin.html"
    if file_path.exists():
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="Super admin page not found")

# HTML拡張子付きのルートも対応
@app.get("/admin.html", response_class=HTMLResponse)
async def serve_admin_html():
    return await serve_admin()

@app.get("/order.html", response_class=HTMLResponse)
async def serve_order_html():
    return await serve_order()

@app.get("/super-admin.html", response_class=HTMLResponse)
async def serve_super_admin_html():
    return await serve_super_admin()

# ヘルスチェック
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# ========================
# 店舗・ライセンス管理 API
# ========================

SUPER_ADMIN_KEY = os.getenv("SUPER_ADMIN_KEY")
if not SUPER_ADMIN_KEY:
    raise RuntimeError("SUPER_ADMIN_KEY environment variable is required")

def verify_super_admin(key: str):
    """超管理者認証"""
    if not key or key != SUPER_ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid super admin key")

def get_admin_key_from_header(x_admin_key: Optional[str] = Header(None)) -> str:
    """ヘッダーからadmin_keyを取得"""
    if not x_admin_key:
        raise HTTPException(status_code=403, detail="X-Admin-Key header required")
    verify_super_admin(x_admin_key)
    return x_admin_key

def generate_license_key():
    """ライセンスキー生成 (CABAX-XXXX-XXXX-XXXX)"""
    chars = string.ascii_uppercase + string.digits
    parts = [''.join(secrets.choice(chars) for _ in range(4)) for _ in range(3)]
    return f"CABAX-{'-'.join(parts)}"

@app.get("/api/stores")
async def get_stores(admin_key: str = Depends(get_admin_key_from_header), db: Session = Depends(get_db)):
    """全店舗一覧取得"""
    stores = db.query(Store).all()
    result = []
    for store in stores:
        days_remaining = (store.expires_at - datetime.utcnow()).days if store.expires_at else 0
        result.append({
            "id": store.id,
            "name": store.name,
            "license_key": store.license_key,
            "username": store.username,
            "has_manager_pin": bool(store.manager_pin),
            "has_staff_pin": bool(store.staff_pin),
            "expires_at": store.expires_at.isoformat() if store.expires_at else None,
            "status": store.status,
            "plan": store.plan,
            "monthly_fee": store.monthly_fee,
            "owner_name": store.owner_name,
            "phone": store.phone,
            "email": store.email,
            "address": store.address,
            "notes": store.notes,
            "created_at": store.created_at.isoformat() if store.created_at else None,
            "days_remaining": days_remaining
        })
    return result

@app.post("/api/stores")
async def create_store(store: StoreCreate, admin_key: str = Depends(get_admin_key_from_header), db: Session = Depends(get_db)):
    """新規店舗登録"""
    
    # ユーザー名の重複チェック
    if store.username:
        existing = db.query(Store).filter(Store.username == store.username).first()
        if existing:
            raise HTTPException(status_code=400, detail="このユーザー名は既に使用されています")
    
    license_key = generate_license_key()
    # 重複チェック
    while db.query(Store).filter(Store.license_key == license_key).first():
        license_key = generate_license_key()
    
    # 初回は1ヶ月後に期限設定
    expires_at = datetime.utcnow() + timedelta(days=30)
    
    # パスワードのハッシュ化
    hashed_pw = get_password_hash(store.password) if store.password else None
    
    new_store = Store(
        name=store.name,
        license_key=license_key,
        username=store.username,
        hashed_password=hashed_pw,
        expires_at=expires_at,
        status="active",
        plan=store.plan,
        monthly_fee=store.monthly_fee,
        owner_name=store.owner_name,
        phone=store.phone,
        email=store.email,
        address=store.address,
        notes=store.notes
    )
    db.add(new_store)
    db.commit()
    db.refresh(new_store)
    
    # 初期データを追加
    store_id = new_store.id
    
    # デフォルトテーブル
    default_tables = [
        {"name": "1番", "is_vip": False},
        {"name": "2番", "is_vip": False},
        {"name": "3番", "is_vip": False},
        {"name": "4番", "is_vip": False},
        {"name": "5番", "is_vip": False},
        {"name": "VIP1", "is_vip": True},
        {"name": "VIP2", "is_vip": True},
    ]
    for t in default_tables:
        db.add(Table(name=t["name"], is_vip=t["is_vip"], status="available", store_id=store_id))
    
    # デフォルトメニュー
    default_menu = [
        # drink - お客様用ドリンク（割り方はモーダルで選択）
        {"name": "ビール", "category": "drink", "price": 0, "cost": 0, "premium": False},
        {"name": "カクテル", "category": "drink", "price": 0, "cost": 0, "premium": False},
        {"name": "ソフトドリンク", "category": "drink", "price": 0, "cost": 0, "premium": False},
        {"name": "ショット", "category": "drink", "price": 2000, "cost": 0, "premium": False},
        {"name": "グラスワイン", "category": "drink", "price": 2000, "cost": 0, "premium": False},
        # castdrink - キャストドリンク（サイズはモーダルで選択）
        {"name": "麦焼酎", "category": "castdrink", "price": 1000, "cost": 0, "premium": False},
        {"name": "ウイスキー", "category": "castdrink", "price": 1000, "cost": 0, "premium": False},
        # tableset - 卓セット（無料・管理用）
        {"name": "アイスセット", "category": "tableset", "price": 0, "cost": 0, "premium": False},
        {"name": "アイス（追加）", "category": "tableset", "price": 0, "cost": 0, "premium": False},
        {"name": "グラス（追加）", "category": "tableset", "price": 0, "cost": 0, "premium": False},
        {"name": "ウーロン茶ピッチャー", "category": "tableset", "price": 0, "cost": 0, "premium": False},
        {"name": "緑茶ピッチャー", "category": "tableset", "price": 0, "cost": 0, "premium": False},
        {"name": "炭酸水", "category": "tableset", "price": 0, "cost": 0, "premium": False},
        {"name": "紅茶ピッチャー", "category": "tableset", "price": 0, "cost": 0, "premium": False},
        {"name": "ジャスミン茶ピッチャー", "category": "tableset", "price": 0, "cost": 0, "premium": False},
        {"name": "コーヒーピッチャー", "category": "tableset", "price": 0, "cost": 0, "premium": False},
        {"name": "ミネラルウォーター", "category": "tableset", "price": 0, "cost": 0, "premium": False},
        # champagne - シャンパン
        {"name": "アルマンド ブリュット", "category": "champagne", "price": 120000, "cost": 0, "premium": True},
        {"name": "アルマンド ロゼ", "category": "champagne", "price": 150000, "cost": 0, "premium": True},
        {"name": "クリュッグ", "category": "champagne", "price": 50000, "cost": 0, "premium": True},
        {"name": "ドンペリ", "category": "champagne", "price": 45000, "cost": 0, "premium": True},
        {"name": "ドンペリ ロゼ", "category": "champagne", "price": 70000, "cost": 0, "premium": True},
        {"name": "ベルエポック", "category": "champagne", "price": 35000, "cost": 0, "premium": True},
        {"name": "サロン", "category": "champagne", "price": 80000, "cost": 0, "premium": True},
        {"name": "ヴーヴクリコ", "category": "champagne", "price": 18000, "cost": 0, "premium": False},
        {"name": "モエ", "category": "champagne", "price": 15000, "cost": 0, "premium": False},
        {"name": "ローランペリエ", "category": "champagne", "price": 20000, "cost": 0, "premium": False},
        # wine - ワイン
        {"name": "赤ワイン", "category": "wine", "price": 8000, "cost": 0, "premium": False},
        {"name": "白ワイン", "category": "wine", "price": 8000, "cost": 0, "premium": False},
        # shochu - 焼酎ボトル
        {"name": "黒霧島", "category": "shochu", "price": 5000, "cost": 0, "premium": False},
        {"name": "いいちこ", "category": "shochu", "price": 4500, "cost": 0, "premium": False},
        # whisky - ウイスキーボトル
        {"name": "ジャックダニエル", "category": "whisky", "price": 12000, "cost": 0, "premium": False},
        {"name": "山崎", "category": "whisky", "price": 35000, "cost": 0, "premium": True},
        # food - フード
        {"name": "フルーツ盛り", "category": "food", "price": 3000, "cost": 0, "premium": False},
        {"name": "チョコレート", "category": "food", "price": 1500, "cost": 0, "premium": False},
        {"name": "ナッツ", "category": "food", "price": 1000, "cost": 0, "premium": False},
        {"name": "チーズ盛り", "category": "food", "price": 2000, "cost": 0, "premium": False},
        {"name": "枝豆", "category": "food", "price": 500, "cost": 0, "premium": False},
        {"name": "唐揚げ", "category": "food", "price": 800, "cost": 0, "premium": False},
    ]
    for m in default_menu:
        db.add(MenuItem(
            name=m["name"], 
            category=m["category"], 
            price=m["price"], 
            cost=m["cost"],
            premium=m["premium"],
            store_id=store_id
        ))
    
    db.commit()
    
    return {
        "id": new_store.id,
        "name": new_store.name,
        "license_key": new_store.license_key,
        "username": new_store.username,
        "expires_at": new_store.expires_at.isoformat(),
        "status": new_store.status,
        "message": "店舗を登録しました（初期データ含む）"
    }

@app.put("/api/stores/{store_id}")
async def update_store(store_id: int, store: StoreUpdate, admin_key: str = Depends(get_admin_key_from_header), db: Session = Depends(get_db)):
    """店舗情報更新"""
    
    db_store = db.query(Store).filter(Store.id == store_id).first()
    if not db_store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # ユーザー名の重複チェック（自分以外）
    if store.username:
        existing = db.query(Store).filter(Store.username == store.username, Store.id != store_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="このユーザー名は既に使用されています")
    
    update_data = store.dict(exclude_unset=True)
    
    # パスワードはハッシュ化して保存
    if 'password' in update_data and update_data['password']:
        db_store.hashed_password = get_password_hash(update_data['password'])
        del update_data['password']
    elif 'password' in update_data:
        del update_data['password']

    # PINもハッシュ化して保存
    if 'manager_pin' in update_data and update_data['manager_pin']:
        db_store.manager_pin = get_password_hash(update_data['manager_pin'])
        del update_data['manager_pin']
    elif 'manager_pin' in update_data:
        del update_data['manager_pin']

    if 'staff_pin' in update_data and update_data['staff_pin']:
        db_store.staff_pin = get_password_hash(update_data['staff_pin'])
        del update_data['staff_pin']
    elif 'staff_pin' in update_data:
        del update_data['staff_pin']

    for key, value in update_data.items():
        setattr(db_store, key, value)
    
    db.commit()
    db.refresh(db_store)
    return {"message": "更新しました", "id": db_store.id}

@app.post("/api/stores/{store_id}/extend")
async def extend_license(store_id: int, months: int, admin_key: str = Depends(get_admin_key_from_header), db: Session = Depends(get_db)):
    """ライセンス期限延長"""
    
    db_store = db.query(Store).filter(Store.id == store_id).first()
    if not db_store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # 現在の期限から延長（期限切れの場合は今日から）
    base_date = db_store.expires_at if db_store.expires_at > datetime.utcnow() else datetime.utcnow()
    db_store.expires_at = base_date + timedelta(days=30 * months)
    db_store.status = "active"
    
    db.commit()
    return {
        "message": f"{months}ヶ月延長しました",
        "new_expires_at": db_store.expires_at.isoformat()
    }

@app.post("/api/stores/{store_id}/suspend")
async def suspend_store(store_id: int, admin_key: str = Depends(get_admin_key_from_header), db: Session = Depends(get_db)):
    """店舗一時停止"""
    
    db_store = db.query(Store).filter(Store.id == store_id).first()
    if not db_store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    db_store.status = "suspended"
    db.commit()
    return {"message": "停止しました"}

@app.post("/api/stores/{store_id}/activate")
async def activate_store(store_id: int, admin_key: str = Depends(get_admin_key_from_header), db: Session = Depends(get_db)):
    """店舗再開"""
    
    db_store = db.query(Store).filter(Store.id == store_id).first()
    if not db_store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    db_store.status = "active"
    db.commit()
    return {"message": "再開しました"}

@app.delete("/api/stores/{store_id}")
async def delete_store(store_id: int, admin_key: str = Depends(get_admin_key_from_header), db: Session = Depends(get_db)):
    """店舗削除（関連データも全て削除）"""
    
    db_store = db.query(Store).filter(Store.id == store_id).first()
    if not db_store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    # 関連データを先に削除（外部キー制約対策）
    # 1. セッションに紐づく注文を削除
    sessions = db.query(SessionModel).filter(SessionModel.store_id == store_id).all()
    for session in sessions:
        db.query(Order).filter(Order.session_id == session.id).delete()
    
    # 2. セッション削除
    db.query(SessionModel).filter(SessionModel.store_id == store_id).delete()
    
    # 3. テーブル削除
    db.query(Table).filter(Table.store_id == store_id).delete()
    
    # 4. メニュー削除
    db.query(MenuItem).filter(MenuItem.store_id == store_id).delete()
    
    # 5. キャスト削除
    db.query(Cast).filter(Cast.store_id == store_id).delete()
    
    # 6. スタッフ削除
    db.query(Staff).filter(Staff.store_id == store_id).delete()
    
    # 7. 勤怠削除
    db.query(Attendance).filter(Attendance.store_id == store_id).delete()
    
    # 8. スタッフ勤怠削除
    db.query(StaffAttendance).filter(StaffAttendance.store_id == store_id).delete()
    
    # 最後に店舗削除
    db.delete(db_store)
    db.commit()
    return {"message": "削除しました"}

@app.get("/api/license/verify/{license_key}")
async def verify_license(license_key: str, db: Session = Depends(get_db)):
    """ライセンス検証（店舗側から呼ぶ）"""
    store = db.query(Store).filter(Store.license_key == license_key).first()
    if not store:
        return {"valid": False, "message": "無効なライセンスキーです"}
    
    if store.status == "suspended":
        return {"valid": False, "message": "ライセンスが停止されています"}
    
    if store.expires_at < datetime.utcnow():
        return {"valid": False, "message": "ライセンスの有効期限が切れています", "expired": True}
    
    days_remaining = (store.expires_at - datetime.utcnow()).days
    return {
        "valid": True,
        "store_name": store.name,
        "plan": store.plan,
        "expires_at": store.expires_at.isoformat(),
        "days_remaining": days_remaining,
        "warning": days_remaining <= 7
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
