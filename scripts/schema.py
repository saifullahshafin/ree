"""Edit-event schema: the shared vocabulary every creator is described in.

Enums are fixed on purpose. Free text lives only in onscreen_text, visual_detail and why,
so style packs from different creators can be counted and compared field by field.
"""

LAYOUT = ["talking_head_wide", "talking_head_medium", "talking_head_close", "talking_head_punch_in",
          "pip_over_graphic", "split_screen", "fullscreen_graphic", "broll_footage",
          "screen_recording", "title_card", "other"]

EVENT_TYPE = ["hard_cut", "jump_cut_same_shot", "punch_in_zoom", "punch_out_zoom", "slow_push_zoom",
              "layout_change", "text_overlay", "graphic_overlay", "chart_or_data", "icon_or_emoji_pop",
              "broll_insert", "screenshot_insert", "transition_effect", "caption_highlight",
              "camera_angle_change", "color_or_filter_change", "chapter_card", "sponsor_segment", "other"]

GRAPHIC_KIND = ["none", "kinetic_text", "text_card", "lower_third", "bullet_list", "quote_card",
                "bar_chart", "line_chart", "pie_or_donut", "number_counter", "table",
                "diagram_or_flowchart", "mind_map_or_whiteboard", "icon_or_emoji", "illustration_2d",
                "3d_object_or_scene", "screenshot_web_or_app", "screenshot_book_or_paper", "photo",
                "stock_footage", "self_shot_broll", "movie_or_meme_clip", "ui_mockup", "map", "other"]

DIMENSION = ["none", "flat_2d", "parallax_2_5d", "true_3d"]

MOTION = ["none", "hard_cut", "pop_scale", "slide", "fade", "typewriter", "draw_on_stroke",
          "mask_reveal", "zoom", "whip_or_blur", "bounce_spring", "wipe", "other"]

TALK_BEAT = ["hook", "promise_or_preview", "framework_point", "list_item", "story_anecdote",
             "statistic_or_number", "quote_or_reference", "example", "definition_or_concept",
             "contrast_or_comparison", "punchline_or_joke", "emotional_or_personal", "cta_or_sponsor",
             "segue", "recap", "outro"]

ENERGY = ["calm", "warm", "curious", "emphatic", "playful", "serious", "excited", "vulnerable"]

AUDIO_CUE = ["none", "sfx_whoosh", "sfx_pop", "sfx_click_or_type", "sfx_ding", "sfx_riser",
             "sfx_other", "music_start", "music_change", "music_stop", "music_duck", "silence_beat"]


def _enum(values):
    return {"type": "STRING", "enum": values}


EVENT = {
    "type": "OBJECT",
    "properties": {
        "anchor_id": {"type": "STRING", "description": "id of the measured change point this event happens at (e.g. C12), or 'none' if it matches no change point"},
        "t_start": {"type": "NUMBER", "description": "absolute seconds; copy the change point time when anchored"},
        "t_end": {"type": "NUMBER", "description": "absolute seconds when the element leaves or the shot ends"},
        "event_type": _enum(EVENT_TYPE),
        "layout": _enum(LAYOUT),
        "graphic_kind": _enum(GRAPHIC_KIND),
        "dimension": _enum(DIMENSION),
        "motion_in": _enum(MOTION),
        "motion_out": _enum(MOTION),
        "onscreen_text": {"type": "STRING", "description": "verbatim on-screen text, empty if none"},
        "spoken_trigger": {"type": "STRING", "description": "the words being spoken as the event starts"},
        "talk_beat": _enum(TALK_BEAT),
        "speaker_energy": _enum(ENERGY),
        "audio_cue": _enum(AUDIO_CUE),
        "visual_detail": {"type": "STRING", "description": "position, colours, font look, size, background, frame placement"},
        "why": {"type": "STRING", "description": "the editorial function of this edit in one sentence"},
        "confidence": {"type": "NUMBER"},
    },
    "required": ["anchor_id", "t_start", "t_end", "event_type", "layout", "graphic_kind", "dimension", "motion_in",
                 "motion_out", "onscreen_text", "spoken_trigger", "talk_beat", "speaker_energy",
                 "audio_cue", "visual_detail", "why", "confidence"],
}

CHUNK = {
    "type": "OBJECT",
    "properties": {
        "segment_summary": {"type": "STRING", "description": "what this stretch of the video is about and how it is edited"},
        "music_present": {"type": "BOOLEAN"},
        "music_character": {"type": "STRING"},
        "dominant_layout": _enum(LAYOUT),
        "events": {"type": "ARRAY", "items": EVENT},
        "skipped_anchors": {"type": "ARRAY", "items": {"type": "STRING"},
                            "description": "change point ids that are not edits (body or camera movement, lighting)"},
    },
    "required": ["segment_summary", "music_present", "music_character", "dominant_layout", "events",
                 "skipped_anchors"],
}
