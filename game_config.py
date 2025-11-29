from enum import Enum

class Role(Enum):
    VILLAGER = "Villager"
    WEREWOLF = "Werewolf"
    CUPID = "Cupid"
    ANGEL = "Angel"
    SHERIFF = "Sheriff"
    FORTUNE_TELLER = "Fortune Teller"
    FISHERMAN = "Fisherman"
    UNDERTAKER = "Undertaker"
    FLOWER_CHILD = "Flower Child"

MIN_PLAYERS = 5

WOLF_RATIO = 3 # One werewolf per 3 players