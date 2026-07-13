-- youtube_seekbar.lua — a YouTube-style seek bar for mpv, used by C Media Player.
-- The app's play/pause/volume/fullscreen live on Qt buttons, so this overlay is
-- only the seek bar: a thin red progress line over a gray track, a lighter gray
-- buffered region, a red scrubber dot on hover, click/drag to seek, and it fades
-- out when the mouse is idle (staying up while paused, like YouTube).

local mp = require 'mp'
local assdraw = require 'mp.assdraw'

local state = {
    visible = true,
    last_move = 0,
    mx = -1, my = -1,
    over_bar = false,
    dragging = false,
    duration = 0,
    pos = 0,
    cache_end = 0,
    paused = false,
    seek_bind = false,
}

local HIDE_TIMEOUT = 2.5
local MARGIN   = 14     -- left/right inset of the bar
local BOTTOM   = 26     -- bar centre distance from the window bottom
local H_IDLE   = 3
local H_HOVER  = 5
local DOT_R    = 7
local HIT      = 16     -- vertical hit area around the bar for hover/seek

local overlay = mp.create_osd_overlay("ass-events")

local function dims()
    local d = mp.get_property_native("osd-dimensions")
    if not d or not d.w or d.w == 0 or d.h == 0 then return nil end
    return d
end

local function bar_geom(d)
    return MARGIN, d.w - MARGIN, d.h - BOTTOM   -- x1, x2, centre-y
end

local function fmt(t)
    if not t or t < 0 then t = 0 end
    t = math.floor(t)
    local h = math.floor(t / 3600)
    local m = math.floor((t % 3600) / 60)
    local s = t % 60
    if h > 0 then return string.format("%d:%02d:%02d", h, m, s) end
    return string.format("%d:%02d", m, s)
end

local function render()
    local d = dims()
    if not d then return end
    if not state.visible then
        overlay.data = ""
        overlay:update()
        return
    end

    local x1, x2, cy = bar_geom(d)
    local width = x2 - x1
    local hover = state.over_bar or state.dragging
    local half = (hover and H_HOVER or H_IDLE) / 2

    local dur = state.duration or 0
    local frac = (dur > 0) and math.max(0, math.min(1, state.pos / dur)) or 0
    local buf  = (dur > 0) and math.max(0, math.min(1, state.cache_end / dur)) or 0

    local fs = math.max(13, math.floor(d.h * 0.026))
    local text_bottom = cy - half - 8           -- an1 anchor: text's bottom edge

    local a = assdraw.ass_new()

    -- bottom scrim for readability — tall enough to cover the time text above
    -- the bar plus a little padding, at any window size
    a:new_event()
    a:pos(0, 0)
    a:append("{\\bord0\\shad0\\1c&H000000&\\1a&HBE&}")
    a:draw_start(); a:rect_cw(0, math.min(d.h - 74, text_bottom - fs - 8), d.w, d.h); a:draw_stop()

    -- time text, bottom-left, sitting just above the bar (an1 = bottom-left
    -- anchor, so this y is the text's bottom edge; 8px clearance over the bar)
    a:new_event()
    a:an(1)
    a:pos(x1, text_bottom)
    a:append(string.format("{\\fs%d\\bord1.4\\3c&H000000&\\1c&HFFFFFF&}%s / %s",
        fs, fmt(state.pos), fmt(dur)))

    -- track (translucent white)
    a:new_event(); a:pos(0, 0)
    a:append("{\\bord0\\shad0\\1c&HFFFFFF&\\1a&HB4&}")
    a:draw_start(); a:rect_cw(x1, cy - half, x2, cy + half); a:draw_stop()

    -- buffered (a touch brighter)
    if buf > 0 then
        a:new_event(); a:pos(0, 0)
        a:append("{\\bord0\\shad0\\1c&HFFFFFF&\\1a&H82&}")
        a:draw_start(); a:rect_cw(x1, cy - half, x1 + width * buf, cy + half); a:draw_stop()
    end

    -- played (YouTube red = #FF0000 -> ASS &H0000FF&)
    a:new_event(); a:pos(0, 0)
    a:append("{\\bord0\\shad0\\1c&H0000FF&}")
    a:draw_start(); a:rect_cw(x1, cy - half, x1 + width * frac, cy + half); a:draw_stop()

    -- scrubber dot on hover / drag
    if hover then
        local px = x1 + width * frac
        a:new_event(); a:pos(0, 0)
        a:append("{\\bord0\\shad0\\1c&H0000FF&}")
        a:draw_start(); a:round_rect_cw(px - DOT_R, cy - DOT_R, px + DOT_R, cy + DOT_R, DOT_R); a:draw_stop()
    end

    overlay.res_x = d.w
    overlay.res_y = d.h
    overlay.data = a.text
    overlay:update()
end

local function show()
    state.visible = true
    state.last_move = mp.get_time()
    render()
end

local function over_bar(d, x, y)
    local x1, x2, cy = bar_geom(d)
    return y >= cy - HIT and y <= cy + HIT and x >= x1 - 6 and x <= x2 + 6
end

local function seek_to(d, x, exact)
    local x1, x2 = bar_geom(d)
    local frac = math.max(0, math.min(1, (x - x1) / (x2 - x1)))
    if (state.duration or 0) > 0 then
        -- Scrub with fast keyframe seeks so a drag stays smooth even on long
        -- videos; land precisely with one exact seek when the drag ends.
        mp.commandv("seek", frac * state.duration, "absolute",
            exact and "exact" or "keyframes")
    end
end

local function on_click(e)
    local d = dims()
    if not d then return end
    if e.event == "down" then
        state.dragging = true
        seek_to(d, state.mx, false)
    elseif e.event == "up" then
        state.dragging = false
        seek_to(d, state.mx, true)   -- final precise landing
    end
end

-- The seek binding is only installed while the cursor is over the bar, so a
-- click anywhere else falls through to the app's own MBTN_LEFT handling
-- (e.g. drag-to-move on the detached window).
local function set_seek_binding(on)
    if on == state.seek_bind then return end
    state.seek_bind = on
    if on then
        mp.add_forced_key_binding("mbtn_left", "ytseek_click", on_click, {complex = true})
    else
        mp.remove_key_binding("ytseek_click")
    end
end

mp.observe_property("mouse-pos", "native", function(_, v)
    if not v then return end
    state.mx, state.my = v.x, v.y
    local d = dims()
    if d then state.over_bar = over_bar(d, v.x, v.y) end
    set_seek_binding(state.over_bar or state.dragging)
    -- Any mouse movement reveals the bar; the idle timer hides it again while
    -- playing. (Don't gate on v.hover — it's unreliable under wid/XWayland
    -- embedding and reads false during playback, which hid the bar entirely.)
    show()
    if state.dragging and d then seek_to(d, v.x) end
end)

mp.observe_property("time-pos", "number", function(_, v)
    state.pos = v or 0
    if state.visible then render() end
end)
mp.observe_property("duration", "number", function(_, v) state.duration = v or 0 end)
mp.observe_property("demuxer-cache-time", "number", function(_, v) state.cache_end = v or 0 end)
mp.observe_property("pause", "bool", function(_, v)
    state.paused = v or false
    show()
end)

mp.add_periodic_timer(0.25, function()
    if state.paused then
        if not state.visible then show() end
        return
    end
    if state.visible and not state.dragging
       and (mp.get_time() - state.last_move) > HIDE_TIMEOUT then
        state.visible = false
        set_seek_binding(false)
        render()
    end
end)

mp.register_event("file-loaded", show)
