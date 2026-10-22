# -*- coding: utf-8 -*-
"""极简磁盘缓存：同一份 JD + 同一个 prompt，不重复调模型。

为什么需要：改报告模板、调排版的时候要反复重跑，没有缓存每次都烧钱、
也等得久。缓存放在 sk/_cache/（已在 .gitignore 里）。
"""
import hashlib
import json
import os

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cache")


def _path(name, text):
    h = hashlib.sha1((name + "\x00" + (text or "")).encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, h + ".json")


def get(name, text):
    try:
        with open(_path(name, text), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, OSError, ValueError):
        return None


def put(name, text, obj):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_path(name, text), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        return True
    except OSError:
        return False


def stats():
    try:
        n = len([x for x in os.listdir(CACHE_DIR) if x.endswith(".json")])
    except OSError:
        n = 0
    return n
