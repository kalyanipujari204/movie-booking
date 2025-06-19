from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from typing import Optional, List
import mysql.connector
from mysql.connector import Error
import jwt
from passlib.context import CryptContext
import os
from contextlib import contextmanager

app = FastAPI(title="Movie Booking API", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# Database config
DB_CONFIG = {
    'host': 'localhost',
    'database': 'bookmovie',
    'user': 'root',
    'password': 'admin123'
}


@contextmanager
def get_db():
    connection = None
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        yield connection
    except Error as e:
        if connection:
            connection.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    finally:
        if connection and connection.is_connected():
            connection.close()


# Models
class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class User(BaseModel):
    customer_id: int
    name: str
    email: str


class Movie(BaseModel):
    movie_id: int
    title: str
    description: str
    genre: str
    poster_url: str
    duration: int
    release_date: datetime
    base_price: float  # Added base_price field


class Theatre(BaseModel):
    theatre_id: int
    name: str
    location: str


class Showtime(BaseModel):
    showtime_id: int
    movie_id: int
    theatre_id: int
    start_time: datetime
    price: float
    movie: Optional[Movie] = None
    theatre: Optional[Theatre] = None


class Seat(BaseModel):
    seat_id: int
    showtime_id: int
    seat_number: str
    is_booked: bool


class BookingCreate(BaseModel):
    showtime_id: int
    seat_id: int


class Booking(BaseModel):
    booking_id: int
    customer_id: int
    showtime_id: int
    seat_id: int
    booking_time: datetime


# Auth functions
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM customers WHERE customer_id = %s", (user_id,))
        user = cursor.fetchone()

    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return User(**user)


# Routes
@app.post("/auth/register")
async def register(user: UserCreate):
    hashed_password = get_password_hash(user.password)

    with get_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO customers (name, email, password_hash) VALUES (%s, %s, %s)",
                (user.name, user.email, hashed_password)
            )
            conn.commit()
            return {"message": "User registered successfully"}
        except Error as e:
            if e.errno == 1062:  # Duplicate entry
                raise HTTPException(status_code=400, detail="Email already registered")
            raise HTTPException(status_code=500, detail="Registration failed")


@app.post("/auth/login")
async def login(user: UserLogin):
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM customers WHERE email = %s", (user.email,))
        db_user = cursor.fetchone()

    if not db_user or not verify_password(user.password, db_user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(db_user["customer_id"])}, expires_delta=access_token_expires
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": User(**db_user)
    }


@app.get("/movies", response_model=List[Movie])
async def get_movies():
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        # Added base_price to the SELECT statement
        cursor.execute("SELECT movie_id, title, description, genre, poster_url, duration, release_date, base_price FROM movies ORDER BY release_date DESC")
        movies = cursor.fetchall()
    return [Movie(**movie) for movie in movies]


@app.get("/movies/{movie_id}", response_model=Movie)
async def get_movie(movie_id: int):
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        # Added base_price to the SELECT statement
        cursor.execute("SELECT movie_id, title, description, genre, poster_url, duration, release_date, base_price FROM movies WHERE movie_id = %s", (movie_id,))
        movie = cursor.fetchone()

    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")
    return Movie(**movie)


@app.get("/theatres", response_model=List[Theatre])
async def get_theatres():
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM theatres")
        theatres = cursor.fetchall()
    return [Theatre(**theatre) for theatre in theatres]


@app.get("/showtimes")
async def get_showtimes(movie_id: Optional[int] = None, theatre_id: Optional[int] = None):
    query = """
        SELECT s.*, m.title, m.description, m.genre, m.poster_url, m.duration, m.release_date, m.base_price,
               t.name as theatre_name, t.location
        FROM showtimes s
        JOIN movies m ON s.movie_id = m.movie_id
        JOIN theatres t ON s.theatre_id = t.theatre_id
        WHERE 1=1
    """
    params = []

    if movie_id:
        query += " AND s.movie_id = %s"
        params.append(movie_id)

    if theatre_id:
        query += " AND s.theatre_id = %s"
        params.append(theatre_id)

    query += " ORDER BY s.start_time"

    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, params)
        showtimes = cursor.fetchall()

    result = []
    for showtime in showtimes:
        showtime_data = {
            "showtime_id": showtime["showtime_id"],
            "movie_id": showtime["movie_id"],
            "theatre_id": showtime["theatre_id"],
            "start_time": showtime["start_time"],
            "price": showtime["price"],
            "movie": Movie(
                movie_id=showtime["movie_id"],
                title=showtime["title"],
                description=showtime["description"],
                genre=showtime["genre"],
                poster_url=showtime["poster_url"],
                duration=showtime["duration"],
                release_date=showtime["release_date"],
                base_price=showtime["base_price"]  # Added base_price
            ),
            "theatre": Theatre(
                theatre_id=showtime["theatre_id"],
                name=showtime["theatre_name"],
                location=showtime["location"]
            )
        }
        result.append(showtime_data)

    return result


