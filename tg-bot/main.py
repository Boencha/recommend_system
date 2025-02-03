import sqlite3
import telebot
from database import save_user_rating, save_new_user
from dotenv import load_dotenv
import os
from telebot import types
from recommender import popularity_recomend, hybrid_recommendations
import logging
import json
from collections import defaultdict

user_recommendations = defaultdict(list)


load_dotenv() 
API_TOKEN = os.getenv('API_TOKEN')
bot = telebot.TeleBot(API_TOKEN)

logging.basicConfig(level=logging.DEBUG)


@bot.message_handler(commands=['start'])
def start(message):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("Новый пользователь", "Уже зарегистрирован")
    bot.send_message(
        message.chat.id,
        "Привет! Я MovieMateBot. Выбери один из вариантов ниже:",
        reply_markup=markup
    )


@bot.message_handler(func=lambda message: message.text == "Новый пользователь")
def new_user(message):
    bot.send_message(message.chat.id, "Пожалуйста, введи свой никнейм.")
    bot.register_next_step_handler(message, register_new_user)

def register_new_user(message):
    username = message.text.strip()

    if check_user_exists(username):
        bot.send_message(message.chat.id, "Этот никнейм уже занят. Пожалуйста, выбери другой.")
        bot.register_next_step_handler(message, register_new_user)
    else:
        user_id = generate_new_user_id()
        save_new_user(user_id, username)
        bot.send_message(message.chat.id, f"Приятно познакомиться, {username}! Ты зарегистрирован. Теперь нужно оценить несколько фильмов для персональных рекомендаций.")
        get_movie_suggestions(message, user_id)

@bot.message_handler(func=lambda message: message.text == "Уже зарегистрирован")
def existing_user_prompt(message):
    bot.send_message(message.chat.id, "Пожалуйста, введи свой никнейм.")
    bot.register_next_step_handler(message, existing_user)

def existing_user(message):
    username = message.text.strip()

    if check_user_exists(username):
        user_id = get_user_id_by_username(username)
        bot.send_message(message.chat.id, f"Привет, {username}! Мы рады тебя видеть снова!")
        bot.send_message(message.chat.id, f"Вот твоя подброка:")
        send_personal_recommendations(message, user_id)
    else:
        bot.send_message(message.chat.id, "Такого пользователя не найдено. Попробуй зарегистрироваться, выбрав 'Новый пользователь'.")

