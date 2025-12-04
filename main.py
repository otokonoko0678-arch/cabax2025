"""
Cabax - キャバクラ管理システム バックエンド（完全版）
FastAPI + SQLAlchemy + JWT認証
すべての機能に対応
"""

from fastapi import FastAPI, Depends, HTTPException, status
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
from pathlib import Path

# 設定
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./cabax.db")

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
    name = Column(String, unique=True, index=True)
    status = Column(String, default="available")
    is_vip = Column(Boolean, default=False)
    sessions = relationship("SessionModel", back_populates="table")

class Cast(Base):
    # 源氏名を使用
    __tablename__ = "casts"
    id = Column(Integer, primary_key=True, index=True)
    stage_name = Column(String, unique=True, index=True)
    rank = Column(String, default="regular")
    hourly_rate = Column(Integer)
    drink_back_rate = Column(Integer, default=10)  # ドリンクバック率(%)
    sales = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    sessions = relationship("SessionModel", back_populates="cast")
    attendances = relationship("Attendance", back_populates="cast")

class MenuItem(Base):
    __tablename__ = "menu_items"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    category = Column(String, index=True)
    price = Column(Integer)
    description = Column(Text, nullable=True)
    image_url = Column(String, nullable=True)
    stock = Column(Integer, nullable=True)
    premium = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    orders = relationship("Order", back_populates="menu_item")

class SessionModel(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True, index=True)
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
    
    table = relationship("Table", back_populates="sessions")
    cast = relationship("Cast", back_populates="sessions")
    orders = relationship("Order", back_populates="session")

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"))
    menu_item_id = Column(Integer, ForeignKey("menu_items.id"), nullable=True)
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
    cast_id = Column(Integer, ForeignKey("casts.id"))
    date = Column(String, index=True)
    clock_in = Column(String)
    clock_out = Column(String, nullable=True)
    status = Column(String, default="working")
    cast = relationship("Cast", back_populates="attendances")

class Shift(Base):
    __tablename__ = "shifts"
    id = Column(Integer, primary_key=True, index=True)
    cast_id = Column(Integer, ForeignKey("casts.id"))
    date = Column(String, index=True)
    start_time = Column(String)
    end_time = Column(String)

class Staff(Base):
    __tablename__ = "staff"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    role = Column(String)  # waiter, kitchen, manager, catch, driver, other
    hourly_rate = Column(Integer, default=1000)
    phone = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
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
    hourly_rate: int
    drink_back_rate: int = 10

class CastUpdate(BaseModel):
    stage_name: Optional[str] = None
    rank: Optional[str] = None
    hourly_rate: Optional[int] = None
    drink_back_rate: Optional[int] = None

class CastResponse(BaseModel):
    id: int
    stage_name: str
    rank: str
    hourly_rate: int
    drink_back_rate: int
    sales: int
    class Config:
        from_attributes = True

class MenuItemCreate(BaseModel):
    name: str
    category: str
    price: int
    description: Optional[str] = None
    image_url: Optional[str] = None
    stock: Optional[int] = None
    premium: Optional[bool] = False

class MenuItemUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    price: Optional[int] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    stock: Optional[int] = None
    premium: Optional[bool] = None

class MenuItemResponse(BaseModel):
    id: int
    name: str
    category: str
    price: int
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

class SessionResponse(BaseModel):
    id: int
    table_id: int
    cast_id: int
    guests: int
    catch_staff: Optional[str]
    start_time: datetime
    end_time: Optional[datetime]
    current_total: int
    tax_rate: int = 20
    status: str
    class Config:
        from_attributes = True

class OrderCreate(BaseModel):
    session_id: int
    menu_item_id: int
    quantity: int
    is_drink_back: bool = False
    cast_name: Optional[str] = None

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
    hourly_rate: int = 1000
    phone: Optional[str] = None

class StaffUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    hourly_rate: Optional[int] = None
    phone: Optional[str] = None

class StaffResponse(BaseModel):
    id: int
    name: str
    role: str
    hourly_rate: int
    phone: Optional[str]
    is_active: bool
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
        return username
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ========================
# FastAPI アプリケーション
# ========================