@app.get("/seats", response_model=List[Seat])
async def get_seats(showtime_id: int):
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM seats WHERE showtime_id = %s ORDER BY seat_number", (showtime_id,))
        seats = cursor.fetchall()
    return [Seat(**seat) for seat in seats]


@app.post("/bookings", response_model=Booking)
async def create_booking(booking: BookingCreate, current_user: User = Depends(get_current_user)):
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)

        # Check if seat is available
        cursor.execute("SELECT is_booked FROM seats WHERE seat_id = %s", (booking.seat_id,))
        seat = cursor.fetchone()

        if not seat:
            raise HTTPException(status_code=404, detail="Seat not found")

        if seat["is_booked"]:
            raise HTTPException(status_code=400, detail="Seat already booked")

        try:
            # Create booking
            cursor.execute(
                "INSERT INTO bookings (customer_id, showtime_id, seat_id) VALUES (%s, %s, %s)",
                (current_user.customer_id, booking.showtime_id, booking.seat_id)
            )
            booking_id = cursor.lastrowid

            # Mark seat as booked
            cursor.execute("UPDATE seats SET is_booked = TRUE WHERE seat_id = %s", (booking.seat_id,))

            conn.commit()

            # Get the created booking
            cursor.execute("SELECT * FROM bookings WHERE booking_id = %s", (booking_id,))
            new_booking = cursor.fetchone()

            return Booking(**new_booking)

        except Error as e:
            conn.rollback()
            raise HTTPException(status_code=500, detail="Booking failed")


@app.delete("/bookings/{booking_id}")
async def cancel_booking(booking_id: int, current_user: User = Depends(get_current_user)):
    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)

        # Get booking details to verify ownership
        cursor.execute(
            "SELECT * FROM bookings WHERE booking_id = %s AND customer_id = %s",
            (booking_id, current_user.customer_id)
        )
        booking = cursor.fetchone()

        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found or not owned by user")

        try:
            # Free up the seat
            cursor.execute(
                "UPDATE seats SET is_booked = FALSE WHERE seat_id = %s",
                (booking["seat_id"],)
            )

            # Delete the booking
            cursor.execute(
                "DELETE FROM bookings WHERE booking_id = %s",
                (booking_id,)
            )

            conn.commit()
            return {"message": "Booking cancelled successfully"}

        except Error as e:
            conn.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to cancel booking: {str(e)}")

@app.get("/bookings/my")
async def get_my_bookings(current_user: User = Depends(get_current_user)):
    query = """
        SELECT 
            b.booking_id,
            b.booking_time,
            s.showtime_id,
            s.start_time,
            s.price,
            m.movie_id,
            m.title as movie_title,
            m.poster_url,
            t.theatre_id,
            t.name as theatre_name,
            GROUP_CONCAT(se.seat_number ORDER BY se.seat_number SEPARATOR ', ') as seat_numbers,
            COUNT(se.seat_id) as seat_count
        FROM bookings b
        JOIN showtimes s ON b.showtime_id = s.showtime_id
        JOIN movies m ON s.movie_id = m.movie_id
        JOIN theatres t ON s.theatre_id = t.theatre_id
        JOIN seats se ON b.seat_id = se.seat_id
        WHERE b.customer_id = %s
        GROUP BY b.booking_id, s.showtime_id, m.movie_id, t.theatre_id
        ORDER BY b.booking_time DESC
    """

    with get_db() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, (current_user.customer_id,))
        bookings = cursor.fetchall()

    if not bookings:
        return []

    # Format the response to match frontend expectations
    formatted_bookings = []
    for booking in bookings:
        formatted_booking = {
            "booking_id": booking["booking_id"],
            "showtime": {
                "showtime_id": booking["showtime_id"],
                "start_time": booking["start_time"],
                "price": float(booking["price"]),
                "movie": {
                    "movie_id": booking["movie_id"],
                    "title": booking["movie_title"],
                    "poster_url": booking["poster_url"]
                },
                "theatre": {
                    "theatre_id": booking["theatre_id"],
                    "name": booking["theatre_name"]
                }
            },
            "seats": [{"seat_number": num.strip()} for num in booking["seat_numbers"].split(",")],
            "booking_time": booking["booking_time"]
        }
        formatted_bookings.append(formatted_booking)

    return formatted_bookings


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)