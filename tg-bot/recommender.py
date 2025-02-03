import sqlite3
import pandas as pd
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD
import hnswlib
import pickle
from sklearn.metrics.pairwise import cosine_similarity


conn = sqlite3.connect('~/tg-bot/data/movie_recommendations.db')
cursor = conn.cursor()


def load_movies():
    conn = sqlite3.connect("~/tg-bot/data/movie_recommendations.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM movies")
    result = cursor.fetchall()
    conn.close()
    movies =  pd.DataFrame(result, columns=['id', 'popularity','production_countries','runtime','title','vote_average','vote_count','year','soup'])
    return movies

def load_ratings():
    conn = sqlite3.connect("~/tg-bot/data/movie_recommendations.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ratings")
    result = cursor.fetchall()
    conn.close()
    return pd.DataFrame(result, columns=['userId', 'movieId', 'rating', 'timestamp'])



def formula(df, m, C):
    v = df['vote_count']
    R = df['vote_average']
    return (v/(v+m) * R) + (m/(m+v) * C)

def popularity_recomend():
    movies_df = load_movies()
    vote_counts = movies_df[movies_df['vote_count'].notnull()]['vote_count'].astype('int')
    vote_averages = movies_df[movies_df['vote_average'].notnull()]['vote_average'].astype('int')
    C = vote_averages.mean()
    m = vote_counts.quantile(0.95)
    
    qualified = movies_df[(movies_df['vote_count'] >= m) & (movies_df['vote_count'].notnull()) & (movies_df['vote_average'].notnull())][['id', 'popularity','title','vote_average','vote_count','year']]
    qualified['vote_count'] = qualified['vote_count'].astype('int')
    qualified['vote_average'] = qualified['vote_average'].astype('int')
    
    qualified['wr'] = qualified.apply(lambda row: formula(row, m, C), axis=1)
    qualified = qualified.sort_values('wr', ascending=False)
    
    return qualified['id'].head(250)


def create_ratings_matrix(ratings, movies, user_col='userId', movie_col='movieId', rating_col='rating'):
    info = pd.merge(ratings, movies[['id']], left_on='movieId', right_on='id', how='inner').sort_values('userId')
    info = info.drop(['id'], axis=1)
    ratings_matrix = info.pivot_table(index=user_col, columns=movie_col, values=rating_col, fill_value=0)
    return ratings_matrix

def prepare_tfidf_embeddings(movies, description_col='soup'):
    movies['soup'] = movies['soup'].fillna('')
    vectorizer = TfidfVectorizer(stop_words='english', max_features=15000)
    tfidf_matrix = vectorizer.fit_transform(movies[description_col])
    tfidf_embeddings = tfidf_matrix.toarray()
    
    
    
    with open("~/tg-bot/data/tfidf_embeddings.pkl", "wb") as f:
        pickle.dump(tfidf_embeddings, f)
    
    with open("~/tg-bot/data/tfidf_vectorizer.pkl", "wb") as f:
        pickle.dump(vectorizer, f)
        
    return tfidf_embeddings



def prepare_data_for_recommendations(ratings_matrix, movies):

    svd = TruncatedSVD(n_components=50, random_state=42)
    movie_embeddings_svd = svd.fit_transform(ratings_matrix.T)
    
    with open("~/tg-bot/data/tfidf_embeddings.pkl", "rb") as f:
        tfidf_embeddings = pickle.load(f)
    

    if movie_embeddings_svd.shape[0] < tfidf_embeddings.shape[0]:
        padding = np.zeros((tfidf_embeddings.shape[0] - movie_embeddings_svd.shape[0], movie_embeddings_svd.shape[1]))
        movie_embeddings_svd = np.vstack([movie_embeddings_svd, padding])
    
    combined_embeddings = np.hstack([movie_embeddings_svd, tfidf_embeddings])
    

    index = hnswlib.Index(space='l2', dim=combined_embeddings.shape[1])
    index.init_index(max_elements=combined_embeddings.shape[0], ef_construction=200, M=16)
    index.add_items(combined_embeddings)
    
    movie_ids = movies['id'].values
    movie_titles = movies['title'].values

    movie_id_to_index = {movie_id: idx for idx, movie_id in enumerate(movie_ids)}


    with open("~/tg-bot/data/movie_id_to_index.pkl", "wb") as f:
        pickle.dump(movie_id_to_index, f)

    with open("~/tg-bot/data/movie_titles.pkl", "wb") as f:
        pickle.dump(dict(zip(movie_ids, movie_titles)), f)

    index.save_index("~/tg-bot/data/hybrid_hnsw_index.bin")
    with open("~/tg-bot/data/combined_embeddings.pkl", "wb") as f:
        pickle.dump(combined_embeddings, f)

    return svd



