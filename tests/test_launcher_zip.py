"""Unpack real ZIP archives with the launcher's actual Zip/Unpacker in Java."""
import os
import subprocess
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from test_touch_controls import JAVA, ROOT

SOURCE = ROOT / "android/app/src/org/homm5/port"

CHECK = r'''
package org.homm5.port;
import java.io.*;
import java.nio.channels.FileChannel;
import java.nio.file.*;
public class ZipUnpackCheck {
  public static void main(String[] args) throws Exception {
    Unpacker.Plan plan = Unpacker.plan(new Zip(FileChannel.open(Paths.get(args[0]), StandardOpenOption.READ)));
    File target = new File(args[1]);
    Unpacker.Job job = new Unpacker.Job(plan, target, args[0], null);
    job.run();
    if (job.failure != null) throw job.failure;
    for (String path : plan.paths) {
      File f = new File(target, path);
      System.out.println(path + "\t" + f.length() + "\t" + f.lastModified());
    }
  }
}
'''


def zip_cp866(path, files, stamp):
    """Windows Explorer's way: OEM (here CP866) names without the UTF-8 flag."""
    original = zipfile.ZipInfo._encodeFilenameFlags

    def oem(self):
        try:
            return self.filename.encode("ascii"), self.flag_bits
        except UnicodeEncodeError:
            return self.filename.encode("cp866"), self.flag_bits & ~0x800

    zipfile.ZipInfo._encodeFilenameFlags = oem
    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in files.items():
                info = zipfile.ZipInfo(name, date_time=stamp)
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, data)
    finally:
        zipfile.ZipInfo._encodeFilenameFlags = original


class LauncherZipTest(unittest.TestCase):
    def run_java(self, archive, target):
        out = ROOT / "build/tests/launcher-zip"
        out.mkdir(parents=True, exist_ok=True)
        check = out / "ZipUnpackCheck.java"
        check.write_text(CHECK, encoding="utf-8")
        files = [SOURCE / (n + ".java") for n in ("Games", "Zip", "Deflate64", "Unpacker")]
        subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(out),
                        *map(str, files), str(check)], check=True)
        run = subprocess.run([str(JAVA / "java.exe"), "-ea", "-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8", "-Dsun.stdout.encoding=UTF-8", "-cp", str(out),
                              "org.homm5.port.ZipUnpackCheck", str(archive), str(target)],
                             check=True, capture_output=True)
        rows = {}
        for line in run.stdout.decode("utf-8").splitlines():
            path, size, modified = line.split("\t")
            rows[path] = (int(size), int(modified))
        return rows

    def test_cp866_names_and_archive_times(self):
        stamp = (2008, 10, 7, 13, 14, 16)
        files = {
            "Heroes V/bin/H5_Game.exe": b"MZ" + bytes(64),
            "Heroes V/data/data.pak": b"PK" + bytes(100),
            "Heroes V/data/a2p1-data.pak": b"PK" + bytes(50),
            "Heroes V/Maps/Моя карта.h5m": b"map",
            "Heroes V/UserMODs/Ёлка.h5u": b"mod",
            "Heroes V/Maps/─.txt": b"box",   # not a CP866 letter: read as CP437 (the same glyph)
        }
        with tempfile.TemporaryDirectory() as work:
            archive = Path(work) / "game.zip"
            zip_cp866(archive, files, stamp)
            with zipfile.ZipFile(archive) as z:   # the names really are flagless OEM bytes
                self.assertTrue(all(not i.flag_bits & 0x800 for i in z.infolist()))
            target = Path(work) / "HeroesV"
            rows = self.run_java(archive, target)
            self.assertIn("Maps/Моя карта.h5m", rows)
            self.assertIn("UserMODs/Ёлка.h5u", rows)
            self.assertIn("Maps/─.txt", rows)
            self.assertEqual(rows["Maps/Моя карта.h5m"][0], 3)
            self.assertTrue((target / "Maps" / "Моя карта.h5m").is_file())
            expected = time.mktime(stamp + (0, 0, -1)) * 1000
            for path, (_, modified) in rows.items():
                self.assertLessEqual(abs(modified - expected), 2000, path)


if __name__ == "__main__":
    unittest.main()
