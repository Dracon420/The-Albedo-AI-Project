# Third-party notices

The [PolyForm Noncommercial license](LICENSE.md) covers Albedo's own code. These bundled components are not
Albedo's and keep their own licenses:

| Component | Where | License | Source |
|---|---|---|---|
| Piper (piper-phonemize) | `piper/piper_phonemize.dll` | MIT | https://github.com/rhasspy/piper-phonemize |
| espeak-ng | `piper/espeak-ng.dll`, `piper/espeak-ng-data/` | GPL-3.0-or-later | https://github.com/espeak-ng/espeak-ng |
| ONNX Runtime | `piper/onnxruntime*.dll` | MIT | https://github.com/microsoft/onnxruntime |
| libtashkeel model | `piper/libtashkeel_model.ort` | MIT | https://github.com/mush42/libtashkeel |
| openWakeWord "hey jarvis" model | `wakewords/hey_jarvis_v0.1.onnx` | CC BY-NC-SA 4.0 | https://github.com/dscripka/openWakeWord |

espeak-ng is GPL software: its complete source code is available at the link above, and you may redistribute
it under the GPL's terms. The "hey core-tah-nuh" wake-word model in `wakewords/` was trained for this project.

Python and JavaScript dependencies are installed from PyPI and npm under their own licenses and are not
included in this repository.
