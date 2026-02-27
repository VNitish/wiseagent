# Session 1 — Mistakes & Fixes

**1. Calling a US Twilio number from India**
Kept getting "no balance" — it's an international call charged by my carrier. Fix: flip it with outgoing call. Have Twilio call my Indian number outbound instead.

**2. Wrong websockets header param**
Used `extra_headers` — crashed. Used `additional_headers` — silently failed. Turns out websockets v13 uses `additional_headers`, but exceptions were swallowed by bare `except: pass`. Added logging to catch it.

**3. Greeting sent before stream_sid was set**
Triggered the greeting right after session.update, but `stream_sid` was still None so all audio got dropped. Fix: send greeting only after receiving Twilio's `start` event.

**4. High latency**
Default VAD silence was 500ms. Reduced to 300ms — noticeably snappier.
