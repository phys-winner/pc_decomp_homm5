"""Adventure-map LOD -> full model redirects, derived from an edition's own records.

The adventure map shows creatures and heroes with separate reduced "_LOD"
models (fewer polygons, half-size textures): AdvMapMonsterShared.Model and the
hero's HeroCharacterAdventure character reference them, while combat uses the
full model of the same creature (Creature -> CreatureVisual.AnimCharacter) or
hero (HeroCharacterArena). The engine has no switch between the two: the data
names the LOD files. The port's toggle port_lod_fix (android/host/lod_models.c)
resolves those references to the full models instead, with this table:

  model   LOD model of a map monster      -> the creature's combat model
          LOD model of a map hero (and its per-player colour models)
                                          -> the hero's combat model (colours)
  anims   a map monster's LOD-bound adventure animations -> the combat set of
          the full model (the LOD skeleton's tracks do not fit it); heroes keep
          their adventure set (idle/move), unless the combat set has both, which
          then fits the full model exactly

A reference is redirected only where every record that uses it agrees, and a
LOD whose mesh is not reduced (at least 90% of the full one) is kept (no gain).
Run:  python -X utf8 tools/lod_models.py --write   (all editions, from port.json)
      python -X utf8 tools/lod_models.py --edition toe --report
"""
import argparse
import collections
import json
import posixpath
import re
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

OUTPUT = ROOT / "android/host/lod_models_table.h"
EDITIONS = ("toe", "vanilla", "hof")
# Their combat sets have no movement, so the map would drive the full model
# with the LOD's adventure animations, and these skeletons differ: the
# community mod (Creatures&Heroes_NormalLODModels, 2025) found both unusable
# that way (the generic knight) or rebuilt one by hand (RuneMage).
KEEP = {"characters/heroes/knight_lod.(character).xdb", "characters/heroes/runemage_lod.(character).xdb"}


class Data:
    def __init__(self, archives):
        self.names = {}
        for path in reversed(archives):          # later wins: highest priority last
            archive = zipfile.ZipFile(path)
            for info in archive.infolist():
                self.names[info.filename.lower()] = (archive, info.filename)
        self.cache = {}

    def read(self, path):
        if not path:
            return None
        key = path.lstrip("/").lower()
        if key not in self.cache:
            entry = self.names.get(key)
            self.cache[key] = entry[0].read(entry[1]) if entry else None
        return self.cache[key]

    def exists(self, path):
        return bool(path) and path.lstrip("/").lower() in self.names


def resolve(base, href):
    """An href as the engine resolves it: absolute, or relative to the record's folder."""
    if not href:
        return None
    href = href.split("#", 1)[0].replace("\\", "/")
    if not href:
        return None
    if href.startswith("/"):
        return posixpath.normpath(href).lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), href)).lstrip("/")


def field(data, tag):
    m = re.search(rb"<" + tag.encode() + rb"\s+href=\"([^\"]*)\"", data or b"")
    return m.group(1).decode("utf-8", "replace") if m else None


def text_field(data, tag):
    m = re.search(rb"<" + tag.encode() + rb">([^<]*)</" + tag.encode() + rb">", data or b"")
    return m.group(1).decode("utf-8", "replace").strip() if m else None


def items(data, tag):
    m = re.search(rb"<" + tag.encode() + rb">(.*?)</" + tag.encode() + rb">", data or b"", re.S)
    return [h.decode("utf-8", "replace") for h in re.findall(rb'<Item\s+href="([^"]*)"', m.group(1))] if m else []


def root_tag(data):
    m = re.search(rb"<([A-Za-z_][A-Za-z0-9_]*)[\s>]", (data or b"")[(data or b"").find(b"?>") + 2:])
    return m.group(1).decode() if m else None


def anim_kinds(db, path):
    data = db.read(path)
    return {k.decode(): resolve(path, h.decode()) for k, h in
            re.findall(rb'<Kind>([^<]*)</Kind>\s*<Anim\s+href="([^"]*)"', data or b"")}


def lod_bound(db, path):
    """An animation set exported from a _LOD scene binds to the LOD skeleton."""
    data = db.read(path)
    if data is None:
        return False
    scenes = re.findall(rb'<ExpSrcScene\s+href="([^"]*)"', data)
    for anim in anim_kinds(db, path).values():
        scenes += re.findall(rb'<SrcName\s+href="([^"]*)"', db.read(anim) or b"")
    return any(b"_lod" in scene.lower() for scene in scenes)


