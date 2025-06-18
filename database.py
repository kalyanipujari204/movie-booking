import mysql.connector
from contextlib import contextmanager

@contextmanager
def get_db():
    conn = mysql.connector.connect(
        host="localhost",
        user="root",
        password="admin123",
        database="bookmovie"
    )
    try:
        yield conn
    finally:
        conn.close()