app = FastAPI(title="Cabax API", version="2.0.0")

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
            Cast(stage_name="あいり", rank="レギュラー", hourly_rate=3000, drink_back_rate=10),
            Cast(stage_name="みゆ", rank="レギュラー", hourly_rate=3000, drink_back_rate=10),
            Cast(stage_name="れな", rank="エース", hourly_rate=4000, drink_back_rate=15),
            Cast(stage_name="かな", rank="エース", hourly_rate=4000, drink_back_rate=15),
            Cast(stage_name="りお", rank="ナンバー", hourly_rate=5000, drink_back_rate=20),
        ]
        db.add_all(casts)
        db.commit()
        print("✅ キャスト作成完了")
    
    # スタッフ
    if db.query(Staff).count() == 0:
        staff_members = [
            Staff(name="田中", role="manager", hourly_rate=1500),
            Staff(name="山田", role="waiter", hourly_rate=1200),
            Staff(name="佐藤", role="waiter", hourly_rate=1200),
            Staff(name="鈴木", role="kitchen", hourly_rate=1100),
            Staff(name="高橋", role="catch", hourly_rate=1000),
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
    user = db.query(User).filter(User.username == request.username).first()
    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

# キャスト管理
@app.get("/api/casts", response_model=List[CastResponse])
def get_casts(db: Session = Depends(get_db), ):
    return db.query(Cast).all()

@app.post("/api/casts", response_model=CastResponse)
def create_cast(cast: CastCreate, db: Session = Depends(get_db), ):
    db_cast = Cast(**cast.dict())
    db.add(db_cast)
    db.commit()
    db.refresh(db_cast)
    return db_cast

@app.put("/api/casts/{cast_id}", response_model=CastResponse)
def update_cast(cast_id: int, cast: CastUpdate, db: Session = Depends(get_db), ):
    db_cast = db.query(Cast).filter(Cast.id == cast_id).first()
    if not db_cast:
        raise HTTPException(status_code=404, detail="Cast not found")
    for key, value in cast.dict(exclude_unset=True).items():
        setattr(db_cast, key, value)
    db.commit()
    db.refresh(db_cast)
    return db_cast

@app.delete("/api/casts/{cast_id}")
def delete_cast(cast_id: int, db: Session = Depends(get_db), ):
    db_cast = db.query(Cast).filter(Cast.id == cast_id).first()
    if not db_cast:
        raise HTTPException(status_code=404, detail="Cast not found")
    db.delete(db_cast)
    db.commit()
    return {"message": "Cast deleted"}

# スタッフ管理
@app.get("/api/staff", response_model=List[StaffResponse])
def get_staff(db: Session = Depends(get_db)):
    return db.query(Staff).filter(Staff.is_active == True).all()

@app.post("/api/staff", response_model=StaffResponse)
def create_staff(staff: StaffCreate, db: Session = Depends(get_db)):
    db_staff = Staff(**staff.dict())
    db.add(db_staff)
    db.commit()
    db.refresh(db_staff)
    return db_staff

@app.put("/api/staff/{staff_id}", response_model=StaffResponse)
def update_staff(staff_id: int, staff: StaffUpdate, db: Session = Depends(get_db)):
    db_staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not db_staff:
        raise HTTPException(status_code=404, detail="Staff not found")
    for key, value in staff.dict(exclude_unset=True).items():
        setattr(db_staff, key, value)
    db.commit()
    db.refresh(db_staff)
    return db_staff

@app.delete("/api/staff/{staff_id}")
def delete_staff(staff_id: int, db: Session = Depends(get_db)):
    db_staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not db_staff:
        raise HTTPException(status_code=404, detail="Staff not found")
    db_staff.is_active = False  # 論理削除
    db.commit()
    return {"message": "Staff deleted"}

# メニュー管理
@app.get("/api/menu", response_model=List[MenuItemResponse])
def get_menu(db: Session = Depends(get_db), ):
    return db.query(MenuItem).all()

@app.post("/api/menu", response_model=MenuItemResponse)
def create_menu_item(item: MenuItemCreate, db: Session = Depends(get_db), ):
    db_item = MenuItem(**item.dict())
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

@app.put("/api/menu/{item_id}", response_model=MenuItemResponse)
def update_menu_item(item_id: int, item: MenuItemUpdate, db: Session = Depends(get_db), ):
    db_item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    for key, value in item.dict(exclude_unset=True).items():
        setattr(db_item, key, value)
    db.commit()
    db.refresh(db_item)
    return db_item

@app.delete("/api/menu/{item_id}")
def delete_menu_item(item_id: int, db: Session = Depends(get_db), ):
    db_item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    db.delete(db_item)
    db.commit()
    return {"message": "Menu item deleted"}

# テーブル管理
@app.get("/api/tables", response_model=List[TableResponse])
def get_tables(db: Session = Depends(get_db), ):
    return db.query(Table).all()

@app.post("/api/tables", response_model=TableResponse)
def create_table(table: TableCreate, db: Session = Depends(get_db)):
    # 同名テーブルチェック
    existing = db.query(Table).filter(Table.name == table.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="同じ名前のテーブルが既に存在します")
    
    db_table = Table(name=table.name, is_vip=table.is_vip, status="available")
    db.add(db_table)
    db.commit()
    db.refresh(db_table)
    return db_table

@app.put("/api/tables/{table_id}", response_model=TableResponse)
def update_table(table_id: int, table: TableCreate, db: Session = Depends(get_db)):
    db_table = db.query(Table).filter(Table.id == table_id).first()
    if not db_table:
        raise HTTPException(status_code=404, detail="テーブルが見つかりません")
    
    # 同名テーブルチェック（自分以外）
    existing = db.query(Table).filter(Table.name == table.name, Table.id != table_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="同じ名前のテーブルが既に存在します")
    
    db_table.name = table.name
    db_table.is_vip = table.is_vip
    db.commit()
    db.refresh(db_table)
    return db_table

@app.delete("/api/tables/{table_id}")
def delete_table(table_id: int, db: Session = Depends(get_db)):
    db_table = db.query(Table).filter(Table.id == table_id).first()
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
def create_session(session: SessionCreate, db: Session = Depends(get_db), ):
    db_session = SessionModel(**session.dict())
    db.add(db_session)
    table = db.query(Table).filter(Table.id == session.table_id).first()
    if table:
        table.status = "occupied"
    db.commit()
    db.refresh(db_session)
    return db_session

@app.get("/api/sessions/active", response_model=List[SessionResponse])
def get_active_sessions(db: Session = Depends(get_db), ):
    return db.query(SessionModel).filter(SessionModel.status == "active").all()

@app.get("/api/sessions/{session_id}/orders")
def get_session_orders(session_id: int, db: Session = Depends(get_db)):
    """特定セッションの注文を取得"""
    orders = db.query(Order).filter(Order.session_id == session_id).all()
    result = []
    for order in orders:
        menu_item = db.query(MenuItem).filter(MenuItem.id == order.menu_item_id).first() if order.menu_item_id else None
        # menu_item_idがない場合はcast_nameにitem_nameが入っている（add-chargeで追加した料金）
        item_name = menu_item.name if menu_item else (order.cast_name or "料金")
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
def call_staff(session_id: int, db: Session = Depends(get_db)):
    """スタッフ呼び出し"""
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    # 実際のシステムでは通知を送るなどの処理を行う
    print(f"🔔 スタッフ呼び出し: セッション {session_id}")
    return {"message": "Staff called", "session_id": session_id}

@app.put("/api/sessions/{session_id}/checkout")
def checkout_session(session_id: int, db: Session = Depends(get_db), ):
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.status = "completed"
    session.end_time = datetime.utcnow()
    if session.table:
        session.table.status = "available"
    db.commit()
    return {"message": "Session checked out"}

@app.post("/api/sessions/{session_id}/add-charge")
def add_charge_to_session(session_id: int, charge: dict, db: Session = Depends(get_db)):
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
def get_orders(db: Session = Depends(get_db)):
    """全注文を取得（テーブル名、メニュー名付き）"""
    orders = db.query(Order).all()
    result = []
    for order in orders:
        session = db.query(SessionModel).filter(SessionModel.id == order.session_id).first()
        table = db.query(Table).filter(Table.id == session.table_id).first() if session else None
        menu_item = None
        if order.menu_item_id:
            menu_item = db.query(MenuItem).filter(MenuItem.id == order.menu_item_id).first()
        
        # menu_item_idがない場合はcast_nameにアイテム名が入っている（add-chargeで追加した料金）
        item_name = menu_item.name if menu_item else (order.cast_name or "料金")
        
        result.append({
            "id": order.id,
            "session_id": order.session_id,
            "table_id": table.id if table else None,
            "table_name": table.name if table else "?",
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

@app.post("/api/orders")
def create_order(order: OrderCreate, db: Session = Depends(get_db), ):
    menu_item = db.query(MenuItem).filter(MenuItem.id == order.menu_item_id).first()
    if not menu_item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    db_order = Order(
        session_id=order.session_id,
        menu_item_id=order.menu_item_id,
        quantity=order.quantity,
        price=menu_item.price,
        is_drink_back=order.is_drink_back,
        cast_name=order.cast_name
    )
    db.add(db_order)
    session = db.query(SessionModel).filter(SessionModel.id == order.session_id).first()
    if session:
        session.current_total += menu_item.price * order.quantity
    db.commit()
    db.refresh(db_order)
    return db_order

@app.put("/api/orders/{order_id}/serve")
def mark_order_served(order_id: int, db: Session = Depends(get_db)):
    """注文を提供済みにする"""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    order.is_served = True
    db.commit()
    return {"message": "Order marked as served", "id": order_id}

@app.put("/api/sessions/{session_id}/orders/{order_id}/status")
def update_order_status(session_id: int, order_id: int, status_data: dict, db: Session = Depends(get_db)):
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
def clock_in(attendance: AttendanceCreate, db: Session = Depends(get_db), ):
    db_attendance = Attendance(**attendance.dict(), status="working")
    db.add(db_attendance)
    db.commit()
    db.refresh(db_attendance)
    return db_attendance

@app.put("/api/attendance/{attendance_id}/clock-out")
def clock_out(attendance_id: int, data: AttendanceClockOut, db: Session = Depends(get_db), ):
    attendance = db.query(Attendance).filter(Attendance.id == attendance_id).first()
    if not attendance:
        raise HTTPException(status_code=404, detail="Attendance not found")
    attendance.clock_out = data.clock_out
    attendance.status = "completed"
    db.commit()
    return attendance

@app.get("/api/attendance")
def get_attendance(date: Optional[str] = None, db: Session = Depends(get_db), ):
    query = db.query(Attendance)
    if date:
        query = query.filter(Attendance.date == date)
    return query.all()

# シフト管理
@app.post("/api/shifts")
def create_shift(shift: ShiftCreate, db: Session = Depends(get_db), ):
    db_shift = Shift(**shift.dict())
    db.add(db_shift)
    db.commit()
    db.refresh(db_shift)
    return db_shift

@app.get("/api/shifts")
def get_shifts(date: Optional[str] = None, db: Session = Depends(get_db), ):
    query = db.query(Shift)
    if date:
        query = query.filter(Shift.date == date)
    return query.all()

# 日報
@app.get("/api/daily-report")
def get_daily_report(date: Optional[str] = None, db: Session = Depends(get_db)):
    """日報データを取得"""
    target_date = date or datetime.utcnow().strftime("%Y-%m-%d")
    
    # その日のセッション
    sessions = db.query(SessionModel).filter(
        SessionModel.start_time >= f"{target_date} 00:00:00",
        SessionModel.start_time <= f"{target_date} 23:59:59"
    ).all()
    
    # 売上計算
    total_sales = 0
    total_guests = 0
    session_count = len(sessions)
    
    for session in sessions:
        total_sales += session.current_total or 0
        total_guests += session.guests or 0
    
    # その日の注文
    orders = db.query(Order).filter(
        Order.created_at >= f"{target_date} 00:00:00",
        Order.created_at <= f"{target_date} 23:59:59"
    ).all()
    
    # ドリンクバック集計
    drink_back_total = sum(o.price * o.quantity for o in orders if o.is_drink_back)
    
    # その日の勤怠
    attendances = db.query(Attendance).filter(Attendance.date == target_date).all()
    
    return {
        "date": target_date,
        "session_count": session_count,
        "total_guests": total_guests,
        "total_sales": total_sales,
        "drink_back_total": drink_back_total,
        "order_count": len(orders),
        "attendance_count": len(attendances),
        "sessions": [
            {
                "id": s.id,
                "table_id": s.table_id,
                "guests": s.guests,
                "total": s.current_total,
                "status": s.status
            } for s in sessions
        ]
    }

@app.get("/api/daily-report/cast-ranking")
def get_cast_ranking(date: Optional[str] = None, db: Session = Depends(get_db)):
    """キャストランキングを取得"""
    target_date = date or datetime.utcnow().strftime("%Y-%m-%d")
    
    # その日のドリンクバック注文を集計
    orders = db.query(Order).filter(
        Order.created_at >= f"{target_date} 00:00:00",
        Order.created_at <= f"{target_date} 23:59:59",
        Order.is_drink_back == True
    ).all()
    
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

# ヘルスチェック
@app.get("/")
def root():
    return {"message": "Cabax API is running", "version": "2.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 開発環境用
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# テーブル初期化用エンドポイント（開発用）
@app.post("/api/init-tables")
def init_tables():
    """開発用：テーブルデータを初期化"""
    tables = []
    for i in range(1, 7):  # テーブル1〜6を作成
        table = {
            "id": i,
            "name": str(i),
            "status": "available",
            "is_vip": False
        }
        tables.append(table)
        # ここでデータベースに保存する処理を追加
        # 例: db.add(Table(**table))
    
    return {"message": "Tables initialized", "tables": tables}

# ========================
# 静的ファイル配信（フロントエンド）
# ========================

# 静的ファイルディレクトリ
STATIC_DIR = Path(__file__).parent / "static"

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

# ヘルスチェック
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
