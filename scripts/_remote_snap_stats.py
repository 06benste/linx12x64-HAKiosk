#!/usr/bin/env python3
import os
import time
import urllib.request
from PIL import Image, ImageStat

base = "http://127.0.0.1:17824"
tag = f"/tmp/ha_snap_{os.getpid()}"
data = b""
for _ in range(10):
    data = urllib.request.urlopen(base + "/snapshot.jpg", timeout=25).read()
    time.sleep(0.45)
graded = f"{tag}_graded.jpg"
plainp = f"{tag}_plain.jpg"
open(graded, "wb").write(data)
plain = urllib.request.urlopen(base + "/snapshot.jpg?plain=1", timeout=25).read()
open(plainp, "wb").write(plain)
# stable names for scp
open("/tmp/ha_user_graded.jpg", "wb").write(data)
open("/tmp/ha_user_plain.jpg", "wb").write(plain)
for name, path in (("plain", plainp), ("graded", graded)):
    im = Image.open(path).convert("RGB")
    st = ImageStat.Stat(im)
    print(name, im.size, "mean", [round(x, 1) for x in st.mean], "bytes", os.path.getsize(path))
