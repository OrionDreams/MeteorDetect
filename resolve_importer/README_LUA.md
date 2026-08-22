# DaVinci Resolve Lua importer

`Import Meteors.lua` runs **inside DaVinci Resolve** and imports `meteors.json` as **Pink clip markers** on matching video clips in the current timeline. It is self-contained and does not require Python, OpenCV, FFmpeg, or the detector's virtual environment.

## Install

Copy `Import Meteors.lua` into Resolve's `Fusion/Scripts/Utility` user scripts directory. For the current Linux development target, the usual per-user location is:

```text
~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/
```

Create the directory if it does not exist. Then restart Resolve so it rescans its scripts.

Common per-user locations on other platforms are typically under Resolve's application-support data directory with the same `Fusion/Scripts/Utility` suffix. If the menu item does not appear, use Resolve's own Fusion/Developer scripting documentation installed with your Resolve version to confirm the scripts path for that OS.

## Run

1. Open the Resolve project and the timeline containing the source clips.
2. Choose **Workspace → Scripts → Import Meteors**.
3. Select the `meteors.json` produced by Resolve Meteor Detector.
4. The script matches JSON source filenames to clips on the current timeline and adds **Pink** clip markers at the detected meteor frames.

Running the importer again is safe: marker custom data is used to avoid intentionally adding the same detection twice to the same clip.

### File-picker fallback

The importer first tries Resolve/Fusion's interactive file picker. If a particular Resolve build does not expose one in the current page/context, it falls back to:

1. the `METEOR_JSON` environment variable, then
2. `~/meteors.json`.

Normally no environment variables are needed when launching it from **Workspace → Scripts**.

## Notes

- The current JSON matcher uses source **filename**. Duplicate filenames inside one JSON results file are rejected as ambiguous.
- A meteor that lies outside the visible source range of a trimmed timeline clip is skipped.
- The importer targets source-relative clip-marker frame IDs, matching the current Python importer behavior.
- The external Python importer remains included for debugging and compatibility testing.
