import sqlalchemy
import sqlalchemy.orm
import dotenv
import os

dotenv.load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
# Render (and Heroku before it) hand out connection strings starting "postgres://", which
# SQLAlchemy 1.4+ no longer accepts as an alias for "postgresql://" - normalize rather than
# make every deploy target hand-edit the value after provisioning.
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

engine = sqlalchemy.create_engine(DATABASE_URL)

SessionLocal = sqlalchemy.orm.sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        

