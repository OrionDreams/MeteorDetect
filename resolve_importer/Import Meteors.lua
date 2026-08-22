-- Resolve Meteor Detector - in-Resolve Lua importer
-- Targeted at DaVinci Resolve Studio 21.x.
--
-- Install this file in Resolve's Fusion/Scripts/Utility folder, restart Resolve,
-- then run it from Workspace > Scripts > Import Meteors.
--
-- The script is intentionally self-contained: no external Lua modules are needed.

local MARKER_COLOR = "Pink"
local MARKER_NAME = "Meteor"
local CUSTOM_PREFIX = "resolve-meteor-detector:"

-- ---------------------------------------------------------------------------
-- Minimal JSON decoder (objects, arrays, strings, numbers, booleans and null)
-- ---------------------------------------------------------------------------

local JSON_NULL = {}

local function json_error(text, pos, msg)
    error(string.format("JSON parse error at byte %d: %s", pos, msg))
end

local function skip_ws(text, pos)
    while true do
        local c = text:sub(pos, pos)
        if c == " " or c == "\t" or c == "\r" or c == "\n" then
            pos = pos + 1
        else
            return pos
        end
    end
end

local parse_value

local function parse_string(text, pos)
    if text:sub(pos, pos) ~= '"' then json_error(text, pos, "expected string") end
    pos = pos + 1
    local out = {}
    while pos <= #text do
        local c = text:sub(pos, pos)
        if c == '"' then
            return table.concat(out), pos + 1
        elseif c == "\\" then
            local esc = text:sub(pos + 1, pos + 1)
            if esc == '"' or esc == "\\" or esc == "/" then
                out[#out + 1] = esc
                pos = pos + 2
            elseif esc == "b" then out[#out + 1] = "\b"; pos = pos + 2
            elseif esc == "f" then out[#out + 1] = "\f"; pos = pos + 2
            elseif esc == "n" then out[#out + 1] = "\n"; pos = pos + 2
            elseif esc == "r" then out[#out + 1] = "\r"; pos = pos + 2
            elseif esc == "t" then out[#out + 1] = "\t"; pos = pos + 2
            elseif esc == "u" then
                local hex = text:sub(pos + 2, pos + 5)
                if #hex ~= 4 or not hex:match("^[0-9a-fA-F]+$") then
                    json_error(text, pos, "invalid unicode escape")
                end
                local cp = tonumber(hex, 16)
                -- Handle UTF-16 surrogate pairs.
                if cp >= 0xD800 and cp <= 0xDBFF and text:sub(pos + 6, pos + 7) == "\\u" then
                    local hex2 = text:sub(pos + 8, pos + 11)
                    local low = tonumber(hex2, 16)
                    if low and low >= 0xDC00 and low <= 0xDFFF then
                        cp = 0x10000 + (cp - 0xD800) * 0x400 + (low - 0xDC00)
                        pos = pos + 6
                    end
                end
                if cp <= 0x7F then
                    out[#out + 1] = string.char(cp)
                elseif cp <= 0x7FF then
                    out[#out + 1] = string.char(
                        0xC0 + math.floor(cp / 0x40),
                        0x80 + (cp % 0x40)
                    )
                elseif cp <= 0xFFFF then
                    out[#out + 1] = string.char(
                        0xE0 + math.floor(cp / 0x1000),
                        0x80 + (math.floor(cp / 0x40) % 0x40),
                        0x80 + (cp % 0x40)
                    )
                else
                    out[#out + 1] = string.char(
                        0xF0 + math.floor(cp / 0x40000),
                        0x80 + (math.floor(cp / 0x1000) % 0x40),
                        0x80 + (math.floor(cp / 0x40) % 0x40),
                        0x80 + (cp % 0x40)
                    )
                end
                pos = pos + 6
            else
                json_error(text, pos, "invalid escape sequence")
            end
        else
            if c:byte() < 0x20 then json_error(text, pos, "control character in string") end
            out[#out + 1] = c
            pos = pos + 1
        end
    end
    json_error(text, pos, "unterminated string")
end

local function parse_number(text, pos)
    local start = pos
    local c = text:sub(pos, pos)
    if c == "-" then pos = pos + 1 end
    if text:sub(pos, pos) == "0" then
        pos = pos + 1
    else
        if not text:sub(pos, pos):match("%d") then json_error(text, pos, "invalid number") end
        while text:sub(pos, pos):match("%d") do pos = pos + 1 end
    end
    if text:sub(pos, pos) == "." then
        pos = pos + 1
        if not text:sub(pos, pos):match("%d") then json_error(text, pos, "invalid fraction") end
        while text:sub(pos, pos):match("%d") do pos = pos + 1 end
    end
    c = text:sub(pos, pos)
    if c == "e" or c == "E" then
        pos = pos + 1
        c = text:sub(pos, pos)
        if c == "+" or c == "-" then pos = pos + 1 end
        if not text:sub(pos, pos):match("%d") then json_error(text, pos, "invalid exponent") end
        while text:sub(pos, pos):match("%d") do pos = pos + 1 end
    end
    local n = tonumber(text:sub(start, pos - 1))
    if n == nil then json_error(text, start, "invalid number") end
    return n, pos
end

local function parse_array(text, pos)
    local arr = {}
    pos = skip_ws(text, pos + 1)
    if text:sub(pos, pos) == "]" then return arr, pos + 1 end
    local i = 1
    while true do
        local value
        value, pos = parse_value(text, pos)
        arr[i] = value
        i = i + 1
        pos = skip_ws(text, pos)
        local c = text:sub(pos, pos)
        if c == "]" then return arr, pos + 1 end
        if c ~= "," then json_error(text, pos, "expected ',' or ']'") end
        pos = skip_ws(text, pos + 1)
    end
end

local function parse_object(text, pos)
    local obj = {}
    pos = skip_ws(text, pos + 1)
    if text:sub(pos, pos) == "}" then return obj, pos + 1 end
    while true do
        if text:sub(pos, pos) ~= '"' then json_error(text, pos, "expected object key") end
        local key
        key, pos = parse_string(text, pos)
        pos = skip_ws(text, pos)
        if text:sub(pos, pos) ~= ":" then json_error(text, pos, "expected ':'") end
        pos = skip_ws(text, pos + 1)
        local value
        value, pos = parse_value(text, pos)
        obj[key] = value
        pos = skip_ws(text, pos)
        local c = text:sub(pos, pos)
        if c == "}" then return obj, pos + 1 end
        if c ~= "," then json_error(text, pos, "expected ',' or '}'") end
        pos = skip_ws(text, pos + 1)
    end
end

parse_value = function(text, pos)
    pos = skip_ws(text, pos)
    local c = text:sub(pos, pos)
    if c == '"' then return parse_string(text, pos) end
    if c == "{" then return parse_object(text, pos) end
    if c == "[" then return parse_array(text, pos) end
    if c == "-" or c:match("%d") then return parse_number(text, pos) end
    if text:sub(pos, pos + 3) == "true" then return true, pos + 4 end
    if text:sub(pos, pos + 4) == "false" then return false, pos + 5 end
    if text:sub(pos, pos + 3) == "null" then return JSON_NULL, pos + 4 end
    json_error(text, pos, "unexpected token")
end

local function json_decode(text)
    local value, pos = parse_value(text, 1)
    pos = skip_ws(text, pos)
    if pos <= #text then json_error(text, pos, "trailing data") end
    return value
end

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------

local function basename(path)
    path = tostring(path or "")
    path = path:gsub("\\", "/")
    return path:match("([^/]+)$") or path
end

local function norm_name(path)
    return string.lower(basename(path))
end

local function file_exists(path)
    local f = io.open(path, "rb")
    if f then f:close(); return true end
    return false
end

local function read_all(path)
    local f, err = io.open(path, "rb")
    if not f then return nil, err end
    local data = f:read("*a")
    f:close()
    return data
end

local function home_dir()
    return os.getenv("HOME") or os.getenv("USERPROFILE") or ""
end

local function get_fusion()
    if fusion ~= nil then return fusion end
    if fu ~= nil then return fu end
    if type(Fusion) == "function" then
        local ok, result = pcall(Fusion)
        if ok then return result end
    end
    return nil
end

local function get_resolve()
    if type(Resolve) == "function" then
        local ok, result = pcall(Resolve)
        if ok and result then return result end
    end
    local f = get_fusion()
    if f and f.GetResolve then
        local ok, result = pcall(function() return f:GetResolve() end)
        if ok and result then return result end
    end
    if app and app.GetResolve then
        local ok, result = pcall(function() return app:GetResolve() end)
        if ok and result then return result end
    end
    return nil
end

local function request_json_path()
    local f = get_fusion()

    -- Fusion/Resolve builds commonly expose RequestFile on the Fusion application.
    if f and f.RequestFile then
        local ok, result = pcall(function()
            return f:RequestFile("", "JSON files (*.json)|*.json", { FReqB_SeqGather = false })
        end)
        if ok and result and tostring(result) ~= "" then return tostring(result) end
    end

    -- AskUser's FileBrowse control is part of the embedded Fusion scripting API.
    -- It needs a current Fusion composition, so this is a fallback rather than the
    -- primary picker when running from the Edit page.
    if f and f.GetCurrentComp then
        local ok_comp, comp = pcall(function() return f:GetCurrentComp() end)
        if ok_comp and comp and comp.AskUser then
            local ok, result = pcall(function()
                return comp:AskUser("Import Meteor Markers", {
                    { "JSONFile", "FileBrowse", Name = "Meteor results JSON" }
                })
            end)
            if ok and result and result.JSONFile and tostring(result.JSONFile) ~= "" then
                return tostring(result.JSONFile)
            end
        end
    end

    -- Non-interactive fallback for unusual Resolve/Fusion builds.
    local env = os.getenv("METEOR_JSON")
    if env and env ~= "" and file_exists(env) then return env end
    local home = home_dir()
    if home ~= "" then
        local fallback = home .. "/meteors.json"
        if file_exists(fallback) then return fallback end
    end
    return nil
end

local function clip_filename(item)
    local ok, mpi = pcall(function() return item:GetMediaPoolItem() end)
    if not ok or not mpi then return "" end

    local props = {}
    pcall(function() props = mpi:GetClipProperty() or {} end)
    local keys = { "File Path", "FilePath", "Filename", "File Name" }
    for _, key in ipairs(keys) do
        if props[key] and tostring(props[key]) ~= "" then
            return basename(props[key])
        end
    end

    local name = nil
    pcall(function() name = mpi:GetName() end)
    if name and tostring(name) ~= "" then return tostring(name) end
    pcall(function() name = item:GetName() end)
    return tostring(name or "")
end

local function source_range(item)
    local left, duration
    local ok1 = pcall(function() left = tonumber(item:GetLeftOffset()) end)
    local ok2 = pcall(function() duration = tonumber(item:GetDuration()) end)
    if not ok1 or not ok2 or not left or not duration or duration <= 0 then return nil, nil end
    left = math.floor(left + 0.5)
    duration = math.floor(duration + 0.5)
    return left, left + duration - 1
end

local function existing_custom_data(item)
    local found = {}
    local markers = {}
    pcall(function() markers = item:GetMarkers() or {} end)
    for _, info in pairs(markers) do
        if type(info) == "table" then
            local custom = info.customData or info.customdata
            if custom and tostring(custom) ~= "" then found[tostring(custom)] = true end
        end
    end
    return found
end

local function join_sorted_keys(set)
    local list = {}
    for key, _ in pairs(set) do list[#list + 1] = key end
    table.sort(list)
    return table.concat(list, ", ")
end

local function show_message(title, body)
    print(title)
    print(body)
    local f = get_fusion()
    if f and f.GetCurrentComp then
        local ok_comp, comp = pcall(function() return f:GetCurrentComp() end)
        if ok_comp and comp and comp.AskUser then
            pcall(function()
                comp:AskUser(title, {
                    { "Message", "Text", Default = body, ReadOnly = true, Lines = 12, Wrap = true }
                })
            end)
        end
    end
end

-- ---------------------------------------------------------------------------
-- Import
-- ---------------------------------------------------------------------------

local function main()
    local json_path = request_json_path()
    if not json_path then
        show_message(
            "Meteor Import",
            "No JSON file was selected. If your Resolve build does not show a file picker, set METEOR_JSON or place meteors.json in your home directory."
        )
        return
    end

    local raw, err = read_all(json_path)
    if not raw then error("Could not read JSON file: " .. tostring(err)) end
    local data = json_decode(raw)
    if type(data) ~= "table" or data.format ~= "resolve-meteor-detector" then
        error("Not a resolve-meteor-detector JSON file")
    end

    local detections = {}
    local duplicates = {}
    for _, fdata in ipairs(data.files or {}) do
        local name = norm_name(fdata.filename or "")
        if name ~= "" then
            if detections[name] then duplicates[name] = true end
            detections[name] = fdata
        end
    end
    if next(duplicates) ~= nil then
        error("Duplicate source filenames in JSON are ambiguous: " .. join_sorted_keys(duplicates))
    end

    local resolve = get_resolve()
    if not resolve then error("Could not access the DaVinci Resolve scripting object") end
    local pm = resolve:GetProjectManager()
    local project = pm and pm:GetCurrentProject() or nil
    local timeline = project and project:GetCurrentTimeline() or nil
    if not timeline then error("No current timeline is open") end

    local added, skipped_trim, already, matched_items = 0, 0, 0, 0
    local unmatched = {}
    for name, _ in pairs(detections) do unmatched[name] = true end

    local track_count = tonumber(timeline:GetTrackCount("video") or 0) or 0
    for track = 1, track_count do
        local items = timeline:GetItemListInTrack("video", track) or {}
        for _, item in pairs(items) do
            local filename = norm_name(clip_filename(item))
            local fdata = detections[filename]
            if filename ~= "" and fdata then
                matched_items = matched_items + 1
                unmatched[filename] = nil
                local existing = existing_custom_data(item)
                local src_first, src_last = source_range(item)

                for _, event in ipairs(fdata.events or {}) do
                    local source_frame = tonumber(event.peak_frame)
                    if source_frame then
                        source_frame = math.floor(source_frame + 0.5)
                        if src_first and (source_frame < src_first or source_frame > src_last) then
                            skipped_trim = skipped_trim + 1
                        else
                            local event_id = tostring(event.id or (basename(filename):gsub("%.[^.]+$", "") .. "-" .. source_frame))
                            local custom = CUSTOM_PREFIX .. event_id
                            if existing[custom] then
                                already = already + 1
                            else
                                local note = string.format(
                                    "Detected meteor\nSource: %s\nFrames: %s-%s\nPeak frame: %d\nConfidence: %s",
                                    tostring(fdata.filename or filename),
                                    tostring(event.start_frame or "?"),
                                    tostring(event.end_frame or "?"),
                                    source_frame,
                                    tostring(event.confidence or "n/a")
                                )
                                local ok = item:AddMarker(source_frame, MARKER_COLOR, MARKER_NAME, note, 1, custom)
                                if ok then
                                    added = added + 1
                                    existing[custom] = true
                                else
                                    print(string.format(
                                        "WARNING: Resolve rejected marker %s on %s at source frame %d",
                                        event_id, filename, source_frame
                                    ))
                                end
                            end
                        end
                    end
                end
            end
        end
    end

    local unmatched_count = 0
    for _ in pairs(unmatched) do unmatched_count = unmatched_count + 1 end
    local timeline_name = "(unnamed)"
    pcall(function() timeline_name = tostring(timeline:GetName()) end)

    local summary = string.format(
        "Timeline: %s\nJSON: %s\n\nMatched clip instances: %d\nAdded Pink clip markers: %d\nAlready present: %d\nSkipped (trimmed out): %d\nJSON files not on timeline: %d",
        timeline_name, json_path, matched_items, added, already, skipped_trim, unmatched_count
    )
    if unmatched_count > 0 then
        summary = summary .. "\n\nUnmatched files:\n" .. join_sorted_keys(unmatched)
    end
    show_message("Meteor Import Complete", summary)
end

local ok, err = xpcall(main, debug.traceback)
if not ok then
    show_message("Meteor Import Error", tostring(err))
end
