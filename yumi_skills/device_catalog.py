"""Yumi's truthful, data-driven smart-home onboarding catalog.

Only connectors implemented in Yumi are listed. This is not copied from
Amazon's private Alexa device catalog.
"""
DEVICE_CATEGORIES = (
    {"id": "all", "label": "Tüm desteklenen kategoriler", "icon": "⌂", "types": ("light", "plug", "vacuum", "tv")},
    {"id": "lighting", "label": "Aydınlatma ve elektrik", "icon": "✦", "types": ("light", "plug")},
    {"id": "cleaning", "label": "Temizlik", "icon": "◉", "types": ("vacuum",)},
    {"id": "entertainment", "label": "TV ve medya", "icon": "▣", "types": ("tv",)},
)
DEVICE_TYPES = {
    "all": (
        ("all", "Tüm desteklenen cihaz türleri"),
        ("light", "Işık / ampul"),
        ("plug", "Akıllı priz / anahtar"),
        ("vacuum", "Robot süpürge"),
        ("tv", "TV / medya oynatıcı"),
    ),
    "lighting": (
        ("all", "Tüm aydınlatma ve elektrik türleri"),
        ("light", "Işık / ampul"),
        ("plug", "Akıllı priz / anahtar"),
    ),
    "cleaning": (("vacuum", "Robot süpürge"),),
    "entertainment": (("tv", "TV / medya oynatıcı"),),
}

INTEGRATIONS = (
    {
        "id": "tuya_via_ha",
        "label": "Tuya / Smart Life · Home Assistant",
        "device_types": ("light", "plug", "vacuum", "tv"),
        "model_scope": "Home Assistant'taki desteklenen Tuya entity'leri bağlantıdan sonra adlarıyla keşfedilir.",
    },
    {
        "id": "xiaomi_via_ha",
        "label": "Xiaomi Home / Roborock · Home Assistant",
        "device_types": ("light", "plug", "vacuum"),
        "model_scope": "Home Assistant entegrasyonunun sunduğu Xiaomi/Roborock modelleri keşifte listelenir; destek bölge ve modele göre değişir.",
    },
    {
        "id": "hue",
        "label": "Philips Hue Bridge",
        "device_types": ("light", "plug"),
        "model_scope": "Hue Bridge'e bağlı uyumlu ışıklar ve prizler eşleştirmeden sonra keşfedilir.",
    },
    {
        "id": "ikea",
        "label": "IKEA Home Smart · DIRIGERA",
        "device_types": ("light", "plug"),
        "model_scope": "DIRIGERA hub'ına bağlı desteklenen ışıklar ve prizler keşifte listelenir.",
    },
    {
        "id": "tapo",
        "label": "TP-Link Tapo / Kasa",
        "device_types": ("light", "plug"),
        "model_scope": "Yerel ağda keşfedilen uyumlu Tapo/Kasa ışık ve prizleri bağlantıdan sonra listelenir.",
    },
    {
        "id": "home_assistant",
        "label": "Home Assistant · genel köprü",
        "device_types": ("light", "plug", "vacuum", "tv"),
        "model_scope": "Yumi şu anda HA'dan ışık, priz/anahtar, süpürge ve medya oynatıcı entity'lerini alır.",
    },
)

def device_types_for_category(category_id):
    return DEVICE_TYPES.get(category_id, DEVICE_TYPES["all"])

def integrations_for_device_type(device_type):
    if device_type == "all":
        return INTEGRATIONS
    return tuple(item for item in INTEGRATIONS if device_type in item["device_types"])

def integration_by_id(integration_id):
    return next((item for item in INTEGRATIONS if item["id"] == integration_id), None)
