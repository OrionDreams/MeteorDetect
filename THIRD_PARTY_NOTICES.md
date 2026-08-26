# Third-Party Notices

MeteorDetect includes, bundles, or is built using third-party open-source software.

This file summarizes the principal third-party components distributed with official
MeteorDetect builds. Each third-party component remains subject to its own license.
Nothing in this file changes the license of MeteorDetect itself or of any third-party
software.

Audit date: 2026-08-26

---

## FFmpeg and FFprobe

MeteorDetect bundles `ffmpeg` and `ffprobe` as standalone executables for probing and
decoding user-supplied video files.

FFmpeg project:

- https://ffmpeg.org/
- https://github.com/FFmpeg/FFmpeg

MeteorDetect intentionally uses redistributable GPL builds with `--enable-gpl` and
`--enable-version3`.

Because these are full static builds, they may contain FFmpeg plus a large number of
statically linked third-party codec, container, subtitle, image, filtering, and utility
libraries. Those incorporated libraries remain subject to their respective licenses.

### Windows x64

Official MeteorDetect Windows x64 releases use a pinned BtbN FFmpeg-Builds GPL static
build from the FFmpeg 9.0 release branch:

- FFmpeg base version: 9.0.1
- BtbN revision: `n9.0.1-6-g9d4ca21220`
- BtbN release: `autobuild-2026-08-20-13-45`
- Variant: `gpl`
- Linking: static

BtbN describes the `gpl` variant as including all dependencies, including dependencies
that require full GPL licensing.

Project:

- https://github.com/BtbN/FFmpeg-Builds

### Linux x64

Official MeteorDetect Linux x64 releases use the corresponding pinned BtbN GPL static
build:

- FFmpeg base version: 9.0.1
- BtbN revision: `n9.0.1-6-g9d4ca21220`
- BtbN release: `autobuild-2026-08-20-13-45`
- Variant: `gpl`
- Linking: static

Project:

- https://github.com/BtbN/FFmpeg-Builds

### macOS Apple Silicon (ARM64)

Official MeteorDetect Apple Silicon releases use the pinned build published by:

- https://github.com/OrionDreams/ffmpeg-apple-silicon
- Release: `v0.2.1`
- FFmpeg version: 9.0.1
- Architecture: arm64
- Variant: full
- Linking: static
- Required FFmpeg license flags: `--enable-gpl --enable-version3`

That release archive contains its exact FFmpeg configuration and complete decoder and
demuxer lists. Those files are the authoritative description of the exact codec and
library configuration shipped on Apple Silicon.

### macOS Intel (x86_64)

Official MeteorDetect Intel macOS releases use the FFmpeg 9.0.1 static binaries
published by Evermeet:

- FFmpeg version: 9.0.1
- Architecture: x86_64
- Linking: static
- Configuration includes `--enable-gpl` and `--enable-version3`

Provider:

- https://evermeet.cx/ffmpeg/

The Evermeet FFmpeg 9.0.1 build includes numerous external libraries, including AOM,
dav1d, libvpx, OpenJPEG, WebP, x264, x265, Xvid, Theora, Opus, Vorbis, zimg, and others.
The exact external-library list published for that build controls over this summary.

### FFmpeg licensing

FFmpeg itself is available under the GNU Lesser General Public License (LGPL), with
parts available under the GNU General Public License (GPL). When GPL components are
enabled, as in the MeteorDetect builds described above, the resulting FFmpeg binaries
are distributed under the applicable GPL terms.

The exact license obligations for each static FFmpeg binary also include the licenses
of the external libraries compiled into that binary.

Official FFmpeg licensing information:

- https://ffmpeg.org/legal.html
- https://ffmpeg.org/doxygen/trunk/md_LICENSE.html

MeteorDetect release packages SHOULD preserve the exact FFmpeg build information used
for that platform. Where available, the package should include:

- `runtime/ffmpeg/BUILD_INFO.txt`
- FFmpeg's GPL license text
- provider/build metadata
- applicable third-party license notices for statically linked libraries

Corresponding source code and build information must be made available as required by
the applicable GPL and third-party licenses.

---

## Avalonia

MeteorDetect uses the Avalonia UI framework.

Direct package references currently include:

- Avalonia 12.1.1
- Avalonia.Desktop 12.1.1
- Avalonia.Themes.Fluent 12.1.1
- Avalonia.Fonts.Inter 12.1.1

Project:

- https://github.com/AvaloniaUI/Avalonia

License:

- MIT License

Copyright:

- AvaloniaUI OÜ and contributors

The MIT License permits use, modification, distribution, sublicensing, and commercial
use provided the copyright and license notice are preserved.

---

## Inter Font

MeteorDetect receives the Inter font through `Avalonia.Fonts.Inter`.

Project:

- https://github.com/rsms/inter

License:

- SIL Open Font License 1.1

Copyright:

- Rasmus Andersson and contributors

The Inter font itself remains subject to the SIL Open Font License even when bundled
with MeteorDetect.

Official OFL text:

- https://openfontlicense.org/open-font-license-official-text/

---

## .NET Community Toolkit

MeteorDetect uses:

- CommunityToolkit.Mvvm 8.4.0

Project:

- https://github.com/CommunityToolkit/dotnet

License:

- MIT License

Copyright:

- .NET Foundation and contributors

---

## Microsoft .NET Runtime

MeteorDetect is published as a self-contained .NET 10 application. Official packages
therefore contain portions of the Microsoft .NET Runtime and its own third-party
dependencies.

Project:

