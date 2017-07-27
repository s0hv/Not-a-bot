import time


class OnCooldownException(Exception):
    def __init__(self, message, reuse=0.0):
        super().__init__(message + '\nCan be reused in {}s'.format(round(reuse, 3)))
        self._reuse = reuse


class CooldownManager:
    def __init__(self):
        self.cooldowns = {}

    def add_cooldown(self, name, rate, per):
        if name in self.cooldowns:
            raise KeyError('Name %s is already registered. Use remove cooldown first to remove it' % name)

        cooldown = Cooldown(name, rate, per)
        self.cooldowns[name] = cooldown
        return cooldown

    def remove_cooldown(self, name):
        try:
            del self.cooldowns[name]
        except KeyError:
            pass

    def get_cooldown(self, name):
        return self.cooldowns.get(name, None)

    def get_or_create(self, name, rate, per):
        if name not in self.cooldowns:
            cd = Cooldown(name, rate, per)
            self.cooldowns[name] = cd
        else:
            cd = self.cooldowns[name]

        return cd


class Cooldown:
    def __init__(self, name, rate, per):
        """

        Args:
            name: name of the cooldown
            rate `int`: how many times cooldown can be triggered in time defined by `per`
            per: how long till the cooldown is reset
        """

        self.name = name
        self.rate = int(rate)
        self.per = float(per)
        self._last_triggered = 0.0
        self._triggered = 0

    def trigger(self, errors=True):
        now = time.time()
        since_last = now - self._last_triggered
        if since_last > self.per:
            self._triggered = 1
            self._last_triggered = now
            return True
        elif since_last < self.per and self._triggered < self.rate:
            self._triggered += 1
            return True

        else:
            if errors:
                raise OnCooldownException('On cooldown.', reuse=self._last_triggered+self.per-now)
            else:
                return False
