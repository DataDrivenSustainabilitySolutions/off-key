# backend/services/database.py
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

def get_db_session(db_url):
    engine = create_engine(db_url)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)