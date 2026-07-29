class Config(object):
    LOGGER = True

    # Get this value from my.telegram.org/apps
    OWNER_ID = "7657218453"
    sudo_users = ["7657218453", "8679737897"]
    GROUP_ID = "-1003087506512"
    TOKEN = "8785412311:AAEQ9cQCV_G2_p9Ch9BuEItn-OITP4WS3Mg"
    mongo_url = "mongodb+srv://alisawaifubot_db_user:jxVLyqL2QxfWSZ6Q@cluster0.hdzxkt6.mongodb.net/?appName=Cluster0"
    PHOTO_URL = ["https://files.catbox.moe/sgo9in.png", "https://files.catbox.moe/kgcrnb.jpeg"]
    SUPPORT_CHAT = "ANIME_GROUP_HAI"
    UPDATE_CHAT = "SAND_VILLAGE"
    BOT_USERNAME = "AlisaWaifusBot"
    CHARA_CHANNEL_ID = "-1004310255455"
    api_id = "10658015"
    api_hash = "a0087bca748f86698c53d291c9e5b3af"
    
class Production(Config):
    LOGGER = True


class Development(Config):
    LOGGER = True
