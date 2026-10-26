# since-worlds

The optional 3D models for Game mode in [Since](https://github.com/DanielAja/since.iso).

Since never ships these in the app. Game mode works without them: the World tab
draws a flat, 2D version of your world by default. If you want the 3D one, the app
downloads a single world pack from this repo's GitHub Releases when you ask for it,
checks it, and keeps it on the phone.

## What's here

| Path | What it is |
|---|---|
| `packs/<world>-v<N>.zip` | One world's models, each a `.usdz`, deflated into one zip |
| `manifest.json` | Every pack with its size, sha256 and the models inside |
| `tools/condense.py` | Turns the Blender exports into the packs and writes the manifest |

Release `v1` holds five worlds and the creatures that wander them:

| Pack | Models | Download | Unpacked |
|---|---|---|---|
| garden | 16 | 96 KB | 475 KB |
| forest | 10 | 108 KB | 496 KB |
| city | 11 | 117 KB | 825 KB |
| farm | 11 | 117 KB | 705 KB |
| coastal | 10 | 135 KB | 803 KB |
| ambient | 12 | 64 KB | 249 KB |

The same models came to 4.9 MB before condensing.

## How the app uses it

1. It reads `https://github.com/DanielAja/since-worlds/releases/download/v1/manifest.json`
   (the tag is pinned in the app). It also looks at the latest release's manifest
   and uses that one instead only if its `format` is one it knows and its
   `minAppVersion` is not newer than the app, so a fixed or smaller pack can
   reach people without an app update.
2. When someone taps Download for a world, it fetches that world's pack (and the
   ambient pack, once) from the same release.
3. It refuses anything whose size or sha256 doesn't match the manifest, then
   unzips into `Application Support/Worlds/<world>/<version>/`, which is excluded
   from iCloud and device backups. Settings can delete it again.
4. If a pack is missing, corrupt or the download fails, the World tab stays 2D.
   The clocks never wait on any of this.

Only model data (geometry and colours) is downloaded, never code. The request is a
plain HTTPS download from GitHub: no account, no identifiers, nothing about the
person or their clocks is sent. GitHub sees the IP address, as it does for any
download.

## Manifest

```json
{
  "format": 1,
  "version": 1,
  "tag": "v1",
  "minAppVersion": "1.1",
  "packs": [
    { "id": "garden", "file": "garden-v1.zip", "bytes": 98279,
      "unpackedBytes": 486873, "sha256": "...", "items": ["garden_apple", "..."] }
  ]
}
```

- `format` changes only when the layout of a pack changes in a way older apps
  can't read. Apps ignore a manifest with a format they don't know.
- `minAppVersion` is the oldest Since that can render the packs.
- `items` are the model names, without `.usdz`. The app's catalog maps every
  item it sells to one of them.

## Condensing

`tools/condense.py` does, per model:

- strips the UV sets (the models are flat colour; there are no textures to map),
  Blender's custom data and user properties, and any material nothing binds;
- quantises vertex positions to 1 mm and normals to two decimals;
- downscales any texture to 512 px on the longest side, 256 for everything but a
  few hero models (v1 has no textures, but later packs might);
- re-encodes binary `.usdc` and repackages the `.usdz`.

The wilting and dead versions of the garden plants are not packed. The app leans
and tints the healthy model instead, so one model covers all three states. Items
in the old catalog that never had a model of their own were dropped.

Every model in v1 passes `usdchecker --arkit`.

To rebuild, on a Mac (usdcat, usdzip and sips come with macOS):

```sh
python3 tools/condense.py --src <folder of world folders of .usdz> --out build --version 2 --min-app 1.1
```

then commit `build/packs/*` to `packs/` and `build/manifest.json` to the root, and
publish a release tagged `v2` with the packs and the manifest as assets. The zips
are written with fixed timestamps, so the same input gives the same bytes and the
same sha256.

## Adding a world

Add the world's models to `PACKS` in `tools/condense.py`, rebuild and release under
a new tag. The app needs an update before it shows a new world: its catalog (the
names, prices and translations of every item) lives in the app.

## Licence

The models were made for Since and are published here so the app can download
them. No other use is granted.
