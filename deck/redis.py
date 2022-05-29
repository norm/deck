import redis


class Redis:
    def __init__(self):
        self.redis = redis.Redis()
        self.namespace = 'deck'

    def key(self, key):
        return '%s:%s' % (self.namespace, key)

    def get(self, key):
        return self.redis.get(self.key(key))

    def set(self, key, value):
        return self.redis.set(self.key(key), value)

    def lindex(self, key, index):
        return self.redis.lindex(self.key(key), index)

    def lpop(self, key):
        return self.redis.lpop(self.key(key))

    def lpush(self, key, value):
        return self.redis.lpush(self.key(key), value)

    def ltrim(self, key, lower, upper):
        return self.redis.ltrim(self.key(key), lower, upper)

    def rpush(self, key, value):
        return self.redis.rpush(self.key(key), value)