def get_hybrid_recommendations(user_id, ratings_matrix, movies, tfidf_embeddings, top_k=10, alpha=0.5):
    with open("~/tg-bot/data/combined_embeddings.pkl", "rb") as f:
        combined_embeddings = pickle.load(f)
    
    with open("~/tg-bot/data/movie_id_to_index.pkl", "rb") as f:
        movie_id_to_index = pickle.load(f)

    index = hnswlib.Index(space='l2', dim=combined_embeddings.shape[1])
    index.load_index("~/tg-bot/data/hybrid_hnsw_index.bin")

    watched_movies = ratings_matrix.loc[user_id][ratings_matrix.loc[user_id] > 0].index.values
    popular_movies = movies[movies['popularity'] > movies['popularity'].median()]
    
    recommendations = {}

    for movie_id in watched_movies:
        if movie_id in movie_id_to_index:
            movie_idx = movie_id_to_index[movie_id]
            
            neighbors, distances = index.knn_query(combined_embeddings[movie_idx], k=top_k + len(watched_movies))
            
            for neighbor_idx, distance in zip(neighbors[0], distances[0]):
                recommended_movie_id = list(movie_id_to_index.keys())[list(movie_id_to_index.values()).index(neighbor_idx)]
                if recommended_movie_id not in watched_movies and recommended_movie_id in popular_movies['id'].values:
                    if recommended_movie_id not in recommendations:
                        recommendations[recommended_movie_id] = 0
                    recommendations[recommended_movie_id] += (1 - alpha) * (1 / (1 + distance))


            movie_vector = tfidf_embeddings[movie_idx].reshape(1, -1)
            movie_cosine_sim = cosine_similarity(movie_vector, tfidf_embeddings)[0]
            
            cosine_sim_indices = np.argsort(-movie_cosine_sim)
            for idx in cosine_sim_indices:
                if idx < len(movie_id_to_index):  
                    cosine_movie_id = list(movie_id_to_index.keys())[idx]
                    if (
                        cosine_movie_id not in watched_movies 
                        and cosine_movie_id in popular_movies['id'].values
                    ):
                        if cosine_movie_id not in recommendations:
                            recommendations[cosine_movie_id] = 0
                        recommendations[cosine_movie_id] += alpha * (1 - movie_cosine_sim[idx])



    sorted_recommendations = sorted(recommendations.items(), key=lambda x: x[1], reverse=True)


    recommended_movie_ids = [rec[0] for rec in sorted_recommendations[:]]
    return recommended_movie_ids[:]



def hybrid_recommendations(userId):
    ratings = load_ratings()
    movies = load_movies()
    
    with open("~/tg-bot/data/tfidf_embeddings.pkl", "rb") as f:
        tfidf_embeddings = pickle.load(f)
        
    ratings_matrix = create_ratings_matrix(ratings, movies[['id', 'title']], user_col='userId', movie_col='movieId', rating_col='rating')

    recommendations = get_hybrid_recommendations(userId, ratings_matrix, movies, tfidf_embeddings, top_k=10)
    return recommendations


