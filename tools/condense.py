#!/usr/bin/env python3
"""Condense the Blender-exported USDZ models into small world packs for Since.

    python3 tools/condense.py --src <dir with one folder of .usdz per world> \
        --out build --version 1 --min-app 1.1

What it does, per model:
  1. Pulls the .usdc layer out of the .usdz and converts it to text (usdcat).
  2. Strips what the app never uses: UV sets (the models are flat colour,
     there are no textures to map), Blender's custom data and user properties,
     and any material that nothing binds.
  3. Quantises vertex positions to 1 mm and normals to two decimals. Flat
     shaded, half a metre tall: nobody can see the difference, and deflate
     squeezes the repeated digits far better.
  4. Downscales any texture to 512 px on its longest side (256 for anything
     that isn't a hero item). The v1 models carry none, but packs added later
     might.
  5. Re-encodes binary .usdc (usdcat) and repackages a .usdz (usdzip).

Per world, the condensed models go into one deflate zip, and manifest.json
lists each pack's size, sha256 and the models inside it.

The wilting and dead variants of the garden plants are not packed: the app
leans and tints the healthy model instead, so one model covers all three.

Needs macOS (usdcat, usdzip and sips ship with it) and Python 3.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

# The v1 worlds and the models each one needs. Anything not listed (the
# _wilt and _dead variants, the other six worlds) is left behind.
PACKS = {
    "garden": ["garden_sprout", "garden_tulip", "garden_daisy", "garden_bluebell",
               "garden_mushroom", "garden_bush", "garden_rock", "garden_lantern",
               "garden_fence", "garden_pine", "garden_apple", "garden_bench",
               "garden_pond", "garden_money_tree", "garden_dumbbell", "garden_gnome"],
    "forest": ["forest_fern", "forest_mushrooms", "forest_rock", "forest_pine",
               "forest_oak", "forest_log", "forest_deer", "forest_trail",
               "forest_beehive", "forest_fox"],
    "city":   ["city_house", "city_park", "city_streetlight", "city_shop",
               "city_fountain", "city_statue_park", "city_tram", "city_tower",
               "city_bank", "city_gym", "city_statue"],
    "farm":   ["farm_wheat", "farm_haybale", "farm_chicken", "farm_well",
               "farm_cow", "farm_tractor", "farm_barn", "farm_silo",
               "farm_gym", "farm_stand", "farm_scarecrow"],
    "coastal": ["coastal_shell", "coastal_palm", "coastal_umbrella",
                "coastal_sandcastle", "coastal_boat", "coastal_dock",
                "coastal_lighthouse", "coastal_surf", "coastal_market",
                "coastal_whale"],
    # Creatures that wander the five worlds above. Shared, so one download.
    "ambient": ["amb_butterfly", "amb_bee", "amb_bird", "amb_person", "amb_bus",
                "amb_car", "amb_chicken", "amb_sheep", "amb_deer", "amb_firefly",
                "amb_seagull", "amb_fish"],
}

# Items big enough on screen to keep a 512 px texture. Everything else, 256.
HERO = {"garden_pond", "garden_apple", "city_tower", "farm_barn", "coastal_lighthouse"}

POINT_DECIMALS = 3
NORMAL_DECIMALS = 2


def run(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)


def find_blocks(text, header_regex):
    """(start, end) spans of every `header { ... }` block, braces matched."""
    spans = []
    for m in re.finditer(header_regex, text):
        open_at = text.find("{", m.end())
        if open_at < 0:
            continue
        depth = 0
        for i in range(open_at, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    spans.append((m.start(), i + 1))
                    break
    return spans


def quantise(match, decimals):
    def fmt(number):
        s = "%.*f" % (decimals, float(number.group(0)))
        s = s.rstrip("0").rstrip(".") if "." in s else s
        return "0" if s in ("-0", "") else s
    return re.sub(r"-?\d+\.\d+(?:e-?\d+)?", fmt, match.group(0))


def condense_layer(text):
    # UVs: no textures, nothing to map.
    text = re.sub(r'\n\s*texCoord2f\[\] primvars:\w+ = \[[^\]]*\]\s*\(\s*interpolation = "\w+"\s*\)', "", text)
    text = re.sub(r"\n\s*int\[\] primvars:\w+:indices = \[[^\]]*\]", "", text)
    # Exporter bookkeeping.
    text = re.sub(r"\n\s*custom string userProperties:[^\n]*", "", text)
    text = re.sub(r"customData = \{\s*dictionary Blender = \{[^{}]*\}\s*\}", "", text)
    text = re.sub(r'\n\s*doc = "Blender[^"\n]*"', "", text)
    # Materials nothing binds.
    bound = set(re.findall(r"rel material:binding = <([^>]+)>", text))
    for start, end in reversed(find_blocks(text, r'\n\s*def Material "(\w+)"')):
        header = re.match(r'\n\s*def Material "(\w+)"', text[start:end])
        scope = text.rfind('def Scope "', 0, start)
        scope_name = re.match(r'def Scope "(\w+)"', text[scope:]).group(1) if scope >= 0 else ""
        path_tail = "/%s/%s" % (scope_name, header.group(1))
        if not any(b.endswith(path_tail) for b in bound):
            text = text[:start] + text[end:]
    # Precision nobody can see.
    text = re.sub(r"point3f\[\] points = \[[^\]]*\]", lambda m: quantise(m, POINT_DECIMALS), text)
    text = re.sub(r"normal3f\[\] normals = \[[^\]]*\]", lambda m: quantise(m, NORMAL_DECIMALS), text)
    return text


def downscale_textures(folder, hero):
    limit = 512 if hero else 256
    for name in os.listdir(folder):
        if name.lower().endswith((".png", ".jpg", ".jpeg")):
            run("sips", "-Z", str(limit), os.path.join(folder, name))


def condense_model(src_usdz, out_usdz, work, hero):
    unpacked = os.path.join(work, "unpacked")
    shutil.rmtree(unpacked, ignore_errors=True)
    os.makedirs(unpacked)
    with zipfile.ZipFile(src_usdz) as z:
        z.extractall(unpacked)
    layers = [n for n in os.listdir(unpacked) if n.endswith((".usdc", ".usda", ".usd"))]
    if len(layers) != 1:
        sys.exit("%s: expected one root layer, found %s" % (src_usdz, layers))
    downscale_textures(unpacked, hero)
    textures = sorted(n for n in os.listdir(unpacked) if n.lower().endswith((".png", ".jpg", ".jpeg")))

    stem = os.path.splitext(os.path.basename(out_usdz))[0]
    text_layer = os.path.join(work, stem + ".usda")
    run("usdcat", os.path.join(unpacked, layers[0]), "-o", text_layer)
    with open(text_layer) as f:
        condensed = condense_layer(f.read())
    with open(text_layer, "w") as f:
        f.write(condensed)
    binary_layer = os.path.join(unpacked, stem + ".usdc")
    if os.path.join(unpacked, layers[0]) != binary_layer:
        os.remove(os.path.join(unpacked, layers[0]))
    run("usdcat", text_layer, "-o", binary_layer)
    if os.path.exists(out_usdz):
        os.remove(out_usdz)
    # usdzip resolves the inputs relative to the working directory.
    cwd = os.getcwd()
    os.chdir(unpacked)
    try:
        run("usdzip", os.path.abspath(out_usdz), stem + ".usdc", *textures)
    finally:
        os.chdir(cwd)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="folder holding <world>/<model>.usdz")
    ap.add_argument("--out", default="build")
    ap.add_argument("--version", type=int, default=1)
    ap.add_argument("--min-app", default="1.1", help="oldest Since version that can render these packs")
    args = ap.parse_args()

    out = os.path.abspath(args.out)
    packs_dir = os.path.join(out, "packs")
    os.makedirs(packs_dir, exist_ok=True)
    manifest = {"format": 1, "version": args.version, "tag": "v%d" % args.version,
                "minAppVersion": args.min_app, "packs": []}

    with tempfile.TemporaryDirectory() as work:
        for pack, models in PACKS.items():
            folder = os.path.join(work, pack)
            os.makedirs(folder)
            source_bytes = 0
            for model in models:
                src = os.path.join(args.src, pack, model + ".usdz")
                if not os.path.exists(src):
                    sys.exit("missing source model %s" % src)
                source_bytes += os.path.getsize(src)
                condense_model(src, os.path.join(folder, model + ".usdz"), work, model in HERO)
            unpacked = sum(os.path.getsize(os.path.join(folder, m + ".usdz")) for m in models)
            name = "%s-v%d.zip" % (pack, args.version)
            path = os.path.join(packs_dir, name)
            if os.path.exists(path):
                os.remove(path)
            # Fixed timestamps and order: the same input gives the same bytes.
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
                for model in sorted(models):
                    info = zipfile.ZipInfo(model + ".usdz", date_time=(2026, 10, 25, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o644 << 16
                    with open(os.path.join(folder, model + ".usdz"), "rb") as f:
                        z.writestr(info, f.read(), compresslevel=9)
            size = os.path.getsize(path)
            manifest["packs"].append({
                "id": pack, "file": name, "bytes": size, "unpackedBytes": unpacked,
                "sha256": sha256(path), "items": sorted(models)})
            print("%-8s %2d models  source %7d B  unpacked %7d B  pack %7d B"
                  % (pack, len(models), source_bytes, unpacked, size))

    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
