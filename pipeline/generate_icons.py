"""Genere les icones PWA (goutte d'eau sur fond bleu degrade).
Rendu en supersampling x4 puis reduction -> bords lisses.
Sortie : maquette/icon-192.png et maquette/icon-512.png
"""
import math
from PIL import Image, ImageDraw

TOP = (47, 128, 237)     # #2f80ed
BOT = (28, 95, 196)      # #1c5fc4
SS = 4                   # supersampling

def render(size):
    S = size * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    px = img.load()
    # fond degrade vertical, pleine page (pour maskable)
    for y in range(S):
        t = y / (S - 1)
        r = int(TOP[0] + (BOT[0]-TOP[0])*t)
        g = int(TOP[1] + (BOT[1]-TOP[1])*t)
        b = int(TOP[2] + (BOT[2]-TOP[2])*t)
        for x in range(S):
            px[x, y] = (r, g, b, 255)
    draw = ImageDraw.Draw(img)
    # goutte : cercle bas + triangle (cotes tangents au cercle)
    cx = S/2
    R = 0.26*S
    cy = 0.60*S
    top = 0.18*S
    L = cy - top
    sin_b = math.sqrt(max(0.0, 1 - (R/L)**2))
    Tx = R*sin_b
    Ty = cy - R*R/L
    white = (255, 255, 255, 255)
    draw.ellipse([cx-R, cy-R, cx+R, cy+R], fill=white)
    draw.polygon([(cx, top), (cx-Tx, Ty), (cx+Tx, Ty)], fill=white)
    # petit reflet bleu clair dans la goutte
    rr = R*0.42
    hx, hy = cx - R*0.28, cy + R*0.05
    draw.ellipse([hx-rr*0.5, hy-rr, hx+rr*0.5, hy+rr],
                 fill=(180, 205, 245, 255))
    return img.resize((size, size), Image.LANCZOS)

for sz in (192, 512):
    render(sz).save("docs/icon-%d.png" % sz)
    print("ecrit maquette/icon-%d.png" % sz)