def geometry_size(db, model):
    """Bytes of a model's binary mesh (bin/Geometries/<uid>): the LOD's reduction."""
    data = db.read(model)
    m = re.search(rb'<Geometry\s+href="([^"]*)"', data or b"")
    if not m:
        return 0
    href = m.group(1).decode()
    # An inline geometry follows its href; the skeleton's uid may come first.
    record = data[m.end():] if href.startswith("#n:inline") else db.read(resolve(model, href))
    uid = re.search(rb"<uid>([^<]*)</uid>", record or b"")
    entry = db.names.get(("bin/geometries/" + uid.group(1).decode()).lower()) if uid else None
    return entry[0].getinfo(entry[1]).file_size if entry else 0


def is_lod(path):
    return bool(path) and "_lod" in posixpath.basename(path).lower()


def stem(path):
    """'.../Peasant_LOD.(Model).xdb' -> 'peasant': the asset a file is a version of."""
    name = posixpath.basename(path or "").lower()
    name = re.sub(r"\.xdb$", "", name)
    name = re.sub(r"\.\([a-z]+\)$", "", name)
    name = re.sub(r"_+lod_*(?:_+\d+)?$", "", name)
    return name.rstrip("_")


def choose(lod, targets):
    """One full version for a LOD file: the only candidate, or the same asset's."""
    if len(targets) == 1:
        return next(iter(targets))
    same = [t for t in targets if stem(t) == stem(lod)]
    return same[0] if len(same) == 1 else None


def build(db):
    """{"models": {lod: full}, "anims": {lod_set: full_set}, "notes": [...]} with lowercase keys."""
    creatures = {}
    table = db.read("GameMechanics/RefTables/Creatures.xdb")
    for ident, href in re.findall(rb'<ID>([^<]*)</ID>\s*<Obj\s+href="([^"]*)"', table or b""):
        creatures[ident.decode()] = resolve("GameMechanics/RefTables/Creatures.xdb", href.decode())
    notes = []
    monsters = []                                   # (map object, lod model, anim set, full model, combat set)
    candidates = collections.defaultdict(set)       # lod model -> {full model}
    hero_models, hero_anims = {}, {}
    for key, (archive, name) in sorted(db.names.items()):
        if not key.startswith("mapobjects/") or not key.endswith(".xdb"):
            continue
        data = db.read(name)
        tag = root_tag(data)
        if tag == "AdvMapMonsterShared":
            lod = resolve(name, field(data, "Model"))
            anim = resolve(name, field(data, "AnimSet"))
            creature = creatures.get(text_field(data, "Creature") or "")
            visual = resolve(creature, field(db.read(creature), "Visual")) if creature else None
            character = resolve(visual, field(db.read(visual), "AnimCharacter")) if visual else None
            cdata = db.read(character)
            full = resolve(character, field(cdata, "Model")) if cdata else None
            arena = resolve(character, field(cdata, "ArenaAnimSet")) if cdata else None
            monsters.append((name, lod, anim, full, arena))
            if is_lod(lod) and full and full.lower() != lod.lower() and db.exists(full) and db.exists(lod):
                candidates[lod.lower()].add(full)
        elif tag == "AdvMapHeroShared":
            adventure = resolve(name, field(data, "HeroCharacterAdventure"))
            combat = resolve(name, field(data, "HeroCharacterArena"))
            if not is_lod(adventure) or not combat or adventure.lower() == combat.lower():
                continue
            if adventure.lower() in KEEP:
                notes.append(f"{adventure}: kept by rule (see KEEP)")
                continue
            adata, cdata = db.read(adventure), db.read(combat)
            if adata is None or cdata is None:
                continue
            lod, full = resolve(adventure, field(adata, "Model")), resolve(combat, field(cdata, "Model"))
            lod_colours = [resolve(adventure, h) for h in items(adata, "ColourModels")]
            full_colours = [resolve(combat, h) for h in items(cdata, "ColourModels")]
            if len(lod_colours) != len(full_colours):
                notes.append(f"{adventure}: {len(lod_colours)} colour models, combat has {len(full_colours)}: kept")
                continue
            pairs = [(lod, full)] + list(zip(lod_colours, full_colours))
            pairs = [(a, b) for a, b in pairs if a and b and a.lower() != b.lower() and db.exists(a) and db.exists(b)]
            if not pairs:
                continue
            reduced, full_size = geometry_size(db, pairs[0][0]), geometry_size(db, pairs[0][1])
            if full_size and reduced >= 0.9 * full_size:
                notes.append(f"{adventure}: LOD mesh not reduced ({reduced}/{full_size} bytes): kept")
                continue
            for a, b in pairs:
                known = hero_models.setdefault(a.lower(), b)
                if known is not None and known.lower() != b.lower():
                    notes.append(f"{a}: heroes disagree: kept")
                    hero_models[a.lower()] = None
            lod_set = resolve(adventure, field(adata, "AdvMapAnimSet") or field(adata, "ArenaAnimSet"))
            combat_set = resolve(combat, field(cdata, "ArenaAnimSet"))
            # The combat set fits the full skeleton exactly; it serves the map
            # when it has the map's idle and movement animations. Only a set
            # named as a LOD set is resolved (the reader looks at "_LOD" names).
            if is_lod(lod_set) and combat_set and {"idle00", "move"} <= set(anim_kinds(db, combat_set)):
                known = hero_anims.setdefault(lod_set.lower(), combat_set)
                if known is not None and known.lower() != combat_set.lower():
                    hero_anims[lod_set.lower()] = None
    models = {}
    for lod, targets in sorted(candidates.items()):
        full = choose(lod, targets)
        if not full:
            notes.append(f"{lod}: creatures disagree ({sorted(targets)}): kept")
            continue
        reduced, full_size = geometry_size(db, lod), geometry_size(db, full)
        if full_size and reduced >= 0.9 * full_size:
            notes.append(f"{lod}: LOD mesh not reduced ({reduced}/{full_size} bytes): kept")
            continue
        models[lod] = full
    for lod, full in hero_models.items():
        if full and lod not in models:
            models[lod] = full
    # A monster's LOD-bound adventure set follows its model to the combat set
    # of that model, where every map object using the set shows that model.
    users = collections.defaultdict(list)
    for name, lod, anim, full, arena in monsters:
        if anim:
            shown = models.get((lod or "").lower(), lod)
            users[anim.lower()].append((name, (shown or "").lower(), (full or "").lower(), arena))
    anims = {}
    for anim, rows in sorted(users.items()):
        # Only sets named as LOD sets: the reader resolves "_LOD" names only,
        # and a set the designers paired with a LOD scene otherwise stays.
        if not is_lod(anim) or not lod_bound(db, anim):
            continue
        sets = {(r[3] or "").lower() for r in rows}
        if len(sets) != 1 or not next(iter(sets)):
            notes.append(f"{anim}: map objects of different creatures use it: kept")
            continue
        target = next(r[3] for r in rows)
        if target.lower() == anim or "idle00" not in anim_kinds(db, target):
            continue
        if not all(r[1] == r[2] for r in rows):
            notes.append(f"{anim}: a user keeps its LOD model: kept")
            continue
        anims[anim] = target
    for lod_set, combat_set in hero_anims.items():
        if combat_set and lod_set not in anims:
            anims[lod_set] = combat_set
    spell = lambda path: db.names.get(path.lower(), (None, path))[1]
    return {"models": {k: spell(v) for k, v in models.items()},
            "anims": {k: spell(v) for k, v in anims.items()}, "notes": notes}


