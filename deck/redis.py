import redis


class Redis:
    def __init__(self):
        self.redis = redis.Redis()
        self.namespace = 'deck'

    def key(self, key):
        return '%s:%s' % (self.namespace, key)

    def delete(self, key):
        return self.redis.delete(self.key(key))

    def get(self, key):
        return self.redis.get(self.key(key))

    def getdel(self, key):
        try:
            value = self.redis.getdel(self.key(key))
        except redis.exceptions.ResponseError:
            value = self.redis.get(self.key(key))
            self.redis.delete(self.key(key))
        return value

    def lindex(self, key, index):
        return self.redis.lindex(self.key(key), index)

    def lpop(self, key):
        return self.redis.lpop(self.key(key))

    def lpush(self, key, value):
        return self.redis.lpush(self.key(key), value)

    def lrange(self, key, lower, upper):
        return self.redis.lrange(self.key(key), lower, upper)

    def lrem(self, key, count, element):
        return self.redis.lrem(self.key(key), count, element)

    def ltrim(self, key, lower, upper):
        return self.redis.ltrim(self.key(key), lower, upper)

    def rpush(self, key, value):
        return self.redis.rpush(self.key(key), value)

    def set(self, key, value):
        return self.redis.set(self.key(key), value)
