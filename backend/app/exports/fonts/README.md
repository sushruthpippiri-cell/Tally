# Bundled fonts

WeasyPrint renders a PDF with whatever fonts the machine happens to have, and Tally names are
often in Indian scripts. Relying on system font packages would mean this Mac, CI and the Docker
image each embedding a different font - or none, and a page of empty boxes. So the fonts live
here, are loaded by `@font-face` from `app/exports/pdf.py`, and ship inside the wheel
(`backend/pyproject.toml`: `packages = ["app"]`). Neither the Dockerfile nor CI installs a font
package (D-053 #7b, as amended by the owner).

`DejaVu Sans` carries Latin, the rupee sign and the digits; the nine Noto Sans faces carry the
Indic scripts of the Indian rupee's own language panel. The CSS stack lists DejaVu first, then
each Noto face, so a name in any of these scripts renders rather than falling back.

## Licences
- The Noto faces are under the **SIL Open Font License 1.1** — [`OFL.txt`](OFL.txt), which
  carries the copyright notice of each of the nine upstream repositories.
- DejaVu is under the **Bitstream Vera and Arev** licences — [`LICENSE-DejaVu.txt`](LICENSE-DejaVu.txt).

Both permit redistribution with the licence text, which is why these two files sit beside the
fonts. Neither font is renamed, so no Reserved Font Name is touched.

## Provenance (pinned, as `docs/srs/README.md` pins its artifacts)
- `NotoSansDevanagari-Regular.ttf` — https://github.com/notofonts/notofonts.github.io/raw/main/fonts/NotoSansDevanagari/hinted/ttf/NotoSansDevanagari-Regular.ttf
- `NotoSansBengali-Regular.ttf` — https://github.com/notofonts/notofonts.github.io/raw/main/fonts/NotoSansBengali/hinted/ttf/NotoSansBengali-Regular.ttf
- `NotoSansGurmukhi-Regular.ttf` — https://github.com/notofonts/notofonts.github.io/raw/main/fonts/NotoSansGurmukhi/hinted/ttf/NotoSansGurmukhi-Regular.ttf
- `NotoSansGujarati-Regular.ttf` — https://github.com/notofonts/notofonts.github.io/raw/main/fonts/NotoSansGujarati/hinted/ttf/NotoSansGujarati-Regular.ttf
- `NotoSansOriya-Regular.ttf` — https://github.com/notofonts/notofonts.github.io/raw/main/fonts/NotoSansOriya/hinted/ttf/NotoSansOriya-Regular.ttf
- `NotoSansTamil-Regular.ttf` — https://github.com/notofonts/notofonts.github.io/raw/main/fonts/NotoSansTamil/hinted/ttf/NotoSansTamil-Regular.ttf
- `NotoSansTelugu-Regular.ttf` — https://github.com/notofonts/notofonts.github.io/raw/main/fonts/NotoSansTelugu/hinted/ttf/NotoSansTelugu-Regular.ttf
- `NotoSansKannada-Regular.ttf` — https://github.com/notofonts/notofonts.github.io/raw/main/fonts/NotoSansKannada/hinted/ttf/NotoSansKannada-Regular.ttf
- `NotoSansMalayalam-Regular.ttf` — https://github.com/notofonts/notofonts.github.io/raw/main/fonts/NotoSansMalayalam/hinted/ttf/NotoSansMalayalam-Regular.ttf
- `DejaVuSans.ttf` — https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.zip -> ttf/DejaVuSans.ttf
- `DejaVuSans-Bold.ttf` — https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.zip -> ttf/DejaVuSans-Bold.ttf

| File | Size | SHA-256 |
|---|---|---|
| `NotoSansDevanagari-Regular.ttf` | 237 KB | `4e3c66638958c3e2ab5d37f47a8deb89fffeb7be9985c665a519bbc7ba762313` |
| `NotoSansBengali-Regular.ttf` | 139 KB | `b55c62ee531e3214da6c0701daecea89a52ba42db7d8206b92e6b51f397a3193` |
| `NotoSansGurmukhi-Regular.ttf` | 53 KB | `658d0207da305a1411c539a8b0bbeda64d4146e54fb4827facddb890b6b90d74` |
| `NotoSansGujarati-Regular.ttf` | 196 KB | `9b5a7aaeeb649a2e75a49d8b006a1f87db1b61c0df3b001609f4e0725d88dbf6` |
| `NotoSansOriya-Regular.ttf` | 128 KB | `a16645d056017927406546aa78e4ce15e782fd8783467267b75450453d007415` |
| `NotoSansTamil-Regular.ttf` | 72 KB | `3c0a186feb3c63c7f6d63e1511dcdc144e745ae09b98e217c83f3e317974f6f9` |
| `NotoSansTelugu-Regular.ttf` | 229 KB | `b274780b69d1d23fe84b55e809a152cb2ac5306d33864b1f87622f6971871aae` |
| `NotoSansKannada-Regular.ttf` | 178 KB | `9ad74dc64838c6855b96f671fc08e425a58921b9d0c71712ea79c328a27e6e38` |
| `NotoSansMalayalam-Regular.ttf` | 110 KB | `c08de7fa8d032a5d6a4d120fb82c78cec60b362a4e73fa26360d89759ff2a7f9` |
| `DejaVuSans.ttf` | 739 KB | `7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954` |
| `DejaVuSans-Bold.ttf` | 689 KB | `e6476c1b80502924294eed40894c5b18e06c181444ca953e5334262df9c27724` |

To replace one, download it again, update its row here, and read the diff: a font file is
binary, so the hash is the only review there is. `.gitattributes` marks `*.ttf` binary so a
Windows checkout does not mangle them.
