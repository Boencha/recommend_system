import sqlite3
import pandas as pd


def initialize_database():
    conn = sqlite3.connect("~/tg-bot/data/movie_recommendations.db")
    cursor = conn.cursor()

    # Создание таблицы для фильмов
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS movies (
        id INTEGER PRIMARY KEY,
        popularity REAL,
        production_countries TEXT,
        revenue REAL,
        runtime REAL,
        title TEXT,
        vote_average REAL,
        vote_count REAL,
        year REAL,
        soup TEXT
    )
    """)

    # Создание таблицы для пользователей
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        userId INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE
    )
    """)

    # Создание таблицы для рейтингов
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ratings (
        userId INTEGER,
        movieId INTEGER,
        rating REAL,
        timestamp INTEGER,
        PRIMARY KEY (userId, movieId)
    )
    """)
    conn.commit()
    conn.close()

def load_initial_data():
    conn = sqlite3.connect("~/tg-bot/data/movie_recommendations.db")
    cursor = conn.cursor()

    # Загрузка фильмов, если таблица пуста
    cursor.execute("SELECT COUNT(*) FROM movies")
    if cursor.fetchone()[0] == 0:
        movies_df = pd.read_csv('~/tg-bot/data/movie_data_ready.csv')
        movies_df.to_sql("movies", conn, if_exists="replace", index=False)

    # Загрузка пользователей, если таблица пуста
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        users_df = pd.read_csv('~/tg-bot/data/users_data.csv')
        users_df.to_sql("users", conn, if_exists="replace", index=False)

    # Загрузка рейтингов, если таблица пуста
    cursor.execute("SELECT COUNT(*) FROM ratings")
    if cursor.fetchone()[0] == 0:
        ratings_df = pd.read_csv('~/tg-bot/data/ratings_small.csv')
        ratings_df.to_sql("ratings", conn, if_exists="replace", index=False)

    conn.close()


def save_new_user(user_id, username):
    conn = sqlite3.connect("~/tg-bot/data/movie_recommendations.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO users (userId, username) VALUES (?, ?)",
        (user_id, username)
    )
    conn.commit()
    conn.close()


def save_user_rating(user_id, movie_id, rating):
    conn = sqlite3.connect("~/tg-bot/data/movie_recommendations.db")
    cursor = conn.cursor()
    # Проверка, существует ли уже рейтинг для этого пользователя и фильма
    cursor.execute("SELECT rating FROM ratings WHERE userId = ? AND movieId = ?", (user_id, movie_id))
    existing_rating = cursor.fetchone()
    
    if existing_rating:  # Если рейтинг уже существует, обновляем его
        cursor.execute("UPDATE ratings SET rating = ? WHERE userId = ? AND movieId = ?", (rating, user_id, movie_id))
    else:  # Если рейтинга нет, вставляем новый
        cursor.execute("INSERT INTO ratings (userId, movieId, rating) VALUES (?, ?, ?)", (user_id, movie_id, rating))
    
    conn.commit()
    conn.close()

def get_user_ratings(user_id):
    """Получение рейтингов пользователя из базы данных"""
    conn = sqlite3.connect("~/tg-bot/data/movie_recommendations.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT movieId, rating FROM ratings WHERE userId = ?",
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


if __name__ == "__main__":
    initialize_database()
    load_initial_data()
    
    
    
    
    

