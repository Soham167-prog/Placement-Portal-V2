from flask_sqlalchemy import SQLAlchemy
from flask_security import Security
import redis

db = SQLAlchemy()
security = Security()

# Expose shared redis client instance connected to local Redis
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)