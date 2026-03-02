from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import certifi
from dotenv import load_dotenv
import os

load_dotenv()


uri = "mongodb+srv://eujin31_db_user:" + os.getenv("MONGO_PASSWORD") + "@cluster0.r4hyyk6.mongodb.net/?appName=Cluster0"

# Create a new client and connect to the server
client = MongoClient(
    uri,
    server_api=ServerApi("1"),
    tls=True,
    tlsCAFile=certifi.where(),
)

# Send a ping to confirm a successful connection
try:
    client.admin.command("ping")
    print("Pinged your deployment. You successfully connected to MongoDB!")
except Exception as e:
    print(e)