def check_user_exists(username):
    conn = sqlite3.connect("/Users/bainadandaeva/Desktop/recomend_system/tg-bot/data/movie_recommendations.db")
    cursor = conn.cursor()
    cursor.execute("SELECT userId FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    return user is not None

def get_user_id_by_username(username):
    conn = sqlite3.connect("/Users/bainadandaeva/Desktop/recomend_system/tg-bot/data/movie_recommendations.db")
    cursor = conn.cursor()
    cursor.execute("SELECT userId FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    return user[0] if user else None

def generate_new_user_id():
    conn = sqlite3.connect("/Users/bainadandaeva/Desktop/recomend_system/tg-bot/data/movie_recommendations.db")
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(userId) FROM users")
    max_id = cursor.fetchone()[0]
    conn.close()
    return (max_id or 0) + 1

def get_movie_suggestions(message, user_id):
    recommendations = popularity_recomend()
    user_recommendations[user_id] = recommendations
    start_index = 0
    
    recommendations = recommendations.tolist()
    
    markup = create_movie_buttons(recommendations, user_id, start_index)
    bot.send_message(message.chat.id, "Выберите фильм для оценки:", reply_markup=markup)

def create_movie_buttons(recommendations, user_id, start_index=0):
    markup = types.InlineKeyboardMarkup()
    for i, movie_id in enumerate(recommendations[start_index : start_index + 5]):
        movie_title = get_movie_title_by_id(movie_id)
        callback_data = f"ratedmovie_{movie_id}_{user_id}"
        markup.add(types.InlineKeyboardButton(text=movie_title, callback_data=callback_data))
    
    markup.add(types.InlineKeyboardButton("Показать ещё", callback_data=f"show_more_{start_index + 5}_{user_id}"))
    return markup

@bot.callback_query_handler(func=lambda call: call.data.startswith("show_more_"))
def show_more_movies(call):
    data_parts = call.data.split("_")
    start_index = int(data_parts[2])
    user_id = int(data_parts[3])
    recommendations = user_recommendations.get(user_id, [])
    
    markup = create_movie_buttons(recommendations, user_id, start_index)
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("ratedmovie_"))
def handle_rating(call):
    data_parts = call.data.split("_")
    movie_id = int(data_parts[1])
    user_id = int(data_parts[2])
    
    movie_title = get_movie_title_by_id(movie_id)
    bot.send_message(call.message.chat.id, f"Вы выбрали фильм: {movie_title}.")

    existing_rating = check_movie_already_rated(user_id, movie_id)
    
    if existing_rating is not None:
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(
            telebot.types.InlineKeyboardButton("Изменить рейтинг", callback_data=f"changerating_{movie_id}_{user_id}"),
            telebot.types.InlineKeyboardButton("Оставить как есть", callback_data=f"nottouchrating_{movie_id}_{user_id}")
        )
        bot.send_message(
            call.message.chat.id,
            f"Вы уже оценили фильм '{movie_title}' на {existing_rating} из 5. Хотите изменить рейтинг?",
            reply_markup=markup)

    else:
        send_rating_options(call.message, movie_id, user_id)
        
@bot.callback_query_handler(func=lambda call: call.data.startswith("changerating_") or call.data.startswith("nottouchrating_"))
def handle_update_rating(call):
    action, movie_id, user_id = call.data.split("_")
    movie_id = int(movie_id)
    user_id = int(user_id)
    
    if action == "changerating":
        bot.send_message(call.message.chat.id, "Вы выбрали изменить рейтинг.")
        send_rating_options(call.message, movie_id, user_id)
        
    elif action == "nottouchrating":
        existing_rating = check_movie_already_rated(user_id, movie_id)
        bot.send_message(call.message.chat.id, f"Оценка для фильма оставлена: {existing_rating} из 5.")
        count_ratted(call.message, user_id)

def send_rating_options(message, movie_id, user_id):
    markup = types.InlineKeyboardMarkup()
    for rating in [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]:
        callback_data = f"rate_{movie_id}_{rating}_{user_id}"
        markup.add(types.InlineKeyboardButton(text=str(rating), callback_data=callback_data))
    bot.send_message(message.chat.id, "Выберите оценку:", reply_markup=markup)

def count_ratted(message, user_id):
    rated_count = get_rated_movie_count(user_id)
    
    if rated_count >= 5:
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(
            telebot.types.InlineKeyboardButton("Продолжить настройку рекомендаций", callback_data=f"continue_rating_{user_id}"),
            telebot.types.InlineKeyboardButton("К персональным рекомендациям", callback_data=f"finish_rating_{user_id}")
        )
        bot.send_message(message.chat.id,
                         "Вы уже оценили 5 или больше фильмов. Хотите продолжить настройку персональных рекомендаций или перейти к Вашим рекомендациям?",
                         reply_markup=markup)
    else:
        remaining_count = 5 - rated_count
        bot.send_message(message.chat.id,
                         f"Вам нужно оценить еще {remaining_count} фильма(ов), чтобы завершить настройку рекомендаций.")
        get_movie_suggestions(message, user_id)
        
def check_movie_already_rated(user_id, movie_id):
    conn = sqlite3.connect("/Users/bainadandaeva/Desktop/recomend_system/tg-bot/data/movie_recommendations.db")
    cursor = conn.cursor()
    cursor.execute("SELECT rating FROM ratings WHERE userId = ? AND movieId = ?", (user_id, movie_id))
    rating = cursor.fetchone()
    conn.close()
    return rating[0] if rating else None

def get_rated_movie_count(user_id):
    conn = sqlite3.connect("~/tg-bot/data/movie_recommendations.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM ratings WHERE userId = ?", (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count


@bot.callback_query_handler(func=lambda call: call.data.startswith("continue_rating_"))
def continue_rating(call):
    user_id = int(call.data.split("_")[2])
    bot.send_message(call.message.chat.id, "Продолжаем настройку рекомендаций.")
    get_movie_suggestions(call.message, user_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("finish_rating_"))
def finish_rating(call):
    user_id = int(call.data.split("_")[2])
    bot.send_message(call.message.chat.id, "Готовим персональные рекомендации...")
    send_personal_recommendations(call.message, user_id)


@bot.callback_query_handler(func=lambda call: "rate_" in call.data)
def rate_movie(call):
    _, movie_id, rating, user_id = call.data.split("_")
    movie_id, rating, user_id = int(movie_id), float(rating), int(user_id)
    
    old_rating = check_movie_already_rated(user_id, movie_id)
    save_user_rating(user_id, movie_id, rating)
    
    if old_rating is not None:
        bot.send_message(
            call.message.chat.id,
            f"Вы изменили рейтинг фильма '{get_movie_title_by_id(movie_id)}' с {old_rating} на {rating}."
        )
    else:
        bot.send_message(
            call.message.chat.id,
            f"Вы оценили фильм '{get_movie_title_by_id(movie_id)}' на {rating} из 5."
        )
    count_ratted(call.message, user_id)

def send_personal_recommendations(message, user_id):
    recommendations = hybrid_recommendations(user_id)
    user_recommendations[user_id] = recommendations
    
    markup = create_movie_buttons(recommendations, user_id)
    bot.send_message(message.chat.id, "Ваши персональные рекомендации:", reply_markup=markup)

def get_movie_title_by_id(movie_id):
    conn = sqlite3.connect("/Users/bainadandaeva/Desktop/recomend_system/tg-bot/data/movie_recommendations.db")
    cursor = conn.cursor()
    cursor.execute("SELECT title FROM movies WHERE id = ?",(int(movie_id),))
    movie = cursor.fetchone()
    conn.close()
    if movie:
        return movie[0]
    else:
        return f"Неизвестный фильм (ID: {movie_id})"



if __name__ == "__main__":
    bot.polling(none_stop=True)
