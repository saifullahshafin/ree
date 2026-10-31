# Gotchas (found while building the first pack, Ali Abdaal, 2026-10-31)

Each entry: what failed, why, what works. Verified on this machine unless marked otherwise.

## Getting the material
- **yt-dlp skips a whole video when its subtitle request fails.** YouTube returned HTTP 429 on the
  timedtext endpoint for the laptop IP; 3 of 5 videos were skipped, not just their captions.
  Fix: `--ignore-errors --sleep-subtitles 8 --sleep-requests 2`. Re-test right after still gave 429, so the
  block lasts a while.
- **Do not depend on YouTube captions at all.** They are rolling auto-captions without clean word timing.
  Transcribe the audio instead (Parakeet on the ARM VM: 26 min of speech in 284 s, about 5.5x real time,
  7,008 words with per-word start/end). Send 16 kHz mono Opus at 24 kbps (about 3 MB per 20 min, 19 s upload
  for five videos); convert to WAV on the server because `hyperframes transcribe` rejects `.opus`.
- 480p is enough for measurement and stills. Download it locally; the YouTube URL is what Gemini reads.

## Gemini access
- `GEMINI_API_KEY` (AI Studio) is blocked for this project (`API_KEY_SERVICE_BLOCKED`). Use Vertex with
  `VERTEX_API_KEY` (express mode, region asia-southeast1). `location='global'` with the API key gives 403.
- Available and working: `gemini-3.1-pro-preview` (used), `gemini-3.5-flash`, `gemini-3-flash-preview`,
  `gemini-2.5-pro`. `gemini-3-pro-preview` is 404 in that region.
- Vertex reads a public YouTube URL directly as `file_data` with `video_metadata` start/end offsets and fps.
  Nothing is uploaded. Offsets work: timestamps Gemini returns are absolute.

## Timing (the big one)
- **Never trust Gemini's timestamps for edit timing.** Pilot v1 (5-min windows, transcript given) put events
  up to 10 s off and anchored them to when the words were spoken, not when the visual changed. It also mislabeled
  a PayPal icon pop as a lower-third bar and missed a chat-bubble pop entirely.
- Its bias where it was close: it floors to whole seconds, landing 0.4 to 1.5 s before the real cut.
- **Fix (v2, adopted): measured anchors.** ffmpeg `scdet` per-frame scores -> `cuts.py` peak-picking.
  Threshold matters: at 10 the small overlays are invisible (PayPal pop scored 5, full-screen card 9, chat
  bubble 3). Use threshold 3 (about 13 change points per minute) and let Gemini skip the ones that are just
  body movement. Send an exact local still for every change point next to the video window. v2 got all
  three v1 misses right at exact times, with the right sound effects.
- `scdet` scores are per frame: one dissolve gives several frames over threshold. Always peak-pick
  (one per 0.5 s) before counting cuts.

## Cost and speed (Gemini 3.1 Pro, Vertex, Oct 2026)
- Video at default resolution is about 66 tokens per frame plus about 25 audio tokens per second.
- v2 window of 150 s at 2 fps with about 28 stills: about 58k input, 5k output, 10k thinking tokens,
  about $0.31 and about 2 minutes. Two hours of footage: about 50 windows, about $15.
- Thinking tokens are billed as output and are as large as the answer itself. Budget for them.

## Verification
- Check a stratified sample (by event_type) on a contact sheet (`sheet.py`) before scaling any prompt
  change. One sheet of 12 tiles at 480 px is cheap to view and caught every v1 problem.

## Quota
- **Preview models share a dynamic quota.** 12 concurrent requests (4 videos x 3 windows) got 14 of about 45
  windows rejected with 429 after 5 retries. Run videos one after another with 2 windows in parallel, and back
  off exponentially with jitter (45 s doubling, cap 300 s, 8 tries). Saved windows are skipped on re-run.

## Label accuracy (v2, measured on 16 stratified events of one full video)
- Anchored events: 12/13 right. Unanchored events (Gemini-added, no measured change point): 1/3 right; graphic
  kind and on-screen text are the usual errors. Treat unanchored events as hints only.

## Sound layer
- The 16 kHz Opus used for transcription cuts everything above 8 kHz, where whoosh and pop detail lives. Use the
  original 44.1 kHz AAC, stream-copied out of the downloaded video (no re-encode). Uploading 116 MB for 2 hours
  took 38 s on 2026-10-31.
- yt-dlp on the ARM VM is blocked by YouTube ("Sign in to confirm you're not a bot"). Download on the laptop.
- Newest demucs pulls `sphn`, which needs a Rust build on aarch64 and fails. Pin `demucs==4.0.1`.
- demucs 4.0.1's CLI saves through torchaudio, which on torch 2.14 needs `torchcodec`. Call the model through
  `demucs.pretrained.get_model` + `demucs.apply.apply_model` and write stems with soundfile (done in sound.py).
- Speed: htdemucs on 3 ARM cores is about 2x slower than real time (60 s audio, 128 s including analysis).
- Measured and model-heard SFX disagree in both directions: on the first minute of fEMHMd7fovM, the meter found a
  rising whoosh peaking exactly on a cut that Gemini labelled silent, and Gemini heard two whooshes under the
  music that the meter missed. Keep both and label the source.

## Look layer
- OpenCV 5 has no `CascadeClassifier` (Haar removed) and no `setLogLevel`. Use `cv2.FaceDetectorYN` with the
  YuNet onnx from opencv_zoo, and set `OPENCV_LOG_LEVEL=ERROR` before import to silence a per-call warning.
- Cast numpy float32 to float before json.dump.
- **Demucs on a whole long video can take down a shared VM.** One pass over a 28 min file needs about 2.4 GB for
  the output tensor alone, plus input and model buffers. With a second audio job running in parallel, the ARM VM
  (23 GB, also running n8n and other services) stopped answering SSH on 2026-10-31. sound.py now separates in
  120 s chunks with 1 s of trimmed context (about 200 MB). Run one audio job at a time, and cap memory
  (`systemd-run --user --scope -p MemoryMax=6G ...`) so the kernel kills the job and not the box.
- **Model "sound effect" labels are unreliable.** Gemini labelled 88 pops and 68 whooshes. On the separated
  music+SFX stem, a loudness test could not tell labelled edits from random moments; spectrograms (ffmpeg
  `showspectrumpic`, read by eye) confirmed whoosh 4/6 and pop 0/6. The model hears a pop because a pop-in usually
  has one. Always verify SFX on spectrograms before writing a sound rule.
- ffmpeg `drawtext` on the ARM VM fails silently without a font; pass `fontfile=` or label tiles locally with PIL.

## Free labelling (label_sheets.py)
- An agent that cannot watch or listen can still read motion and sound as images: a 6-frame strip from -0.3 to
  +1 s shows how an element enters (on the first pack it revealed a two-stage move the stills hid: a pill pops in
  as a lower third, then a card wipes in and the pill rides up to become its header), and a spectrogram strip
  shows whooshes (broad swells) and pops (sharp vertical lines).
- Spectrograms of the full mix are dominated by the voice; use the music+SFX stem from sound.py (`--audio`).
- Sheets at 2 change points per row and 400 px frames stay readable after the image is downscaled for viewing
  (1620 px wide for about 12 change points).
