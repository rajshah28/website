from pymongo import MongoClient
import os
# Setup MongoDB connection using MONGODB_URI from the environment
MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "TEMP")
if MONGODB_URI:
    client = MongoClient(MONGODB_URI)
    db = client[MONGODB_DATABASE]
    responses_collection = db["responses"]
    print("Connected to MongoDB.")
else:
    responses_collection = None
    print("MONGODB_URI not set; responses will not be saved in MongoDB.")