def archives(edition, game):
    from port_ui import resource_archives
    return [Path(game) / pak for pak in resource_archives(edition) if (Path(game) / pak).is_file()]


def game_directory(edition):
    from editions import game_directory as directory
    return directory(edition, ROOT)


def c_table(tables):
    lines = ["/* Generated by tools/lod_models.py from each edition's own records; do not edit.",
             " * {LOD reference (lower case, no leading slash), full model or animation set},",
             " * sorted by the first string (bytewise) for bsearch. */"]
    for edition in EDITIONS:
        rows = tables[edition]
        merged = {**rows["models"], **rows["anims"]}
        if len(merged) != len(rows["models"]) + len(rows["anims"]):
            raise ValueError(edition + ": a path is both a model and an animation set")
        lines.append(f"static const lod_redirect lod_{edition}[] = {{")
        for lod in sorted(merged, key=lambda k: k.encode("utf-8")):
            if not lod.isascii() or not merged[lod].isascii():
                raise ValueError(edition + ": non-ASCII path " + lod)
            lines.append(f"    {{{json.dumps(lod)}, {json.dumps(merged[lod])}}},")
        lines.append("};")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--edition", choices=EDITIONS)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    editions = [args.edition] if args.edition else list(EDITIONS)
    tables = {}
    for edition in editions:
        db = Data(archives(edition, game_directory(edition)))
        tables[edition] = build(db)
        rows = tables[edition]
        print(f"{edition}: {len(rows['models'])} models, {len(rows['anims'])} animation sets, {len(rows['notes'])} notes")
        if args.report:
            for kind in ("models", "anims"):
                for lod, full in sorted(rows[kind].items()):
                    print(f"  {kind[:-1]:5s} {lod} -> {full}")
            for note in rows["notes"]:
                print("  note", note)
    if args.write:
        if set(tables) != set(EDITIONS):
            parser.error("--write needs every edition")
        OUTPUT.write_text(c_table(tables), encoding="utf-8", newline="\n")
        print("wrote", OUTPUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