- https://github.com/dotnet/runtime

Primary license:

- MIT License

The .NET Runtime repository also contains a version-specific
`THIRD-PARTY-NOTICES.TXT` covering third-party software included in the runtime.

For release compliance, MeteorDetect SHOULD ship the exact .NET runtime license and
third-party-notice files corresponding to the runtime version used to produce that
release.

Canonical upstream files:

- https://github.com/dotnet/runtime/blob/main/LICENSE.TXT
- https://github.com/dotnet/runtime/blob/main/THIRD-PARTY-NOTICES.TXT

---

## NumPy

MeteorDetect's detector currently declares:

- `numpy>=1.26`

Project:

- https://github.com/numpy/numpy

License:

- BSD 3-Clause License

Official NumPy binary wheels may contain additional native libraries, including
BLAS/LAPACK implementations, with their own licenses and notices.

The exact NumPy version included in each packaged MeteorDetect detector is determined
at build time unless the release build pins it explicitly.

MeteorDetect release packaging SHOULD preserve the license files supplied with the
exact NumPy wheel included in the detector executable.

---

## OpenCV / opencv-python-headless

MeteorDetect's detector currently declares:

- `opencv-python-headless>=4.9`

Projects:

- https://github.com/opencv/opencv-python
- https://github.com/opencv/opencv

The `opencv-python` packaging project is distributed under the MIT License.

The binary wheels also contain OpenCV and may contain additional native third-party
software. The wheel distribution includes separate license information, commonly
including:

- `LICENSE.txt`
- `LICENSE-3RD-PARTY.txt`

MeteorDetect release packaging SHOULD preserve the license files from the exact
`opencv-python-headless` wheel used to build the detector executable.

---

## CPython

MeteorDetect's standalone detector executable is built from CPython using PyInstaller.

Project:

- https://github.com/python/cpython
- https://www.python.org/

License:

- Python Software Foundation License Version 2 and the additional historical licenses
  included with CPython

Official license information:

- https://docs.python.org/3/license.html

MeteorDetect release packaging SHOULD preserve the CPython license corresponding to
the exact Python version used to build the detector.

---

## PyInstaller

MeteorDetect uses PyInstaller to create the standalone `meteor-detector` executable.

Project:

- https://github.com/pyinstaller/pyinstaller

License:

- GNU General Public License Version 2 or later, with a special exception covering the
  distribution of bundled applications

PyInstaller's bootloader exception permits applications generated with PyInstaller to
be distributed under the application's own license, subject to the licenses of the
software bundled into that application.

The PyInstaller license text should be preserved in release compliance materials.

Canonical license:

- https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt

---

## AvaloniaUI.DiagnosticsSupport

The project references:

- AvaloniaUI.DiagnosticsSupport 2.2.3

MeteorDetect's project configuration excludes this package from ordinary non-Debug
builds using conditional `IncludeAssets` and `PrivateAssets` settings.

It is therefore considered a development/debug dependency and is not expected to be
part of normal MeteorDetect release packages.

If it becomes part of a distributed release in the future, its license and transitive
dependencies should be re-audited.

---

## DaVinci Resolve

DaVinci Resolve is proprietary software from Blackmagic Design and is not distributed
with MeteorDetect.

MeteorDetect generates JSON data and provides an importer script that interoperates
with DaVinci Resolve. References to DaVinci Resolve or Blackmagic Design are
descriptive and do not imply sponsorship, endorsement, or affiliation.

---

# Recommended release license layout

Official MeteorDetect packages should preferably contain a layout similar to:

```text
MeteorDetect/
├── LICENSE
├── THIRD_PARTY_NOTICES.md
├── THIRD_PARTY_LICENSES/
│   ├── dotnet-LICENSE.txt
│   ├── dotnet-THIRD-PARTY-NOTICES.txt
│   ├── python-LICENSE.txt
│   ├── pyinstaller-COPYING.txt
│   ├── numpy-LICENSE.txt
│   ├── opencv-LICENSE.txt
│   ├── opencv-LICENSE-3RD-PARTY.txt
│   └── ffmpeg/
│       ├── LICENSE.txt
│       └── provider-and-library-notices...
└── runtime/
    └── ffmpeg/
        ├── ffmpeg
        ├── ffprobe
        └── BUILD_INFO.txt
```

File names may vary between platforms and upstream packages.

---

# Release compliance checklist

Before publishing an official MeteorDetect release:

1. Include MeteorDetect's own `LICENSE`.

2. Include this `THIRD_PARTY_NOTICES.md`.

3. Preserve the exact FFmpeg build information for each platform.

4. Keep FFmpeg versions and provider release identifiers pinned in the release
   workflow.

5. Preserve or redistribute the license texts and notices required by the exact static
   FFmpeg build and all statically incorporated third-party libraries.

6. Include the .NET Runtime `LICENSE.TXT` and `THIRD-PARTY-NOTICES.TXT` corresponding
   to the exact self-contained runtime shipped in the release.

7. Preserve Python, NumPy, OpenCV, and PyInstaller license files corresponding to the
   exact detector build.

8. Prefer pinning the exact Python dependency versions used for release builds so the
   released binary can be reproduced and audited.

9. Audit the final generated release artifact, not only source manifests. Self-contained
   .NET publishing, Python wheels, PyInstaller, AppImage tooling, and static FFmpeg
   builds may incorporate software that is not obvious from the project's direct
   dependency files.

---

Third-party product names and trademarks belong to their respective owners.

This file is intended as a practical open-source compliance notice and is not legal
advice.
