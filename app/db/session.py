import sqlalchemy
import dotenv
import os

dotenv.load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")

engine = sqlalchemy.create_engine(DATABASE_URL)

SessionLocal = sqlalchemy.orm.sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        

