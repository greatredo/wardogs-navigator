# Third-party notices

Original Wardogs Navigator application code and documentation are licensed under Apache-2.0; see LICENSE and NOTICE. That license does not relicense third-party software, game imagery or trademarks.

WARDOGS, OZETI, BAKURANI and ZESTAFONA map imagery and game marks belong to their respective rights holders. The terrain displays, road candidates and feature caches are derived from publicly served tiles in the wardogs-calculator assets-v1 release. OZETI retains its published coordinate transform. The other maps use the public configuration's play-area crop and a documented image scale. This is an unofficial local companion and is not endorsed by the game developer. The upstream project's license does not establish additional rights to the game's underlying artwork or approval to redistribute that artwork.

Public map data source: https://github.com/apollyon-sys/wardogs-calculator and https://assets.wardogs-artillery.com/releases/assets-v1/maps/tiles/{map-id} (grayscale), /maps/tiles-color/{map-id} (color used during preparation), where map-id is ozeti, bakurani or zestafona. The map catalogue is https://github.com/apollyon-sys/wardogs-calculator/blob/main/maps/index.json . The public project is MIT licensed, copyright (c) 2026 Apollyon; its full license is retained in `assets/wardogs-calculator-LICENSE.txt` and in the `licenses` directory of binary distributions. Changes include cropping, scaling, coordinate alignment, feature extraction, road tracing and connection adjustments. No upstream marker or team-unit overlay is imported into the application. The bundled sample_minimap.png and reference-crop.png files are public-image crops for diagnostics, not player captures.

Binary distributions dynamically package the following components, with their license texts included in the `licenses` directory. Source distributions install them through `requirements.txt`:

- Python 3.13: PSF License.
- PySide6 / Qt for Python / Shiboken 6.11.2: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only (the application uses LGPL components). Qt libraries remain separate dynamic libraries in `_internal`; users may replace compatible versions as permitted by their licenses. Corresponding upstream source: https://code.qt.io/cgit/pyside/pyside-setup.git/ and https://code.qt.io/cgit/qt/ .
- OpenCV Python headless 5.0.0.93: Apache 2.0; wheel third-party notices are included.
- NumPy 2.5.3: BSD-3-Clause; bundled library notices are included.
- MSS 10.2.0: MIT License.
- PyInstaller 6.22.3: GPL with bootloader distribution exception.

The source distribution also uses pytest 9.1.1 (MIT) for development; pytest is not part of the application runtime. Complete application source and build scripts are provided in the source distribution. Windows speech and fonts are supplied by the operating system, not redistributed in this package. The web calculator at https://bili.bi/WARDOGS/zh/ links to the public upstream map-data project above; its client code is not bundled.

The application includes a default PCM voice pack generated offline with Kokoro-82M v1.0 (Apache-2.0 model) using the stock zf_xiaoxiao and af_heart voices and original application prompts. No model weights or inference dependencies are distributed. See [voice pack sources](wardogs_audio/assets/default/SOURCES.md), also present under `_internal/wardogs_audio/assets/default` in binary builds. File playback uses Qt Multimedia.
