import enum


class TimestampFormat(enum.Enum):
    ShortTime = 't'
    LongTime = 'T'
    ShortDate = 'd'
    LongDate = 'D'
    ShortDateTime = 'f'
    LongDateTime = 'F'
    Relative = 'R'
