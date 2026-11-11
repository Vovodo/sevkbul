from urllib.parse import urlparse, urlunparse
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session, ORMExecuteState, with_loader_criteria

from app.config import settings
from app.session_context import get_current_session_id


def _normalize_and_resolve_db_url(raw_url: str) -> str:
    """
    Coolify veya .env üzerinden verilen DATABASE_URL'yi normalize eder ve doğrular:
    1) 'postgres://' şemasını SQLAlchemy 2.0 uyumlu 'postgresql://' şemasına çevirir.
    2) Diğer uygulamanın 'postgres' veritabanıyla karışmaması için '/postgres' ise '/sevkbul' yapar.
    3) Coolify container'ları farklı Docker ağlarında olduğunda internal hostname çözümlenemezse
       sırasıyla [verilen_host, '10.0.1.4', 'c2c39b9e6e9c', '213.142.148.57', '10.0.1.1']
       adreslerini 3 sn timeout ile dener ve erişilebilen ilk adresi seçer.
    """
    url = (raw_url or "").strip().strip('"').strip("'")
    if not url:
        return "sqlite:///./sevkbul.db"

    if url.startswith("sqlite"):
        return url

    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    elif url.startswith("postgresql+psycopg2://"):
        pass

    try:
        parsed = urlparse(url)
    except Exception:
        return url

    # Veritabanı adı '/postgres' veya boş ise izole '/sevkbul' veritabanına yönlendir
    db_path = (parsed.path or "").strip("/")
    if not db_path or db_path == "postgres":
        parsed = parsed._replace(path="/sevkbul")
        url = urlunparse(parsed)

    # Pytest çalışırken veya host yoksa olduğu gibi dön
    orig_host = parsed.hostname
    if not orig_host:
        return url

    port = parsed.port or 5432
    user = parsed.username or "postgres"
    password = parsed.password or ""

    # Denenecek aday host listesi (önce kullanıcının verdiği host, sonra Coolify iç/dış IP'leri)
    candidate_hosts: list[str] = []
    for h in (orig_host, "10.0.1.4", "c2c39b9e6e9c", "213.142.148.57", "10.0.1.1"):
        if h and h not in candidate_hosts:
            candidate_hosts.append(h)

    import psycopg2
    target_db = parsed.path.strip("/") or "sevkbul"
    for host_cand in candidate_hosts:
        try:
            conn = psycopg2.connect(
                dbname=target_db,
                user=user,
                password=password,
                host=host_cand,
                port=port,
                connect_timeout=3,
            )
            conn.close()
            netloc = f"{user}:{password}@{host_cand}:{port}" if password else f"{user}@{host_cand}:{port}"
            resolved = urlunparse(parsed._replace(netloc=netloc, path=f"/{target_db}"))
            if host_cand != orig_host:
                print(f"[DB] '{orig_host}' yerine erişilebilir PostgreSQL hostu seçildi: '{host_cand}'")
            return resolved
        except Exception as exc:
            err_msg = str(exc)
            if "does not exist" in err_msg and target_db != "postgres":
                try:
                    adm = psycopg2.connect(
                        dbname="postgres",
                        user=user,
                        password=password,
                        host=host_cand,
                        port=port,
                        connect_timeout=3,
                    )
                    adm.autocommit = True
                    cur = adm.cursor()
                    cur.execute(f'CREATE DATABASE "{target_db}" ENCODING \'UTF8\'')
                    adm.close()
                    netloc = f"{user}:{password}@{host_cand}:{port}" if password else f"{user}@{host_cand}:{port}"
                    return urlunparse(parsed._replace(netloc=netloc, path=f"/{target_db}"))
                except Exception:
                    pass
            print(f"[DB] PostgreSQL host denemesi başarısız ({host_cand}:{port}): {exc}")

    print("[DB] UYARI: Hiçbir PostgreSQL hostuna ulaşılamadı, yerel SQLite yedek veritabanına geçiliyor.")
    return "sqlite:///./sevkbul.db"


ACTIVE_DATABASE_URL = _normalize_and_resolve_db_url(settings.database_url)

connect_args = {}
engine_kwargs = {"pool_pre_ping": True}
if ACTIVE_DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
else:
    connect_args["connect_timeout"] = 5
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20
    engine_kwargs["pool_recycle"] = 1800

engine = create_engine(
    ACTIVE_DATABASE_URL,
    connect_args=connect_args,
    **engine_kwargs,
)

if ACTIVE_DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute("PRAGMA cache_size=-32000")
        except Exception:
            pass
        finally:
            cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


@event.listens_for(Session, "do_orm_execute")
def _apply_session_isolation_criteria(execute_state: ORMExecuteState) -> None:
    """
    Tüm SELECT, UPDATE ve DELETE sorgularına otomatik olarak
    aktif çalışma oturumu (session_id) filtresini enjekte eder.
    Genel özet sorguları için .execution_options(ignore_session_filter=True) kullanılabilir.
    """
    if execute_state.execution_options.get("ignore_session_filter", False):
        return
    if not (execute_state.is_select or execute_state.is_update or execute_state.is_delete):
        return

    from app.models import InventoryLabel, Shipment, ShipmentTarget, ScanLog, ExcelHeaderSettings

    sid = get_current_session_id()
    stmt = execute_state.statement
    for model_cls in (InventoryLabel, Shipment, ShipmentTarget, ScanLog, ExcelHeaderSettings):
        stmt = stmt.options(
            with_loader_criteria(
                model_cls,
                model_cls.session_id == sid,
                include_aliases=True,
            )
        )
    execute_state.statement = stmt


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
